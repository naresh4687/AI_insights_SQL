"""Unit tests for chart selection and result explanations."""

import re

import pandas as pd
import pytest

from src import demo_queries
from src.insights import ChartSpec, choose_chart, explain, format_value, humanize
from src.query_service import answer_question

TOP5, BY_REGION, BY_CATEGORY, MONTHLY, BOTTOM5 = demo_queries.demo_questions()


# --- Chart selection on the real demo results --------------------------------

@pytest.mark.parametrize(
    "question, expected",
    [
        (TOP5, ChartSpec("bar", "product_name", "revenue")),
        (BY_REGION, ChartSpec("bar", "region", "revenue")),
        (BY_CATEGORY, ChartSpec("bar", "category", "units_sold")),
        (MONTHLY, ChartSpec("line", "month", "revenue")),
        (BOTTOM5, ChartSpec("bar", "product_name", "revenue")),
    ],
)
def test_demo_results_get_the_expected_chart(seeded_db, question, expected):
    assert choose_chart(answer_question(seeded_db, question).data) == expected


# --- No chart when a chart would not be meaningful ------------------------------

@pytest.mark.parametrize(
    "data",
    [
        pd.DataFrame({"region": [], "revenue": []}),                              # empty
        pd.DataFrame({"region": ["North"], "revenue": [1.0]}),                    # single row
        pd.DataFrame({"n": [600]}),                                               # single value
        pd.DataFrame({"name": [f"p{i}" for i in range(51)], "v": range(51)}),     # too many bars
        pd.DataFrame({"a": ["x", "y"], "b": [1, 2], "c": [3, 4]}),                # two measures
        pd.DataFrame({"id": [1, 2], "v": [3, 4]}),                                # numeric label
        pd.DataFrame({"name": ["x", "y"], "label": ["a", "b"]}),                  # no numeric value
        pd.DataFrame({"name": ["x", "x"], "v": [1, 2]}),                          # duplicate labels
        pd.DataFrame({"name": ["x", None], "v": [1, 2]}),                         # missing label
        pd.DataFrame({"name": ["x", "y"], "flag": [True, False]}),                # boolean value
    ],
)
def test_unsuitable_results_get_no_chart(data):
    assert choose_chart(data) is None


def test_date_labels_get_a_line_chart():
    data = pd.DataFrame({"day": ["2025-01-01", "2025-01-02"], "units": [3, 4]})
    assert choose_chart(data) == ChartSpec("line", "day", "units")


def test_fifty_rows_is_still_charted():
    data = pd.DataFrame({"name": [f"p{i}" for i in range(50)], "v": range(50)})
    assert choose_chart(data) is not None


# --- Explanations -------------------------------------------------------------

def test_top_products_explanation(seeded_db):
    text = explain(answer_question(seeded_db, TOP5).data)
    assert text == (
        "Across the 5 rows returned, Laptop Pro 14 has the highest revenue (102,900.00) "
        "and Noise-Cancelling Headphones the lowest (23,796.00)."
    )


def test_monthly_explanation_names_period_range(seeded_db):
    text = explain(answer_question(seeded_db, MONTHLY).data)
    assert text.startswith("The results cover 12 periods from 2025-01 to 2025-12.")


@pytest.mark.parametrize("question", demo_queries.demo_questions())
def test_explanation_figures_all_come_from_the_data(seeded_db, question):
    """Every number in the explanation must be a value from the result."""
    data = answer_question(seeded_db, question).data
    allowed = {format_value(v) for v in data.iloc[:, 1]}
    text = explain(data)
    for label in data.iloc[:, 0]:  # labels may contain digits, e.g. "Protein Bars (12)"
        text = text.replace(str(label), "<label>")
    figures = re.findall(r"\d[\d,]*\.\d{2}|(?<=\()\d[\d,]*(?=\))", text)
    assert figures, "expected at least one figure"
    assert set(figures) <= allowed


@pytest.mark.parametrize("question", demo_queries.demo_questions())
def test_explanation_makes_no_trend_or_causal_claims(seeded_db, question):
    text = explain(answer_question(seeded_db, question).data).lower()
    for word in ("because", "due to", "trend", "growth", "increase", "decline", "caused"):
        assert word not in text


def test_explain_empty_result():
    assert "no rows" in explain(pd.DataFrame({"a": []}))


def test_explain_single_value():
    assert explain(pd.DataFrame({"total_units": [7332]})) == "The result is total units: 7,332."


def test_explain_single_labelled_row():
    assert explain(pd.DataFrame({"region": ["East"], "revenue": [78731.9]})) == \
        "East has a revenue of 78,731.90."


def test_explain_ties_are_reported():
    data = pd.DataFrame({"name": ["a", "b", "c"], "units": [5, 5, 1]})
    assert "(tied with others)" in explain(data)


def test_explain_all_equal_values():
    data = pd.DataFrame({"name": ["a", "b"], "units": [5, 5]})
    assert explain(data) == "All 2 rows returned have the same units (5)."


def test_explain_generic_shape():
    data = pd.DataFrame({"a": ["x", "y"], "b": [1, 2], "c": [3, 4]})
    assert explain(data) == "The query returned 2 rows and 3 columns."


def test_explain_mentions_truncation():
    data = pd.DataFrame({"a": ["x", "y"], "b": [1, 2], "c": [3, 4]})
    assert "Only the first 2 rows are shown" in explain(data, truncated=True)


def test_formatting_helpers():
    assert humanize("units_sold") == "units sold"
    assert format_value(1234567) == "1,234,567"
    assert format_value(1234.5) == "1,234.50"
    assert format_value("East") == "East"
