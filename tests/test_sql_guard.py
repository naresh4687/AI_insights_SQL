"""Unit tests for the SQL safety layer (parser layer and engine-level authorizer)."""

import sqlite3

import pytest

from src import database
from src.sql_guard import MAX_SQL_LENGTH, ReadOnlyAuthorizer, UnsafeSQLError, validate_sql

SAFE_QUERIES = [
    "SELECT * FROM products",
    "select product_name from products where category = 'Furniture';",
    "SELECT region, SUM(quantity * unit_price) AS revenue FROM sales GROUP BY region",
    "SELECT p.product_name, SUM(s.quantity * s.unit_price) AS revenue "
    "FROM sales s JOIN products p ON p.product_id = s.product_id "
    "GROUP BY p.product_name ORDER BY revenue DESC LIMIT 5",
    "SELECT strftime('%Y-%m', sale_date) AS month, SUM(quantity) FROM sales GROUP BY month",
    "WITH totals AS (SELECT region, SUM(quantity) AS units FROM sales GROUP BY region) "
    "SELECT * FROM totals ORDER BY units DESC",
    "SELECT category FROM products UNION SELECT region FROM sales",
    "SELECT * FROM (SELECT product_id, quantity FROM sales) AS sub WHERE quantity > 3",
    "SELECT product_name, RANK() OVER (ORDER BY unit_price DESC) FROM products",
    "SELECT 'DROP TABLE sales' AS harmless_string",
]


@pytest.mark.parametrize("sql", SAFE_QUERIES)
def test_safe_queries_are_accepted(sql):
    assert validate_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        # Writes and schema changes
        "INSERT INTO products VALUES (99, 'x', 'y', 1.0)",
        "UPDATE sales SET quantity = 0",
        "DELETE FROM sales",
        "DROP TABLE sales",
        "ALTER TABLE sales ADD COLUMN hacked TEXT",
        "CREATE TABLE evil (id INTEGER)",
        "REPLACE INTO products VALUES (1, 'x', 'y', 1.0)",
        "CREATE TABLE copy AS SELECT * FROM sales",
        # Multiple statements / injection-style
        "SELECT 1; DROP TABLE sales",
        "SELECT * FROM products; DELETE FROM sales;",
        "SELECT * FROM products WHERE 1=1; --",
        # Database-level commands
        "PRAGMA table_info(sales)",
        "PRAGMA writable_schema = ON",
        "ATTACH DATABASE '/tmp/evil.db' AS evil",
        "DETACH DATABASE main",
        "VACUUM",
        "BEGIN TRANSACTION",
        # Restricted tables and SQLite internals
        "SELECT * FROM query_history",
        "SELECT * FROM sqlite_master",
        "SELECT * FROM main.sales",
        "SELECT * FROM pragma_table_info('sales')",
        "SELECT * FROM sales JOIN sqlite_schema ON 1=1",
        "SELECT * FROM products WHERE product_id IN (SELECT history_id FROM query_history)",
        "WITH x AS (SELECT * FROM sqlite_master) SELECT * FROM x",
        # Recursive CTEs (unbounded row generation)
        "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT x FROM c",
    ],
)
def test_dangerous_queries_are_rejected(sql):
    with pytest.raises(UnsafeSQLError):
        validate_sql(sql)


@pytest.mark.parametrize(
    "sql",
    ["", "   ", "\n\t", None, 42, "SELEC * FROM products", "hello world", "SELECT FROM WHERE", ";"],
)
def test_empty_and_malformed_input_is_rejected(sql):
    with pytest.raises(UnsafeSQLError):
        validate_sql(sql)


def test_overlong_query_is_rejected():
    sql = "SELECT 1" + " " * MAX_SQL_LENGTH
    with pytest.raises(UnsafeSQLError, match="too long"):
        validate_sql(sql)


def test_rejection_message_names_restricted_table():
    with pytest.raises(UnsafeSQLError, match="query_history"):
        validate_sql("SELECT * FROM query_history")


def test_comments_are_stripped_from_validated_sql():
    safe = validate_sql("SELECT * FROM products -- ; DROP TABLE sales")
    assert "DROP" not in safe.upper()
    assert "--" not in safe and "/*" not in safe


def test_trailing_semicolon_is_allowed():
    assert validate_sql("SELECT 1;") == "SELECT 1"


# --- Engine-level authorizer (bypasses validate_sql on purpose) --------------

def _run_with_authorizer(db_path, sql, authorizer):
    conn = database.connect_readonly(db_path)
    conn.set_authorizer(authorizer)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_authorizer_allows_reads_of_permitted_tables(seeded_db):
    authorizer = ReadOnlyAuthorizer()
    rows = _run_with_authorizer(
        seeded_db, "SELECT COUNT(*), ROUND(SUM(quantity * unit_price), 2) FROM sales", authorizer
    )
    assert rows[0][0] == 600
    assert authorizer.denied_reason is None


@pytest.mark.parametrize(
    "sql, reason",
    [
        ("SELECT * FROM query_history", "query_history"),
        ("SELECT name FROM sqlite_master", "sqlite_master"),
        ("SELECT * FROM pragma_table_info('sales')", "not allowed"),
        ("SELECT load_extension('evil')", "load_extension"),
        ("SELECT zeroblob(1000000000)", "zeroblob"),
        ("DELETE FROM sales", "not allowed"),
        ("ATTACH DATABASE ':memory:' AS other", "not allowed"),
    ],
)
def test_authorizer_denies_unsafe_operations_at_engine_level(seeded_db, sql, reason):
    authorizer = ReadOnlyAuthorizer()
    with pytest.raises(sqlite3.DatabaseError):
        _run_with_authorizer(seeded_db, sql, authorizer)
    assert reason in authorizer.denied_reason
