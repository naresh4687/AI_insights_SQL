"""Session state and the single entry point the UI uses to answer anything.

Every request — a chat question, a suggestion, a rerun from history, or SQL typed in the
SQL Explorer — goes through ``run()`` → ``query_service.answer_question()``, so the same
validation, read-only execution and history recording apply everywhere.

The signed-in account (``current_user()``, set by ``src.ui.auth`` before any page runs) limits
which datasets, dashboards and connections the pages offer, and is passed to every lookup that
checks access, so a page cannot reach what the user may not read.
"""

import functools
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

import streamlit as st

from src import accounts, ai_providers, audit, config, data_access, database, demo_queries
from src.core.models import DEMO_DATASET_ID, Dataset
from src.query_service import Answer, QueryError, answer_question

logger = logging.getLogger(__name__)

DEMO_MODE = "Demo Mode"
PAGES = {
    "dashboard": "views/dashboard.py",
    "analyst": "views/analyst.py",
    "history": "views/history.py",
    "explorer": "views/explorer.py",
    "settings": "views/settings.py",
    "import": "views/import_data.py",
    "connections": "views/connections.py",
    "datasets": "views/datasets.py",
    "studio": "views/studio.py",
    "users": "views/users.py",
}

SQL_SOURCES = {
    "demo": demo_queries.lookup_sql,
    "ai": ai_providers.generate_sql,
    "sql": lambda sql: sql,  # SQL Explorer: the user's SQL is the candidate
}


def current_user() -> accounts.User:
    """The signed-in account; the local user when sign-in is off (or before ``auth`` ran)."""
    return st.session_state.get("user") or accounts.LOCAL_USER


def signed_in() -> bool:
    """True when sign-in is on (accounts are separate); False for the single local user."""
    return current_user().user_id != accounts.LOCAL_USER_ID


def history_user() -> str | None:
    """Whose history to show and record: the signed-in user's own; everyone's without sign-in."""
    return current_user().user_id if signed_in() else None


def record(action: str, object_type: str = "", object_id: str = "", detail: str = "") -> None:
    """Add an audit-log entry for the current user."""
    audit.record(current_user(), action, object_type, object_id, detail)


def can_change(owner: str | None) -> bool:
    return accounts.can_change(current_user(), owner)


def ai_mode_label() -> str:
    return f"AI Mode ({ai_providers.display_name()})"


def mode_options() -> list[str]:
    return [DEMO_MODE, ai_mode_label()]


def current_source() -> str:
    """'demo' or 'ai', from the sidebar mode selector."""
    return "demo" if st.session_state.get("mode", DEMO_MODE) == DEMO_MODE else "ai"


def current_dataset_id() -> str:
    """The dataset chosen in the sidebar (the demo data by default)."""
    return st.session_state.get("dataset") or DEMO_DATASET_ID


def choose_dataset(dataset_id: str) -> None:
    """Select a dataset from a page (applied by the sidebar on the next run, because the
    sidebar's widget has already been drawn in this one)."""
    st.session_state["pending_dataset"] = dataset_id


def apply_pending_dataset() -> None:
    """Call before drawing the sidebar's dataset selector."""
    if "pending_dataset" in st.session_state:
        st.session_state["dataset"] = st.session_state.pop("pending_dataset")


def current_target(path: Path | None = None) -> data_access.Target:
    """The selected dataset's location and scope; the demo data if it no longer exists."""
    path = path or db_path()
    try:
        return data_access.target(current_dataset_id(), path, current_user())
    except data_access.UnknownDatasetError:
        return data_access.target(DEMO_DATASET_ID, path, current_user())


def dataset(dataset_id: str) -> Dataset | None:
    """A dataset the current user may read, or None (removed, or not theirs)."""
    found = data_access.catalog().get(dataset_id)
    return found if found is not None and data_access.visible(found, current_user()) else None


def visible_datasets() -> list[Dataset]:
    return data_access.datasets(current_user())


def dataset_names() -> dict[str, str]:
    return {d.dataset_id: d.name for d in visible_datasets()}


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
    dataset_name: str = "Demo sales"
    dataset_id: str = DEMO_DATASET_ID


def _sql_source(source: str, dataset: Dataset):
    if source == "ai" and dataset.dataset_id != DEMO_DATASET_ID:
        return functools.partial(ai_providers.generate_sql, dataset=dataset)
    return SQL_SOURCES[source]


def run(path: Path, text: str, source: str) -> Turn:
    """Answer ``text`` about the selected dataset through the shared pipeline; never raises."""
    start = time.perf_counter()
    answer, error = None, None
    target = current_target(path)
    try:
        answer = answer_question(path, text, generate_sql=_sql_source(source, target.dataset), source=source,
                                 target=None if target.is_demo else target, user_id=history_user())
    except QueryError as exc:
        error = (exc.status, exc.message)
    except Exception:
        logger.exception("Unexpected error while answering")
        error = ("error", "Something went wrong while answering. Please try again.")
    shown = answer.question if answer else (text.strip() if isinstance(text, str) else "")
    return Turn(shown, source, answer, error, time.perf_counter() - start, target.dataset.name, target.dataset_id)


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
