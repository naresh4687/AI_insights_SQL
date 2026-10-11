"""Query scope: the tables one request may read, enforced by both guard layers."""

import sqlite3

import pytest

from src import query_service, sql_guard
from src.query_service import QueryError, run_query
from src.sql_guard import ALLOWED_TABLES, ReadOnlyAuthorizer, UnsafeSQLError, table_scope, validate_sql


@pytest.fixture
def scoped_db(tmp_path):
    """Demo tables plus an extra table that only an explicit scope may read."""
    path = tmp_path / "scope.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE products (product_id INTEGER, product_name TEXT);
        CREATE TABLE sales (sale_id INTEGER, quantity INTEGER);
        CREATE TABLE imported_orders (order_id INTEGER, amount REAL);
        CREATE TABLE query_history (question TEXT);
        INSERT INTO products VALUES (1, 'Pen');
        INSERT INTO sales VALUES (1, 3);
        INSERT INTO imported_orders VALUES (10, 99.5), (11, 0.5);
        INSERT INTO query_history VALUES ('secret question');
    """)
    conn.close()
    return path


# --- Defaults are unchanged -------------------------------------------------------

def test_default_scope_is_the_demo_tables():
    assert validate_sql("SELECT * FROM products") == validate_sql("SELECT * FROM products", ALLOWED_TABLES)
    with pytest.raises(UnsafeSQLError, match="Allowed tables: products, sales"):
        validate_sql("SELECT * FROM imported_orders")


def test_run_query_default_scope_rejects_other_tables(scoped_db):
    with pytest.raises(QueryError) as exc:
        run_query(scoped_db, "SELECT * FROM imported_orders")
    assert exc.value.status == "rejected"


# --- An explicit scope widens to exactly its tables and nothing else ---------------

def test_explicit_scope_allows_its_table(scoped_db):
    result = run_query(scoped_db, "SELECT SUM(amount) AS total FROM imported_orders",
                       allowed_tables={"imported_orders"})
    assert result.data.iloc[0, 0] == pytest.approx(100.0)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM products",
    "SELECT * FROM sales",
    "SELECT * FROM query_history",
    "SELECT o.amount FROM imported_orders o JOIN products p ON p.product_id = o.order_id",
    "SELECT * FROM imported_orders UNION SELECT question, 1 FROM query_history",
    "WITH x AS (SELECT * FROM sales) SELECT * FROM x",
    "SELECT * FROM imported_orders WHERE order_id IN (SELECT sale_id FROM sales)",
])
def test_explicit_scope_excludes_demo_and_internal_tables(scoped_db, sql):
    with pytest.raises(QueryError) as exc:
        run_query(scoped_db, sql, allowed_tables={"imported_orders"})
    assert exc.value.status == "rejected"


def test_cte_name_cannot_shadow_a_table_outside_the_scope(scoped_db):
    # The CTE is named like an out-of-scope table; the query only reads the CTE.
    result = run_query(scoped_db, "WITH sales AS (SELECT amount FROM imported_orders) SELECT * FROM sales",
                       allowed_tables={"imported_orders"})
    assert sorted(result.data["amount"]) == [0.5, 99.5]


def test_scope_is_case_insensitive(scoped_db):
    result = run_query(scoped_db, "SELECT COUNT(*) FROM IMPORTED_ORDERS", allowed_tables={"Imported_Orders"})
    assert result.data.iloc[0, 0] == 2


@pytest.mark.parametrize("scope", [set(), [""], ["  "], [None]])
def test_empty_scope_is_refused_never_widened(scope):
    with pytest.raises(ValueError):
        table_scope(scope)
    with pytest.raises(ValueError):
        validate_sql("SELECT 1", scope)
    with pytest.raises(ValueError):
        ReadOnlyAuthorizer(scope)


# --- The engine layer enforces the scope on its own -------------------------------

def test_authorizer_enforces_scope_when_parser_is_disabled(scoped_db, monkeypatch):
    monkeypatch.setattr(query_service, "validate_sql", lambda sql, *scope: sql)
    with pytest.raises(QueryError) as exc:
        run_query(scoped_db, "SELECT * FROM products", allowed_tables={"imported_orders"})
    assert exc.value.status == "rejected"
    assert "products" in exc.value.message


def test_authorizer_scope_directly():
    auth = ReadOnlyAuthorizer({"imported_orders"})
    assert auth(sqlite3.SQLITE_READ, "imported_orders", "amount", "main", None) == sqlite3.SQLITE_OK
    assert auth(sqlite3.SQLITE_READ, "sales", "quantity", "main", None) == sqlite3.SQLITE_DENY
    assert ReadOnlyAuthorizer()(sqlite3.SQLITE_READ, "sales", "quantity", "main", None) == sqlite3.SQLITE_OK


def test_scope_does_not_mutate_the_default():
    validate_sql("SELECT * FROM imported_orders", {"imported_orders"})
    assert sql_guard.ALLOWED_TABLES == frozenset({"products", "sales"})
