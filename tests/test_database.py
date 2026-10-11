"""Integration tests for schema creation, seeding, revenue values, and query history."""

import sqlite3
from collections import defaultdict
from datetime import datetime

import pytest

from src import database, sample_data


def _revenue_by(key_index: int) -> dict:
    """Independent Python oracle: revenue grouped by a column of the generated sales rows."""
    totals = defaultdict(float)
    for row in sample_data.generate_sales():
        totals[row[key_index]] += row[2] * row[5]  # quantity * sale-level unit_price
    return {k: round(v, 2) for k, v in totals.items()}


# --- Schema -----------------------------------------------------------------

def test_init_db_creates_expected_tables_and_columns(tmp_path):
    db_path = tmp_path / "schema.db"
    database.init_db(db_path)
    conn = database.connect(db_path)
    columns = lambda table: [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]

    assert columns("products") == ["product_id", "product_name", "category", "unit_price"]
    assert columns("sales") == ["sale_id", "product_id", "quantity", "sale_date", "region", "unit_price"]
    assert columns("query_history") == ["history_id", "question", "generated_sql", "status", "created_at"]
    conn.close()


def test_init_db_is_idempotent(tmp_path):
    db_path = tmp_path / "schema.db"
    database.init_db(db_path)
    database.init_db(db_path)  # must not raise on existing tables


def test_sales_foreign_key_is_enforced(seeded_db):
    conn = database.connect(seeded_db)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO sales VALUES (9999, 999, 1, '2025-01-01', 'North', 1.0)")
    conn.close()


def test_sales_quantity_must_be_positive(seeded_db):
    conn = database.connect(seeded_db)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO sales VALUES (9999, 1, 0, '2025-01-01', 'North', 1.0)")
    conn.close()


# --- Seeding ----------------------------------------------------------------

def test_seed_loads_expected_row_counts(seeded_db):
    conn = database.connect(seeded_db)
    assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 12
    assert conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 600
    assert conn.execute("SELECT COUNT(*) FROM query_history").fetchone()[0] == 0
    conn.close()


def test_generated_sales_are_deterministic():
    assert sample_data.generate_sales() == sample_data.generate_sales()


def test_reseeding_resets_database(seeded_db):
    database.add_history(seeded_db, "q", None, "error")
    database.seed_sample_data(seeded_db)
    conn = database.connect(seeded_db)
    assert conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 600
    assert conn.execute("SELECT COUNT(*) FROM query_history").fetchone()[0] == 0
    conn.close()


def test_sample_data_covers_every_month_and_region(seeded_db):
    conn = database.connect(seeded_db)
    months = conn.execute("SELECT COUNT(DISTINCT substr(sale_date, 1, 7)) FROM sales").fetchone()[0]
    regions = {r[0] for r in conn.execute("SELECT DISTINCT region FROM sales")}
    conn.close()
    assert months == 12
    assert regions == set(sample_data.REGIONS)


def test_ensure_database_creates_missing_db(tmp_path):
    db_path = tmp_path / "nested" / "new.db"
    database.ensure_database(db_path)
    assert db_path.exists()


def test_ensure_database_does_not_overwrite_existing(seeded_db):
    database.add_history(seeded_db, "keep me", None, "success")
    database.ensure_database(seeded_db)
    assert database.recent_history(seeded_db)[0]["question"] == "keep me"


# --- Revenue values ---------------------------------------------------------

def test_revenue_by_region_matches_python_oracle(seeded_db):
    conn = database.connect(seeded_db)
    rows = conn.execute(
        "SELECT region, ROUND(SUM(quantity * unit_price), 2) FROM sales GROUP BY region"
    ).fetchall()
    conn.close()
    assert dict(rows) == _revenue_by(key_index=4)


def test_revenue_by_product_matches_python_oracle(seeded_db):
    conn = database.connect(seeded_db)
    rows = conn.execute(
        "SELECT product_id, ROUND(SUM(quantity * unit_price), 2) FROM sales GROUP BY product_id"
    ).fetchall()
    conn.close()
    assert dict(rows) == _revenue_by(key_index=1)


def test_top_products_golden_values(seeded_db):
    """Pins the seeded dataset; update deliberately if the seed data changes."""
    conn = database.connect(seeded_db)
    rows = conn.execute(
        "SELECT p.product_name, ROUND(SUM(s.quantity * s.unit_price), 2) AS revenue "
        "FROM sales s JOIN products p ON p.product_id = s.product_id "
        "GROUP BY p.product_id ORDER BY revenue DESC LIMIT 3"
    ).fetchall()
    conn.close()
    assert rows == [("Laptop Pro 14", 102900.0), ("Standing Desk", 42277.5), ("Office Chair", 34518.0)]


def test_revenue_uses_sale_level_price_not_catalogue_price(seeded_db):
    conn = database.connect(seeded_db)
    sale_level = conn.execute("SELECT SUM(quantity * unit_price) FROM sales").fetchone()[0]
    catalogue = conn.execute(
        "SELECT SUM(s.quantity * p.unit_price) FROM sales s JOIN products p ON p.product_id = s.product_id"
    ).fetchone()[0]
    conn.close()
    assert sale_level < catalogue  # discounts exist, so the two must differ


# --- Read-only connection ---------------------------------------------------

def test_readonly_connection_can_read(seeded_db):
    conn = database.connect_readonly(seeded_db)
    assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 12
    conn.close()


def test_readonly_connection_rejects_writes(seeded_db):
    conn = database.connect_readonly(seeded_db)
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        conn.execute("DELETE FROM sales")
    conn.close()


def test_readonly_connection_does_not_create_missing_db(tmp_path):
    with pytest.raises(sqlite3.OperationalError):
        database.connect_readonly(tmp_path / "missing.db")
    assert not (tmp_path / "missing.db").exists()


# --- Query history ----------------------------------------------------------

def test_history_empty_initially(seeded_db):
    assert database.recent_history(seeded_db) == []


def test_history_stores_entries_newest_first(seeded_db):
    database.add_history(seeded_db, "first", "SELECT 1", "success")
    database.add_history(seeded_db, "second", None, "rejected")

    history = database.recent_history(seeded_db)

    assert [h["question"] for h in history] == ["second", "first"]
    assert history[0]["generated_sql"] is None
    assert history[1]["generated_sql"] == "SELECT 1"
    assert history[0]["status"] == "rejected"
    datetime.fromisoformat(history[0]["created_at"])  # valid ISO timestamp


def test_history_respects_limit(seeded_db):
    for i in range(5):
        database.add_history(seeded_db, f"q{i}", None, "success")
    assert [h["question"] for h in database.recent_history(seeded_db, limit=2)] == ["q4", "q3"]


def test_history_rejects_unknown_status(seeded_db):
    with pytest.raises(ValueError):
        database.add_history(seeded_db, "q", None, "maybe")
