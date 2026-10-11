"""Audit log: who changed what, and when (append-only).

Records sign-ins (and refused sign-ins), user and role changes, and every create, change,
share and delete of datasets, connections and dashboards. Entries hold names and ids only —
never data, SQL results, passwords or tokens. The table refuses UPDATE and DELETE (triggers in
migration 5), so entries cannot be altered from the app.

Recording never breaks the action being recorded: a failure is logged and ignored.
"""

import logging
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src import config
from src.storage import app_db

if TYPE_CHECKING:
    from src.accounts import User

logger = logging.getLogger(__name__)

MAX_DETAIL_LENGTH = 500


@dataclass(frozen=True)
class Event:
    event_id: int
    at: str
    user_id: str | None
    user_email: str
    action: str
    object_type: str
    object_id: str
    detail: str


def record(user: "User | None", action: str, object_type: str = "", object_id: str = "", detail: str = "",
           *, email: str | None = None) -> None:
    """Add an entry. ``user`` None is the system (or an unknown person, with ``email``)."""
    try:
        db_path = config.get_app_db_path()
        app_db.migrate(db_path)
        conn = app_db.connect(db_path)
        try:
            with conn:
                conn.execute(
                    "INSERT INTO audit_log (at, user_id, user_email, action, object_type, object_id, detail) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (app_db.utc_now(), user.user_id if user else None,
                     (email if email is not None else (user.email if user else "")) or "",
                     action, object_type, str(object_id or ""), (detail or "")[:MAX_DETAIL_LENGTH]))
        finally:
            conn.close()
    except (sqlite3.Error, OSError, app_db.MigrationError):
        logger.exception("Could not record audit event %s", action)


def recent(limit: int = 200, user_id: str | None = None, action_prefix: str = "") -> list[Event]:
    """Newest first, optionally only one user's actions or one kind (``"dashboard."``)."""
    db_path = config.get_app_db_path()
    app_db.migrate(db_path)
    clauses, params = [], []
    if user_id:
        clauses.append("user_id = ?")
        params.append(user_id)
    if action_prefix:
        clauses.append("action LIKE ? ESCAPE '\\'")
        params.append(action_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = app_db.connect(db_path)
    try:
        rows = conn.execute(f"SELECT * FROM audit_log {where} ORDER BY event_id DESC LIMIT ?",
                            (*params, limit)).fetchall()
    finally:
        conn.close()
    return [Event(**dict(r)) for r in rows]
