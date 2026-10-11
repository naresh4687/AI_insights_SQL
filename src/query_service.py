"""Query service: turn a question into validated SQL, run it safely, and record history.

``answer_question()`` is the single path used by both Demo Mode and AI Mode — only the
SQL source (``generate_sql``) differs. A question can be about another registered dataset
(``target``, see ``data_access``): its SQL then runs on that dataset's database with only
that dataset's tables allowed. History is always written to the main database. Every SQL candidate goes through ``run_query()``,
which validates it and executes it on a read-only connection.
"""

import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Iterable

import pandas as pd

from src import database, demo_queries
from src.core.models import DEMO_DATASET_ID
from src.sql_guard import ALLOWED_TABLES, ReadOnlyAuthorizer, UnsafeSQLError, validate_sql

if TYPE_CHECKING:
    from src.data_access import Target

logger = logging.getLogger(__name__)

MAX_QUESTION_LENGTH = 500
DEFAULT_MAX_ROWS = 1000
DEFAULT_TIMEOUT_SECONDS = 3.0
MAX_VALUE_LENGTH = 1_000_000  # SQLite limit on any single string/blob value
PROGRESS_INTERVAL = 1000  # SQLite VM instructions between timeout checks

# SQLite error prefixes that are safe and helpful to show users verbatim.
_USER_SAFE_ERRORS = ("no such column", "ambiguous column name", "misuse of", "no such function")


@dataclass
class QueryResult:
    sql: str
    data: pd.DataFrame
    truncated: bool


@dataclass
class Answer:
    question: str
    sql: str
    data: pd.DataFrame
    truncated: bool
    source: str  # "demo" or "ai" — where the SQL came from
    dataset_id: str = DEMO_DATASET_ID  # the dataset the question was about


class QueryError(Exception):
    """A query failed. ``message`` is safe for users; ``status`` is a history status."""

    def __init__(self, message: str, status: str = "error"):
        super().__init__(message)
        self.message = message
        self.status = status


class SqlGenerationError(Exception):
    """A SQL source (e.g. the AI service) could not produce SQL. ``message`` is user-safe."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def answer_question(
    db_path: Path,
    question: str,
    generate_sql: Callable[[str], str] = demo_queries.lookup_sql,
    source: str = "demo",
    target: "Target | None" = None,
    user_id: str | None = None,
) -> Answer:
    """Answer ``question`` using SQL from ``generate_sql``, recording the outcome in history.

    ``db_path`` is the main database (demo data and history). ``target`` is the dataset the
    question is about; ``None`` means the demo data in ``db_path``.
    ``user_id`` is recorded with the history entry (who asked).
    Empty or overlong questions are rejected without a history entry.
    Raises ``QueryError`` with a user-safe message on any failure.
    """
    if not isinstance(question, str) or not question.strip():
        raise QueryError("Please enter a question.", status="rejected")
    question = question.strip()
    if len(question) > MAX_QUESTION_LENGTH:
        raise QueryError(
            f"The question is too long (limit {MAX_QUESTION_LENGTH} characters).", status="rejected"
        )

    dataset_id = target.dataset_id if target else DEMO_DATASET_ID
    query_db = target.db_path if target else db_path
    scope = target.scope if target else ALLOWED_TABLES
    if source == "demo" and dataset_id != DEMO_DATASET_ID:
        # Demo SQL is written for the demo tables; never run it against another dataset.
        _record_history(db_path, question, None, "rejected", dataset_id, user_id)
        raise QueryError(
            f"Demo Mode only answers the example questions about the demo sales data. To ask about "
            f"'{target.dataset.name}', switch to AI Mode, or run your own SQL in the SQL Explorer.",
            status="rejected",
        )

    try:
        candidate_sql = generate_sql(question)
    except demo_queries.UnsupportedQuestionError:
        _record_history(db_path, question, None, "rejected", dataset_id, user_id)
        raise QueryError(
            "Demo Mode only answers the example questions. Choose one from the list, "
            "or switch to AI Mode to ask your own questions.",
            status="rejected",
        ) from None
    except SqlGenerationError as exc:
        logger.warning("SQL generation failed (source=%s): %s", source, exc.message)
        _record_history(db_path, question, None, "error", dataset_id, user_id)
        raise QueryError(exc.message) from None
    except Exception:
        logger.exception("SQL generation failed (source=%s)", source)
        _record_history(db_path, question, None, "error", dataset_id, user_id)
        raise QueryError("A SQL query could not be generated for this question.") from None

    try:
        result = run_query(query_db, candidate_sql, allowed_tables=scope)
    except QueryError as exc:
        _record_history(db_path, question, None, exc.status, dataset_id, user_id)
        raise

    _record_history(db_path, question, result.sql, "success", dataset_id, user_id)
    return Answer(question, result.sql, result.data, result.truncated, source, dataset_id)


def _record_history(db_path: Path, question: str, sql: str | None, status: str,
                    dataset_id: str = DEMO_DATASET_ID, user_id: str | None = None) -> None:
    """Store a history entry. A history failure must never break answering."""
    try:
        database.add_history(db_path, question, sql, status, dataset_id, user_id)
    except (sqlite3.Error, OSError):
        logger.exception("Could not record query history")


def run_query(
    db_path: Path,
    sql: str,
    max_rows: int = DEFAULT_MAX_ROWS,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    allowed_tables: Iterable[str] = ALLOWED_TABLES,
    params: tuple = (),
) -> QueryResult:
    """Validate and execute ``sql`` read-only, returning at most ``max_rows`` rows.

    Only tables in ``allowed_tables`` may be read (both guard layers enforce it). ``params``
    are bound to ``?`` placeholders (values are never put into the SQL text).
    """
    try:
        safe_sql = validate_sql(sql, allowed_tables)
    except UnsafeSQLError as exc:
        raise QueryError(str(exc), status="rejected") from None

    try:
        conn = database.connect_readonly(db_path)
    except sqlite3.Error:
        logger.exception("Could not open database %s", db_path)
        raise QueryError("The database is not available. Please try again later.") from None

    authorizer = ReadOnlyAuthorizer(allowed_tables)
    try:
        conn.execute("PRAGMA query_only = ON")
        conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_VALUE_LENGTH)
        conn.set_authorizer(authorizer)
        deadline = time.monotonic() + timeout_seconds
        conn.set_progress_handler(lambda: time.monotonic() > deadline, PROGRESS_INTERVAL)

        cursor = conn.execute(safe_sql, params)
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchmany(max_rows + 1)
    except sqlite3.DatabaseError as exc:
        raise _to_query_error(exc, authorizer) from None
    finally:
        conn.close()

    truncated = len(rows) > max_rows
    return QueryResult(sql=safe_sql, data=pd.DataFrame(rows[:max_rows], columns=columns), truncated=truncated)


def _to_query_error(exc: sqlite3.DatabaseError, authorizer: ReadOnlyAuthorizer) -> QueryError:
    """Translate a SQLite error into a user-safe QueryError, logging the details."""
    text = str(exc)
    if authorizer.denied_reason:
        return QueryError(authorizer.denied_reason, status="rejected")
    if "interrupted" in text:
        return QueryError("The query took too long and was stopped. Try a simpler question.")
    if text.lower().startswith(_USER_SAFE_ERRORS):
        return QueryError(f"The query could not be run: {text}.")
    logger.error("Query failed: %s", text)
    return QueryError("The query could not be run.")
