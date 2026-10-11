"""SQL explanations, error hints (src/sql_explain.py), CSV export (src/export.py) and the
chart builders (src/ui/charts.py)."""

import io
from datetime import datetime

import pandas as pd
import pytest

from src import demo_queries, export
from src.analysis import Chart, chart_options
from src.catalog import demo_dataset
from src.core.models import ColumnInfo, Dataset, SourceType, Storage, TableInfo
from src.sql_explain import explain_error, explain_sql
from src.ui import charts

TOP5_SQL = demo_queries.DEMO_QUERIES[demo_queries.demo_questions()[0]]


# --- SQL explanations ---------------------------------------------------------------------

def test_demo_query_is_explained_step_by_step():
    assert explain_sql(TOP5_SQL) == [
        "Reads from sales (as s).",
        "Joins products (as p) where p.product_id = s.product_id.",
        "Groups the rows by p.product_id, p.product_name.",
        "Shows product_name.",
        "Calculates revenue as ROUND(SUM(s.quantity * s.unit_price), 2).",
        "Sorts by revenue (descending).",
        "Returns at most 5 rows.",
    ]


@pytest.mark.parametrize("sql, expected", [
    ("SELECT * FROM sales WHERE region = 'East'", ["Reads from sales.", "Keeps only rows where region = 'East'.",
                                                   "Shows all columns."]),
    ("SELECT DISTINCT region FROM sales", ["Reads from sales.", "Shows region.", "Removes duplicate rows."]),
    ("SELECT region, COUNT(*) AS n FROM sales GROUP BY region HAVING COUNT(*) > 100",
     ["Reads from sales.", "Groups the rows by region.", "Shows region.", "Calculates n as COUNT(*).",
      "Keeps only groups where COUNT(*) > 100."]),
    ("WITH t AS (SELECT region FROM sales) SELECT * FROM t",
     ["First builds an intermediate result named t from sales.", "Reads from t.", "Shows all columns."]),
    ("SELECT category FROM products UNION ALL SELECT region FROM sales",
     ["Combines 2 queries with UNION (keeping duplicates).", "Part: reads from products.", "Part: reads from sales."]),
])
def test_query_shapes(sql, expected):
    assert explain_sql(sql) == expected


@pytest.mark.parametrize("sql", ["", "not sql (((", "SELECT 1; SELECT 2", "DROP TABLE sales"])
def test_unexplainable_sql_gets_a_safe_message(sql):
    assert explain_sql(sql) == ["This query could not be broken down automatically."]


# --- Error hints --------------------------------------------------------------------------

ORDERS = Dataset("orders", "Orders", SourceType.CSV, Storage.DATASETS,
                 (TableInfo("orders", (ColumnInfo("order_id", "INTEGER"), ColumnInfo("amount", "REAL"))),))


@pytest.mark.parametrize("message, dataset, expected", [
    ("Table 'staff' is not available. Allowed tables: orders.", ORDERS, "can only use orders"),
    ("Reading from 'staff' is not allowed.", ORDERS, "can only use orders"),
    ("The query could not be run: no such column: amout.", ORDERS,
     "There is no column named amout. Available columns: order_id, amount."),
    ("The query could not be run: no such column: x.", demo_dataset(), "products.product_id"),
    ("The query took too long and was stopped. Try a simpler question.", ORDERS, "narrower question"),
    ("The query could not be parsed as valid SQL.", None, "typos"),
    ("Exactly one SQL statement is allowed.", None, "one statement at a time"),
    ("Only read-only SELECT queries are allowed.", None, "only reads data"),
    ("The function 'load_extension' is not allowed.", None, "load_extension is not supported"),
    ("Recursive queries are not allowed.", None, "WITH RECURSIVE"),
])
def test_error_hints(message, dataset, expected):
    assert expected in explain_error(message, dataset)


@pytest.mark.parametrize("message", ["Please enter a question.", "Gemini rejected the API key.",
                                     "Demo Mode only answers the example questions about the demo sales data."])
def test_messages_that_need_no_hint(message):
    assert explain_error(message, ORDERS) is None


# --- CSV export ---------------------------------------------------------------------------

def read_back(content: bytes) -> pd.DataFrame:
    assert content.startswith(b"\xef\xbb\xbf")  # BOM: Excel shows accents correctly
    return pd.read_csv(io.BytesIO(content), encoding="utf-8-sig", dtype=str, keep_default_na=False)


