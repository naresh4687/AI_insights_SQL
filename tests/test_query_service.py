"""Integration tests for safe query execution."""

import pandas as pd
import pytest

from src import database
from src.query_service import QueryError, QueryResult, run_query

TOP_PRODUCTS_SQL = (
    "SELECT p.product_name, ROUND(SUM(s.quantity * s.unit_price), 2) AS revenue "
    "FROM sales s JOIN products p ON p.product_id = s.product_id "
    "GROUP BY p.product_id ORDER BY revenue DESC LIMIT 3"
)


def test_run_query_returns_dataframe_with_expected_values(seeded_db):
    result = run_query(seeded_db, TOP_PRODUCTS_SQL)

    assert isinstance(result, QueryResult)
    assert isinstance(result.data, pd.DataFrame)
    assert list(result.data.columns) == ["product_name", "revenue"]
    assert result.data.values.tolist() == [
        ["Laptop Pro 14", 102900.0],
        ["Standing Desk", 42277.5],
        ["Office Chair", 34518.0],
    ]
    assert result.truncated is False


def test_run_query_returns_the_validated_sql(seeded_db):
    result = run_query(seeded_db, "SELECT COUNT(*) AS n FROM products -- comment")
    assert result.sql == "SELECT COUNT(*) AS n FROM products"
    assert result.data["n"].iloc[0] == 12


def test_empty_result_is_an_empty_dataframe_not_an_error(seeded_db):
    result = run_query(seeded_db, "SELECT * FROM sales WHERE region = 'Atlantis'")
    assert result.data.empty
    assert list(result.data.columns) == ["sale_id", "product_id", "quantity", "sale_date", "region", "unit_price"]


def test_results_are_capped_and_flagged_as_truncated(seeded_db):
    result = run_query(seeded_db, "SELECT * FROM sales", max_rows=50)
    assert len(result.data) == 50
    assert result.truncated is True


def test_result_exactly_at_cap_is_not_truncated(seeded_db):
    result = run_query(seeded_db, "SELECT * FROM products", max_rows=12)
    assert len(result.data) == 12
    assert result.truncated is False


def test_long_running_query_is_stopped(seeded_db):
    cross_join = "SELECT COUNT(*) FROM sales a, sales b, sales c"  # 216 million rows
    with pytest.raises(QueryError, match="took too long") as exc_info:
        run_query(seeded_db, cross_join, timeout_seconds=0.2)
    assert exc_info.value.status == "error"


@pytest.mark.parametrize("sql", ["DELETE FROM sales", "SELECT 1; DROP TABLE sales", "SELECT * FROM query_history"])
def test_unsafe_sql_is_rejected_and_data_untouched(seeded_db, sql):
    with pytest.raises(QueryError) as exc_info:
        run_query(seeded_db, sql)
    assert exc_info.value.status == "rejected"

    assert run_query(seeded_db, "SELECT COUNT(*) AS n FROM sales").data["n"].iloc[0] == 600


def test_disallowed_function_is_rejected_by_engine_layer(seeded_db):
    # Passes the parser layer (it is a plain SELECT) but the authorizer denies it.
    with pytest.raises(QueryError, match="zeroblob") as exc_info:
        run_query(seeded_db, "SELECT zeroblob(10) FROM products")
    assert exc_info.value.status == "rejected"


def test_unknown_column_gives_helpful_message(seeded_db):
    with pytest.raises(QueryError, match="no such column: revenue") as exc_info:
        run_query(seeded_db, "SELECT revenue FROM sales")
    assert exc_info.value.status == "error"


def test_missing_database_gives_safe_message(tmp_path):
    missing = tmp_path / "missing.db"
    with pytest.raises(QueryError, match="database is not available") as exc_info:
        run_query(missing, "SELECT 1")
    assert str(missing) not in exc_info.value.message  # no internal paths leaked


def test_query_connection_cannot_write_history(seeded_db):
    # Even a valid read leaves query_history untouched: the service never writes.
    run_query(seeded_db, "SELECT * FROM products")
    assert database.recent_history(seeded_db) == []
