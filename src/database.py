"""SQLite schema, connections, seeding, and query-history storage.

Two kinds of connection are provided:
- ``connect()``: read-write, used for setup, seeding, and writing query history.
- ``connect_readonly()``: opened with ``mode=ro`` so user-facing queries cannot modify
  data even if validation were bypassed. Phase 3 layers further safeguards on top.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src import sample_data
from src.core.models import DEMO_DATASET_ID

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS products (
    product_id   INTEGER PRIMARY KEY,
    product_name TEXT NOT NULL,
    category     TEXT NOT NULL,
    unit_price   REAL NOT NULL CHECK (unit_price >= 0)
);

CREATE TABLE IF NOT EXISTS sales (
    sale_id    INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    quantity   INTEGER NOT NULL CHECK (quantity > 0),
    sale_date  TEXT NOT NULL,
    region     TEXT NOT NULL,
    unit_price REAL NOT NULL CHECK (unit_price >= 0)
);

CREATE INDEX IF NOT EXISTS idx_sales_product ON sales(product_id);
CREATE INDEX IF NOT EXISTS idx_sales_date ON sales(sale_date);

CREATE TABLE IF NOT EXISTS query_history (
    history_id    INTEGER PRIMARY KEY,
    question      TEXT NOT NULL,
    generated_sql TEXT,
    status        TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

-- Which dataset a history entry was about. Added alongside query_history (which is not
-- altered); entries without a row here were asked about the demo data.
CREATE TABLE IF NOT EXISTS history_datasets (
    history_id INTEGER PRIMARY KEY REFERENCES query_history(history_id),
    dataset_id TEXT NOT NULL
);

-- Who asked (an accounts user_id), when sign-in is on. Entries without a row here were made
-- without sign-in and are shown only when sign-in is off.
CREATE TABLE IF NOT EXISTS history_users (
    history_id INTEGER PRIMARY KEY REFERENCES query_history(history_id),
    user_id    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_users_user ON history_users(user_id, history_id);
"""

HISTORY_STATUSES = ("success", "rejected", "error")


def connect(db_path: Path) -> sqlite3.Connection:
    """Open a read-write connection with foreign-key enforcement enabled."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    """Open a read-only connection. Fails if the database file does not exist."""
    uri = f"{Path(db_path).resolve().as_uri()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def init_db(db_path: Path) -> None:
    """Create the schema if it does not already exist."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
    conn.close()


def seed_sample_data(db_path: Path) -> None:
    """Rebuild the database from scratch and load the deterministic sample data."""
    db_path = Path(db_path)
    if db_path.exists():
        db_path.unlink()
    init_db(db_path)
    with connect(db_path) as conn:
        conn.executemany("INSERT INTO products VALUES (?, ?, ?, ?)", sample_data.PRODUCTS)
        conn.executemany("INSERT INTO sales VALUES (?, ?, ?, ?, ?, ?)", sample_data.generate_sales())
    conn.close()


def ensure_database(db_path: Path) -> None:
    """Create and seed the database if it is missing (e.g. on first deploy). An existing
    database only gets tables it lacks (CREATE TABLE IF NOT EXISTS); no data is changed."""
    if not Path(db_path).exists():
        seed_sample_data(db_path)
    else:
        init_db(db_path)


def add_history(db_path: Path, question: str, generated_sql: str | None, status: str,
                dataset_id: str | None = None, user_id: str | None = None) -> None:
    """Record a question, the SQL used (if any), its outcome, the dataset it was about
    (``None`` or the demo dataset: the demo data) and who asked (``None``: sign-in is off)."""
    if status not in HISTORY_STATUSES:
        raise ValueError(f"Unknown history status: {status!r}")
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect(db_path) as conn:  # one transaction: the entry and its dataset together
        cursor = conn.execute(
            "INSERT INTO query_history (question, generated_sql, status, created_at) VALUES (?, ?, ?, ?)",
            (question, generated_sql, status, created_at),
        )
        if dataset_id and dataset_id != DEMO_DATASET_ID:
            conn.execute("INSERT INTO history_datasets (history_id, dataset_id) VALUES (?, ?)",
                         (cursor.lastrowid, dataset_id))
        if user_id:
            conn.execute("INSERT INTO history_users (history_id, user_id) VALUES (?, ?)", (cursor.lastrowid, user_id))
    conn.close()


def recent_history(db_path: Path, limit: int = 10, user_id: str | None = None) -> list[dict]:
    """Return the most recent history entries, newest first; only ``user_id``'s if given."""
    conn = connect(db_path)
    conn.row_factory = sqlite3.Row
    mine = "JOIN history_users u ON u.history_id = h.history_id AND u.user_id = ? " if user_id else ""
    try:
        rows = conn.execute(
            "SELECT h.history_id, h.question, h.generated_sql, h.status, h.created_at, "
            "COALESCE(d.dataset_id, ?) AS dataset_id "
            f"FROM query_history h {mine}LEFT JOIN history_datasets d ON d.history_id = h.history_id "
            "ORDER BY h.history_id DESC LIMIT ?",
            (DEMO_DATASET_ID, *([user_id] if user_id else []), limit),
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def history_count(db_path: Path) -> int:
    """Number of query-history entries."""
    conn = connect_readonly(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM query_history").fetchone()[0]
    finally:
        conn.close()
