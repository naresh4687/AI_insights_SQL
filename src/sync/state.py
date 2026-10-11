"""Refresh settings, the run log, and per-dataset locks, stored in the app database."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.storage import app_db

MODES = {"full": "Full (replace all rows)", "incremental": "Incremental (new or changed rows)"}
MIN_INTERVAL_MINUTES = 5
LOCK_STALE_AFTER = timedelta(minutes=30)


@dataclass(frozen=True)
class RefreshSettings:
    dataset_id: str
    mode: str = "full"
    key_column: str | None = None  # incremental: unique, non-empty column identifying a row
    cursor_column: str | None = None  # incremental: value that grows for new or changed rows
    interval_minutes: int | None = None  # schedule; None = manual only
    enabled: bool = False  # whether the worker runs the schedule
    next_run_at: str | None = None
    last_cursor: str | None = None  # highest cursor value seen by the last successful refresh


@dataclass(frozen=True)
class Run:
    run_id: int
    dataset_id: str
    trigger: str
    mode: str
    status: str
    attempts: int
    started_at: str
    finished_at: str | None
    rows_fetched: int | None
    rows_inserted: int | None
    rows_updated: int | None
    rows_total: int | None
    message: str | None


def utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def now() -> datetime:
    return datetime.now(timezone.utc)


class SyncState:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        app_db.migrate(self.db_path)

    def _conn(self) -> sqlite3.Connection:
        return app_db.connect(self.db_path)

    # --- Settings ---------------------------------------------------------------------

    def settings(self, dataset_id: str) -> RefreshSettings:
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM refresh_settings WHERE dataset_id = ?", (dataset_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            return RefreshSettings(dataset_id)
        return RefreshSettings(row["dataset_id"], row["mode"], row["key_column"], row["cursor_column"],
                               row["interval_minutes"], bool(row["enabled"]), row["next_run_at"], row["last_cursor"])

    def save_settings(self, settings: RefreshSettings) -> RefreshSettings:
        """Store settings. Enabling a schedule (or changing its interval) sets the next run."""
        previous = self.settings(settings.dataset_id)
        next_run = settings.next_run_at
        if settings.enabled and settings.interval_minutes:
            if not previous.enabled or previous.interval_minutes != settings.interval_minutes or not next_run:
                next_run = utc(now() + timedelta(minutes=settings.interval_minutes))
        else:
            next_run = None
        last_cursor = settings.last_cursor
        if (previous.mode, previous.key_column, previous.cursor_column) != (
                settings.mode, settings.key_column, settings.cursor_column):
            last_cursor = None  # a different incremental definition starts from the beginning
        conn = self._conn()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO refresh_settings (dataset_id, mode, key_column, cursor_column, interval_minutes, "
                    "enabled, next_run_at, last_cursor, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(dataset_id) DO UPDATE SET mode = excluded.mode, key_column = excluded.key_column, "
                    "cursor_column = excluded.cursor_column, interval_minutes = excluded.interval_minutes, "
                    "enabled = excluded.enabled, next_run_at = excluded.next_run_at, "
                    "last_cursor = excluded.last_cursor, updated_at = excluded.updated_at",
                    (settings.dataset_id, settings.mode, settings.key_column, settings.cursor_column,
                     settings.interval_minutes, int(settings.enabled), next_run, last_cursor, app_db.utc_now()))
        finally:
            conn.close()
        return self.settings(settings.dataset_id)

    def after_run(self, dataset_id: str, success: bool, cursor: str | None = None) -> None:
        """Schedule the next run (from now, so missed runs do not pile up) and keep the cursor."""
        current = self.settings(dataset_id)
        next_run = (utc(now() + timedelta(minutes=current.interval_minutes))
                    if current.enabled and current.interval_minutes else None)
        conn = self._conn()
        try:
            with conn:
                conn.execute("UPDATE refresh_settings SET next_run_at = ?, last_cursor = ? WHERE dataset_id = ?",
                             (next_run, cursor if success and cursor is not None else current.last_cursor, dataset_id))
        finally:
            conn.close()

    def due(self, at: datetime | None = None) -> list[str]:
        """Datasets whose schedule is enabled and due."""
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT dataset_id FROM refresh_settings WHERE enabled = 1 AND next_run_at IS NOT NULL "
                "AND next_run_at <= ? ORDER BY next_run_at", (utc(at or now()),)).fetchall()
        finally:
            conn.close()
        return [r[0] for r in rows]

    # --- Run log ----------------------------------------------------------------------

    def start_run(self, dataset_id: str, trigger: str, mode: str) -> int:
        conn = self._conn()
        try:
            with conn:
                cursor = conn.execute("INSERT INTO refresh_runs (dataset_id, trigger, mode, status, started_at) "
                                      "VALUES (?, ?, ?, 'running', ?)", (dataset_id, trigger, mode, app_db.utc_now()))
            return cursor.lastrowid
        finally:
            conn.close()

    def finish_run(self, run_id: int, status: str, message: str, attempts: int = 1, rows_fetched: int | None = None,
                   rows_inserted: int | None = None, rows_updated: int | None = None,
                   rows_total: int | None = None) -> None:
        conn = self._conn()
        try:
            with conn:
                conn.execute("UPDATE refresh_runs SET status = ?, message = ?, attempts = ?, finished_at = ?, "
                             "rows_fetched = ?, rows_inserted = ?, rows_updated = ?, rows_total = ? WHERE run_id = ?",
                             (status, message, attempts, app_db.utc_now(), rows_fetched, rows_inserted, rows_updated,
                              rows_total, run_id))
        finally:
            conn.close()

    def runs(self, dataset_id: str, limit: int = 20) -> list[Run]:
        conn = self._conn()
        try:
            rows = conn.execute("SELECT * FROM refresh_runs WHERE dataset_id = ? ORDER BY run_id DESC LIMIT ?",
                                (dataset_id, limit)).fetchall()
        finally:
            conn.close()
        return [Run(**dict(r)) for r in rows]

    # --- Locks ------------------------------------------------------------------------

    def acquire(self, dataset_id: str, owner: str) -> bool:
        """Take the dataset's refresh lock; False if another refresh holds a fresh lock."""
        conn = self._conn()
        try:
            with conn:
                conn.execute("DELETE FROM refresh_locks WHERE dataset_id = ? AND acquired_at < ?",
                             (dataset_id, utc(now() - LOCK_STALE_AFTER)))  # a crashed run's lock
                conn.execute("INSERT INTO refresh_locks VALUES (?, ?, ?)", (dataset_id, owner, app_db.utc_now()))
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

    def release(self, dataset_id: str, owner: str) -> None:
        conn = self._conn()
        try:
            with conn:
                conn.execute("DELETE FROM refresh_locks WHERE dataset_id = ? AND owner = ?", (dataset_id, owner))
        finally:
            conn.close()
