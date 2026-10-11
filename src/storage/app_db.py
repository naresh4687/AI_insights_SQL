"""App metadata database (``data/app.db``) and its versioned schema migrations.

Migrations are append-only: each has a number and SQL, and is applied once, in order,
inside its own transaction. The applied versions are recorded in ``schema_migrations``.
Never edit a released migration — add a new one. A database newer than this code is
refused rather than modified.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# (version, description, SQL). Append only.
MIGRATIONS: tuple[tuple[int, str, str | tuple[str, ...]], ...] = (
    (1, "dataset catalog", """
        CREATE TABLE datasets (
            dataset_id      TEXT PRIMARY KEY,
            name            TEXT NOT NULL UNIQUE,
            source_type     TEXT NOT NULL,
            storage         TEXT NOT NULL,
            description     TEXT NOT NULL DEFAULT '',
            owner           TEXT,
            builtin         INTEGER NOT NULL DEFAULT 0 CHECK (builtin IN (0, 1)),
            quality_status  TEXT NOT NULL,
            refresh_status  TEXT NOT NULL,
            extra_json      TEXT NOT NULL DEFAULT '{}',
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL,
            last_refresh_at TEXT
        );
        CREATE TABLE dataset_tables (
            dataset_id   TEXT NOT NULL REFERENCES datasets(dataset_id) ON DELETE CASCADE,
            table_name   TEXT NOT NULL,
            position     INTEGER NOT NULL,
            columns_json TEXT NOT NULL,
            row_count    INTEGER,
            PRIMARY KEY (dataset_id, table_name)
        );
    """),
    (2, "connection profiles", """
        CREATE TABLE connections (
            connection_id  TEXT PRIMARY KEY,
            name           TEXT NOT NULL UNIQUE,
            kind           TEXT NOT NULL CHECK (kind IN ('postgres', 'mysql', 'rest')),
            settings_json  TEXT NOT NULL,
            secret         BLOB,
            created_at     TEXT NOT NULL,
            updated_at     TEXT NOT NULL,
            last_tested_at TEXT,
            last_test_ok   INTEGER CHECK (last_test_ok IN (0, 1))
        );
    """),
    (3, "refresh settings, run log and locks", """
        CREATE TABLE refresh_settings (
            dataset_id       TEXT PRIMARY KEY REFERENCES datasets(dataset_id) ON DELETE CASCADE,
            mode             TEXT NOT NULL CHECK (mode IN ('full', 'incremental')),
            key_column       TEXT,
            cursor_column    TEXT,
            interval_minutes INTEGER CHECK (interval_minutes IS NULL OR interval_minutes >= 5),
            enabled          INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
            next_run_at      TEXT,
            last_cursor      TEXT,
            updated_at       TEXT NOT NULL
        );
        CREATE TABLE refresh_runs (
            run_id        INTEGER PRIMARY KEY,
            dataset_id    TEXT NOT NULL,
            trigger       TEXT NOT NULL CHECK (trigger IN ('manual', 'scheduled')),
            mode          TEXT NOT NULL,
            status        TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed', 'skipped')),
            attempts      INTEGER NOT NULL DEFAULT 1,
            started_at    TEXT NOT NULL,
            finished_at   TEXT,
            rows_fetched  INTEGER,
            rows_inserted INTEGER,
            rows_updated  INTEGER,
            rows_total    INTEGER,
            message       TEXT
        );
        CREATE INDEX idx_refresh_runs_dataset ON refresh_runs(dataset_id, run_id);
        CREATE TABLE refresh_locks (
            dataset_id  TEXT PRIMARY KEY,
            owner       TEXT NOT NULL,
            acquired_at TEXT NOT NULL
        );
    """),
    (4, "dashboards", """
        CREATE TABLE dashboards (
            dashboard_id TEXT PRIMARY KEY,
            name         TEXT NOT NULL UNIQUE,
            description  TEXT NOT NULL DEFAULT '',
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        );
        CREATE TABLE dashboard_widgets (
            widget_id    INTEGER PRIMARY KEY,
            dashboard_id TEXT NOT NULL REFERENCES dashboards(dashboard_id) ON DELETE CASCADE,
            position     INTEGER NOT NULL,
            title        TEXT NOT NULL,
            question     TEXT NOT NULL DEFAULT '',
            dataset_id   TEXT NOT NULL,
            sql          TEXT NOT NULL,
            chart_kind   TEXT NOT NULL,
            width        TEXT NOT NULL CHECK (width IN ('full', 'half', 'third')),
            created_at   TEXT NOT NULL
        );
        CREATE TABLE dashboard_filters (
            filter_id    INTEGER PRIMARY KEY,
            dashboard_id TEXT NOT NULL REFERENCES dashboards(dashboard_id) ON DELETE CASCADE,
            kind         TEXT NOT NULL CHECK (kind IN ('date', 'category', 'number')),
            column_name  TEXT NOT NULL,
            label        TEXT NOT NULL,
            UNIQUE (dashboard_id, column_name)
        );
    """),
    # A tuple: these statements contain ';' inside trigger bodies, so they are not split.
    (5, "user accounts, ownership, sharing and audit log", (
        """CREATE TABLE users (
            user_id       TEXT PRIMARY KEY,
            email         TEXT NOT NULL UNIQUE,
            name          TEXT NOT NULL DEFAULT '',
            role          TEXT NOT NULL CHECK (role IN ('viewer', 'editor', 'admin')),
            active        INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
            subject       TEXT UNIQUE,
            invited_by    TEXT,
            created_at    TEXT NOT NULL,
            last_login_at TEXT
        )""",
        "ALTER TABLE datasets ADD COLUMN shared INTEGER NOT NULL DEFAULT 0 CHECK (shared IN (0, 1))",
        "ALTER TABLE dashboards ADD COLUMN owner TEXT",
        "ALTER TABLE dashboards ADD COLUMN shared INTEGER NOT NULL DEFAULT 0 CHECK (shared IN (0, 1))",
        "ALTER TABLE connections ADD COLUMN owner TEXT",
        """CREATE TABLE audit_log (
            event_id    INTEGER PRIMARY KEY,
            at          TEXT NOT NULL,
            user_id     TEXT,
            user_email  TEXT NOT NULL DEFAULT '',
            action      TEXT NOT NULL,
            object_type TEXT NOT NULL DEFAULT '',
            object_id   TEXT NOT NULL DEFAULT '',
            detail      TEXT NOT NULL DEFAULT ''
        )""",
        """CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON audit_log
           BEGIN SELECT RAISE(ABORT, 'The audit log cannot be changed.'); END""",
        """CREATE TRIGGER audit_log_no_delete BEFORE DELETE ON audit_log
           BEGIN SELECT RAISE(ABORT, 'The audit log cannot be changed.'); END""",
    )),
)


class MigrationError(RuntimeError):
    """The database schema cannot be brought up to date safely."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: Path) -> sqlite3.Connection:
    """Read-write connection with foreign keys enforced and rows accessible by name."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def current_version(conn: sqlite3.Connection) -> int:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone()
    if not exists:
        return 0
    return conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()[0]


def migrate(db_path: Path, migrations: tuple[tuple[int, str, str | tuple[str, ...]], ...] = MIGRATIONS) -> int:
    """Create or upgrade the database; returns the resulting schema version."""
    versions = [m[0] for m in migrations]
    if versions != list(range(1, len(versions) + 1)):
        raise MigrationError("Migrations must be numbered 1, 2, 3, … without gaps.")

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, description TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        conn.commit()
        version = current_version(conn)
        if version > len(migrations):
            raise MigrationError(
                f"{db_path.name} has schema version {version}, newer than this app supports "
                f"({len(migrations)}). Upgrade the app instead of using an older version."
            )
        for number, description, sql in migrations[version:]:
            _apply(conn, number, description, sql)
        return current_version(conn)
    finally:
        conn.close()


def _apply(conn: sqlite3.Connection, number: int, description: str, sql: str | tuple[str, ...]) -> None:
    """Apply one migration atomically: all of it, or none of it. ``sql`` is a script split on
    ';', or a tuple of single statements (needed when a statement contains ';')."""
    statements = list(sql) if isinstance(sql, tuple) else [s.strip() for s in sql.split(";") if s.strip()]
    try:
        conn.execute("BEGIN")
        for statement in statements:
            conn.execute(statement)
        conn.execute("INSERT INTO schema_migrations VALUES (?, ?, ?)", (number, description, utc_now()))
        conn.execute("COMMIT")
    except sqlite3.Error as exc:
        conn.execute("ROLLBACK")
        raise MigrationError(f"Migration {number} ({description}) failed: {exc}") from exc