@pytest.mark.parametrize("value", ["=HYPERLINK(\"http://evil\")", "+1+1", "-2+3", "@SUM(A1)", "\tcmd", "\r=1"])
def test_formula_like_text_is_neutralised(value):
    out = read_back(export.to_csv(pd.DataFrame({"name": [value]})))
    assert out["name"][0] == "'" + value  # exactly the value, with an apostrophe in front


def test_numbers_and_ordinary_text_are_unchanged():
    data = pd.DataFrame({"name": ["Café", "a=b", "Ravi"], "amount": [-5.5, 0.0, 12.25], "n": [-1, 2, 3]})
    out = read_back(export.to_csv(data))
    assert out["name"].tolist() == ["Café", "a=b", "Ravi"]
    assert out["amount"].tolist() == ["-5.5", "0.0", "12.25"] and out["n"].tolist() == ["-1", "2", "3"]


def test_formula_like_column_names_are_neutralised():
    out = read_back(export.to_csv(pd.DataFrame({"=cmd": ["x"]})))
    assert list(out.columns) == ["'=cmd"]


def test_missing_values_export_as_empty():
    out = read_back(export.to_csv(pd.DataFrame({"a": ["x", None], "b": [1.0, None]})))
    assert out.values.tolist() == [["x", "1.0"], ["", ""]]


@pytest.mark.parametrize("name, expected", [
    ("Demo sales", "insightsql_demo-sales_20261011-093000.csv"),
    ("../../etc/passwd", "insightsql_etc-passwd_20261011-093000.csv"),
    ("தமிழ்", "insightsql_result_20261011-093000.csv"),
])
def test_file_names_are_safe(name, expected):
    assert export.file_name(name, datetime(2026, 10, 11, 9, 30)) == expected


# --- Chart builders -----------------------------------------------------------------------

def _mark(chart) -> str:
    spec = chart.to_dict()
    mark = spec.get("mark")
    return mark["type"] if isinstance(mark, dict) else mark


CATEGORIES = pd.DataFrame({"region": ["N", "S", "E", "W"], "revenue": [4.0, 3.0, 2.0, 1.0]})
MONTHS = pd.DataFrame({"month": [f"2025-{m:02d}" for m in range(1, 7)], "revenue": [1.0, 2, 3, 4, 5, 6]})
PAIRS = pd.DataFrame({"price": [1.0, 2, 3, 4, 5], "units": [10, 8, 6, 4, 2]})
GROUPS = pd.DataFrame({"region": list("NNSSEE"), "amount": [1, 2, 3, 4, 5, 6]})


@pytest.mark.parametrize("data, kind, mark", [
    (CATEGORIES, "bar", "bar"), (CATEGORIES, "column", "bar"), (CATEGORIES, "pie", "arc"),
    (CATEGORIES, "donut", "arc"), (MONTHS, "line", "line"), (MONTHS, "area", "area"), (MONTHS, "histogram", "bar"),
    (MONTHS, "box", "boxplot"), (PAIRS, "scatter", "circle"), (GROUPS, "box", "boxplot"),
])
def test_every_offered_chart_builds_with_the_right_mark(data, kind, mark):
    spec = next(c for c in chart_options(data) if c.kind == kind)
    chart = charts.build(spec, data)
    assert _mark(chart) == mark
    chart.to_json()  # a valid Vega-Lite spec


def test_donut_has_a_hole_and_pie_does_not():
    pie = charts.build(Chart("pie", "region", "revenue"), CATEGORIES).to_dict()["mark"]
    donut = charts.build(Chart("donut", "region", "revenue"), CATEGORIES).to_dict()["mark"]
    assert pie["innerRadius"] == 0 and donut["innerRadius"] > 0


def test_kpi_has_no_altair_chart_and_unknown_kinds_fail():
    assert charts.build(Chart("kpi"), pd.DataFrame({"n": [1]})) is None
    with pytest.raises(ValueError):
        charts.build(Chart("radar", "a", "b"), CATEGORIES)


def test_column_chart_keeps_period_order():
    spec = charts.build(Chart("column", "month", "revenue"), MONTHS).to_dict()
    assert spec["encoding"]["x"].get("sort") is None
    assert charts.build(Chart("column", "region", "revenue"), CATEGORIES).to_dict()["encoding"]["x"]["sort"] == "-y"
