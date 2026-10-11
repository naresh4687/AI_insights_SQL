"""Chart options, statistics, facts and follow-ups (src/analysis.py), checked against
values computed independently in the tests."""

import re

import numpy as np
import pandas as pd
import pytest

from src import analysis, demo_queries
from src.analysis import Chart, chart_options, facts, follow_ups, period_changes, statistics
from src.insights import choose_chart
from src.query_service import answer_question

TOP5, BY_REGION, BY_CATEGORY, MONTHLY, BOTTOM5 = demo_queries.demo_questions()


def kinds(data):
    return [c.kind for c in chart_options(data)]


# --- Chart options --------------------------------------------------------------------

@pytest.mark.parametrize("question", demo_queries.demo_questions())
def test_default_chart_is_unchanged_for_every_demo_question(seeded_db, question):
    data = answer_question(seeded_db, question).data
    base = choose_chart(data)
    assert chart_options(data)[0] == Chart(base.kind, base.x, base.y)


def test_category_results_offer_bar_column_pie_donut():
    data = pd.DataFrame({"region": ["N", "S", "E", "W"], "revenue": [4.0, 3.0, 2.0, 1.0]})
    assert kinds(data) == ["bar", "column", "pie", "donut"]


def test_time_results_offer_line_area_column_then_distributions():
    data = pd.DataFrame({"month": [f"2025-{m:02d}" for m in range(1, 7)], "revenue": [1.0, 2, 3, 4, 5, 6]})
    assert kinds(data) == ["line", "area", "column", "histogram", "box"]


@pytest.mark.parametrize("data, reason", [
    (pd.DataFrame({"r": list("abcdefg"), "v": range(1, 8)}), "more than 6 slices"),
    (pd.DataFrame({"r": ["a", "b"], "v": [5, -1]}), "negative value"),
    (pd.DataFrame({"r": ["a", "b"], "v": [0, 0]}), "nothing to divide"),
])
def test_pie_only_for_a_few_non_negative_parts(data, reason):
    assert "pie" not in kinds(data) and "donut" not in kinds(data), reason


def test_single_row_offers_kpi_cards():
    assert chart_options(pd.DataFrame({"sale_count": [600]})) == [Chart("kpi")]
    assert kinds(pd.DataFrame({"a": [1], "b": [2.5], "name": ["x"]}))[0] == "kpi"
    assert "kpi" not in kinds(pd.DataFrame({f"c{i}": [i] for i in range(7)}))  # too many cards


def test_two_measures_offer_scatter():
    data = pd.DataFrame({"price": [1.0, 2, 3, 4, 5], "units": [10, 8, 6, 4, 2]})
    assert kinds(data) == ["scatter", "histogram", "box"]
    assert chart_options(data)[0] == Chart("scatter", "price", "units")


def test_repeated_categories_offer_box_by_category():
    data = pd.DataFrame({"region": list("NNSSEE"), "amount": [1, 2, 3, 4, 5, 6]})
    assert Chart("box", "region", "amount") in chart_options(data)
    assert Chart("box", "region", "amount").label == "Box plot by region"


@pytest.mark.parametrize("data", [
    pd.DataFrame(),
    pd.DataFrame({"name": ["x", "y"], "label": ["a", "b"]}),
    pd.DataFrame({"name": ["x", "y"], "v": [None, None]}, dtype=object),
])
def test_nothing_chartable_gives_no_options(data):
    assert chart_options(data) == []


def test_options_are_unique():
    data = pd.DataFrame({"v": [1, 2, 3, 4, 5, 6]})
    options = chart_options(data)
    assert len(options) == len(set(options))


# --- Statistics -------------------------------------------------------------------------

def test_statistics_match_pandas_and_ignore_text_and_booleans():
    data = pd.DataFrame({"name": list("abcde"), "flag": [True, False] * 2 + [True],
                         "v": [1.0, 2.0, np.nan, 4.0, 10.0]})
    [stats] = statistics(data)
    values = data["v"].dropna()
    assert (stats.column, stats.count, stats.missing) == ("v", 4, 1)
    assert stats.total == values.sum() and stats.mean == pytest.approx(values.mean())
    assert stats.median == values.median() and (stats.minimum, stats.maximum) == (1.0, 10.0)
    assert stats.std == pytest.approx(values.std())


def test_single_value_has_no_standard_deviation():
    assert statistics(pd.DataFrame({"v": [5]}))[0].std is None


# --- Period-over-period -----------------------------------------------------------------

def test_period_changes_follow_period_order_even_if_rows_are_not_sorted():
    data = pd.DataFrame({"month": ["2025-03", "2025-01", "2025-02"], "revenue": [150.0, 100.0, 0.0]})
    changes = period_changes(data)
    assert [(c.previous_period, c.period, c.change) for c in changes] == [
        ("2025-01", "2025-02", -100.0), ("2025-02", "2025-03", 150.0)]
    assert changes[0].percent == -100.0 and changes[1].percent is None  # from zero: no percentage


def test_period_facts_on_the_real_monthly_result(seeded_db):
    data = answer_question(seeded_db, MONTHLY).data
    found = facts(data)
    first, last = data.iloc[0], data.iloc[-1]
    assert found[0].startswith(f"From {first['month']} to {last['month']}, revenue went from")
    pct = (last["revenue"] - first["revenue"]) / first["revenue"] * 100
    assert f"{pct:+.1f}%" in found[0]
    diffs = data["revenue"].diff()
    rise_at = int(diffs.idxmax())
    assert f"Largest increase: {data['month'][rise_at - 1]} → {data['month'][rise_at]}" in " ".join(found)


