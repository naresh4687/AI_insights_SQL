"""Session state and the single entry point the UI uses to answer anything.

Every request — a chat question, a suggestion, a rerun from history, or SQL typed in the
SQL Explorer — goes through ``run()`` → ``query_service.answer_question()``, so the same
validation, read-only execution and history recording apply everywhere.
"""

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

import streamlit as st

from src import ai_providers, config, database, demo_queries
from src.query_service import Answer, QueryError, answer_question

logger = logging.getLogger(__name__)

DEMO_MODE = "Demo Mode"
PAGES = {
    "dashboard": "views/dashboard.py",
    "analyst": "views/analyst.py",
    "history": "views/history.py",
    "explorer": "views/explorer.py",
    "settings": "views/settings.py",
}

SQL_SOURCES = {
    "demo": demo_queries.lookup_sql,
    "ai": ai_providers.generate_sql,
    "sql": lambda sql: sql,  # SQL Explorer: the user's SQL is the candidate
}


def ai_mode_label() -> str:
    return f"AI Mode ({ai_providers.display_name()})"


def mode_options() -> list[str]:
    return [DEMO_MODE, ai_mode_label()]


def current_source() -> str:
    """'demo' or 'ai', from the sidebar mode selector."""
    return "demo" if st.session_state.get("mode", DEMO_MODE) == DEMO_MODE else "ai"


def source_label(source: str) -> str:
    return {
        "demo": "Demo Mode — predefined SQL (no AI request was made)",
        "sql": "Your SQL — validated before running",
        "ai": f"AI-generated SQL ({ai_providers.display_name()} model) — validated before running",
    }[source]


@st.cache_resource
def _prepare_database(db_path: str) -> str:
    """Create and seed the database on first run (it is not committed to Git)."""
    database.ensure_database(Path(db_path))
    return db_path


def db_path() -> Path:
    return Path(_prepare_database(str(config.get_db_path())))


@st.cache_data(ttl=15, show_spinner=False)
def _cached_ai_status(settings: tuple) -> tuple[bool, str]:
    """``settings`` keys the cache to the configuration; it holds only whether a key is
    set, so no secret is ever cached."""
    return ai_providers.check_status()


def ai_status() -> tuple[bool, str]:
    """The provider's real availability check (key accepted, model exists), cached 15 s."""
    names = ("AI_PROVIDER", "GEMINI_MODEL", "GEMINI_BASE_URL", "HF_MODEL", "HF_BASE_URL")
    settings = tuple(os.getenv(name) for name in names) + (
        config.get_gemini_api_key() is not None,
        config.get_hf_token() is not None,
    )
    return _cached_ai_status(settings)


@dataclass
class Turn:
    """One request and its outcome, as shown in the chat or the SQL Explorer."""

    question: str
    source: str
    answer: Answer | None
    error: tuple[str, str] | None  # (status, user-safe message)
    seconds: float  # measured around answer_question()


def run(path: Path, text: str, source: str) -> Turn:
    """Answer ``text`` through the shared pipeline; never raises."""
    start = time.perf_counter()
    answer, error = None, None
    try:
        answer = answer_question(path, text, generate_sql=SQL_SOURCES[source], source=source)
    except QueryError as exc:
        error = (exc.status, exc.message)
    except Exception:
        logger.exception("Unexpected error while answering")
        error = ("error", "Something went wrong while answering. Please try again.")
    shown = answer.question if answer else (text.strip() if isinstance(text, str) else "")
    return Turn(shown, source, answer, error, time.perf_counter() - start)


def chat() -> list[Turn]:
    return st.session_state.setdefault("chat", [])


def queue_question(text: str, source: str) -> None:
    """Ask ``text`` on the next AI Analyst run (used by suggestions and history reruns)."""
    st.session_state["pending_question"] = (text, source)


def take_pending_question() -> tuple[str, str] | None:
    return st.session_state.pop("pending_question", None)


def reset_chat() -> None:
    st.session_state["chat"] = []
    st.session_state.pop("pending_question", None)