def test_no_period_facts_for_other_results():
    assert period_changes(pd.DataFrame({"r": ["a", "b"], "v": [1, 2]})) == []


# --- Facts ------------------------------------------------------------------------------

def test_share_facts_on_the_real_region_result(seeded_db):
    data = answer_question(seeded_db, BY_REGION).data
    total = data["revenue"].sum()
    top = data.sort_values("revenue", ascending=False).iloc[0]
    found = facts(data)
    assert found[0] == (f"{top['region']} accounts for {top['revenue'] / total:.1%} of the total revenue in this "
                        f"result ({round(total, 2):,.2f}).")


def test_integer_columns_are_reported_as_whole_numbers(seeded_db):
    found = " ".join(facts(answer_question(seeded_db, BY_CATEGORY).data))
    assert "7,332)" in found and "7,332.00" not in found


@pytest.mark.parametrize("question", demo_queries.demo_questions())
def test_every_number_in_the_facts_comes_from_the_result(seeded_db, question):
    """Each figure is a value, a sum, an average, a median, a difference, a ratio or a share of
    the result — recomputed here and compared with every number the facts mention."""
    data = answer_question(seeded_db, question).data
    value = data.columns[1]
    v = data[value].astype(float)
    ordered = v.sort_values(ascending=False).tolist()
    allowed = set(v.round(2)) | {round(v.sum(), 2), round(v.mean(), 2), round(v.median(), 2), 3.0, 1.5}
    allowed |= {round(a - b, 2) for a in v for b in v} | {round(x / v.sum() * 100, 1) for x in v}
    allowed |= {round(sum(ordered[:3]) / v.sum() * 100, 1), round(ordered[0] / ordered[1], 2)}
    allowed |= {round((a - b) / abs(b) * 100, 1) for a in v for b in v if b}
    from src.ingest.profiling import find_outliers
    outliers = find_outliers(data[value])
    if outliers:
        allowed |= {round(outliers.low, 2), round(outliers.high, 2), float(outliers.count)}
    for fact in facts(data):
        text = re.sub(r"\d{4}-\d{2}(-\d{2})?", "", fact)  # period labels are not figures
        for label in data[data.columns[0]].astype(str):  # nor digits inside names ("Laptop Pro 14")
            text = text.replace(label, "")
        for number in re.findall(r"-?\d[\d,]*\.?\d*", text):
            n = float(number.replace(",", ""))
            assert any(abs(n - a) < 0.051 for a in allowed), (number, fact)


@pytest.mark.parametrize("question", demo_queries.demo_questions())
def test_facts_make_no_causal_or_forecast_claims(seeded_db, question):
    text = " ".join(facts(answer_question(seeded_db, question).data)).lower()
    for word in ("because", "due to", "caused", "will ", "forecast", "predict", "expect", "likely"):
        assert word not in text


def test_outliers_are_named():
    data = pd.DataFrame({"product": [f"p{i}" for i in range(9)], "units": [10, 11, 12, 13, 12, 11, 10, 12, 500]})
    found = " ".join(facts(data))
    assert "Possible outliers in units (1 outside" in found and ": p8." in found


def test_truncated_results_say_so():
    data = pd.DataFrame({"r": ["a", "b"], "v": [1, 2]})
    assert facts(data, truncated=True)[-1] == "These figures describe the 2 rows shown, not the full result."


@pytest.mark.parametrize("data", [
    pd.DataFrame(), pd.DataFrame({"r": ["a"], "v": [None]}), pd.DataFrame({"name": ["x", "y"]}),
    pd.DataFrame({"r": ["a", "b"], "v": [-5.0, -1.0]}), pd.DataFrame({"r": ["a", "b"], "v": [0, 0]}),
])
def test_unusual_results_never_fail(data):
    facts(data)
    chart_options(data)
    statistics(data)


# --- Follow-up questions ----------------------------------------------------------------

def test_demo_follow_ups_are_the_demo_questions_not_yet_asked():
    asked = [TOP5, BY_REGION.lower()]
    assert follow_ups(pd.DataFrame(), "demo", asked) == [BY_CATEGORY, MONTHLY, BOTTOM5]


def test_ai_follow_ups_use_the_result_columns():
    by_region = pd.DataFrame({"region": ["N", "S"], "revenue": [2.0, 1.0]})
    assert follow_ups(by_region, "ai", []) == [
        "Which region has the lowest revenue?", "What share of the total revenue does each region have?",
        "What are the top 3 region values by revenue?"]
    monthly = pd.DataFrame({"month": ["2025-01", "2025-02"], "units_sold": [1, 2]})
    assert follow_ups(monthly, "ai", [])[0] == "Which month had the highest units sold?"


def test_no_follow_ups_for_typed_sql_or_unsuitable_results():
    data = pd.DataFrame({"region": ["N", "S"], "revenue": [2.0, 1.0]})
    assert follow_ups(data, "sql", []) == []
    assert follow_ups(pd.DataFrame({"n": [5]}), "ai", []) == []


def test_follow_ups_skip_questions_already_asked():
    data = pd.DataFrame({"region": ["N", "S"], "revenue": [2.0, 1.0]})
    assert "Which region has the lowest revenue?" not in follow_ups(data, "ai", ["which region has the lowest revenue?"])
    assert len(follow_ups(data, "ai", [])) <= analysis.MAX_FOLLOW_UPS
