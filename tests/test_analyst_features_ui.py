"""AI Analyst enhancements in the app (AppTest): chart picker, KPI cards, insights, SQL
explanation, export button, follow-up questions and error hints."""

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import database, demo_queries

APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")
ANALYST, EXPLORER = "views/analyst.py", "views/explorer.py"
TOP5, BY_REGION, BY_CATEGORY, MONTHLY, BOTTOM5 = demo_queries.demo_questions()
GEMINI_MODE = "AI Mode (Gemini)"


@pytest.fixture
def app(seeded_db, monkeypatch):
    monkeypatch.setenv("INSIGHTSQL_DB_PATH", str(seeded_db))
    at = AppTest.from_file(APP_PATH, default_timeout=30).run()
    return ok(at.switch_page(ANALYST).run())


def ok(at):
    assert not at.exception, [e.value for e in at.exception]
    return at


def example(at, index):
    return ok(at.button(key=f"example_{index}").click().run())


def marks(at) -> list[str]:
    found = []
    for chart in at.get("vega_lite_chart"):
        spec = json.loads(chart.proto.spec)
        mark = spec.get("mark")
        found.append(mark["type"] if isinstance(mark, dict) else mark)
    return found


def markdown(at) -> str:
    return "\n".join(m.value for m in at.markdown)


def picker(at, key="charttype_turn_0"):
    return next(b for b in at.get("button_group") if b.key == key)


def run_sql(at, sql):
    at.text_area(key="custom_sql").input(sql)
    next(b for b in at.button if b.label == "Run SQL").click()
    return ok(at.run())


# --- Chart picker -------------------------------------------------------------------------

def test_default_chart_is_unchanged_and_other_types_are_offered(app):
    example(app, 1)  # revenue by region
    assert marks(app) == ["bar"]
    assert picker(app).options == ["Bar", "Column", "Pie", "Donut"] and picker(app).value == 0


@pytest.mark.parametrize("label, mark", [("Column", "bar"), ("Pie", "arc"), ("Donut", "arc")])
def test_switching_chart_type_redraws_the_chart(app, label, mark):
    example(app, 1)
    chooser = picker(app)
    ok(chooser.set_value(chooser.options.index(label)).run())
    assert marks(app) == [mark]


def test_time_result_offers_line_area_and_distributions(app):
    example(app, 3)  # monthly totals
    assert marks(app) == ["line"]
    assert picker(app).options == ["Line", "Area", "Column", "Histogram", "Box plot"]
    ok(picker(app).set_value(1).run())
    assert marks(app) == ["area"]


def test_single_value_is_shown_as_a_kpi_card(app):
    ok(app.switch_page(EXPLORER).run())
    run_sql(app, "SELECT COUNT(*) AS sale_count, ROUND(SUM(quantity * unit_price), 2) AS revenue FROM sales")
    assert {m.label: m.value for m in app.metric} == {"Sale count": "600", "Revenue": "283,700.56"}
    assert marks(app) == []


# --- Insights, SQL explanation and export -------------------------------------------------

def test_insights_tab_shows_facts_and_statistics(app):
    example(app, 1)
    text = markdown(app)
    assert "East accounts for 27.8% of the total revenue in this result (283,700.56)." in text
    assert "| revenue | 4 | 0 | 283,700.56 | 70,925.14 |" in text
    assert [t.label.split(" ", 1)[1] for t in app.tabs[:4]] == ["Results", "Visualization", "SQL", "Insights"]


def test_sql_tab_explains_the_query(app):
    example(app, 0)
    text = markdown(app)
    assert "**What this query does**" in text
    assert "- Joins products (as p) where p.product\\_id = s.product\\_id." in text
    assert "- Returns at most 5 rows." in text


def test_results_can_be_downloaded(app):
    example(app, 0)
    [download] = app.get("download_button")
    assert download.proto.label == "Download CSV"
    assert download.key == "download_turn_0"


# --- Follow-up questions --------------------------------------------------------------------

def test_demo_follow_ups_ask_the_next_demo_questions(app):
    example(app, 0)
    follow = [b for b in app.button if b.key and "followup_" in b.key]
    assert [b.label for b in follow] == [BY_REGION, BY_CATEGORY, MONTHLY]
    ok(follow[0].click().run())
    assert [t.question for t in app.session_state["chat"]] == [TOP5, BY_REGION]
    assert app.session_state["chat"][-1].answer is not None
    labels = [b.label for b in app.button if b.key and "followup_" in b.key]
    assert labels == [BY_CATEGORY, MONTHLY, BOTTOM5]  # only under the latest answer, nothing repeated
    assert all(b.key.startswith("followup_turn_1_") for b in app.button if b.key and "followup_" in b.key)


def test_ai_follow_up_is_answered_through_the_validated_pipeline(app, fake_gemini, seeded_db):
    app.run()
    ok(app.radio(key="mode").set_value(GEMINI_MODE).run())
    fake_gemini.reply_sql("SELECT region, SUM(quantity * unit_price) AS revenue FROM sales GROUP BY region")
    ok(app.chat_input(key="chat_question").set_value("Revenue by region?").run())
    follow = [b for b in app.button if b.key and "followup_" in b.key]
    assert follow[0].label == "Which region has the lowest revenue?"
    fake_gemini.reply_sql("DELETE FROM sales")  # whatever the follow-up produces is validated
    asked_before = len(fake_gemini.generate_requests)
    ok(follow[0].click().run())
    turn = app.session_state["chat"][-1]
    assert turn.question == "Which region has the lowest revenue?" and turn.source == "ai"
    assert len(fake_gemini.generate_requests) == asked_before + 1  # it really went to the AI service
    assert fake_gemini.generate_requests[-1]["contents"][0]["parts"][0]["text"] == turn.question
    assert turn.error[0] == "rejected" and "read-only" in turn.error[1]
    assert database.recent_history(seeded_db)[0]["status"] == "rejected"


def test_no_follow_ups_after_an_error(app):
    ok(app.chat_input(key="chat_question").set_value("Who is our best salesperson?").run())
    assert not [b for b in app.button if b.key and "followup_" in b.key]


# --- Error hints -------------------------------------------------------------------------

@pytest.mark.parametrize("sql, hint", [
    ("SELECT revenu FROM sales", "There is no column named revenu."),
    ("SELECT * FROM query_history", "can only use products, sales"),
    ("SELECT 1; SELECT 2", "one statement at a time"),
])
def test_errors_come_with_a_hint(app, sql, hint):
    ok(app.switch_page(EXPLORER).run())
    run_sql(app, sql)
    assert any(hint in c.value for c in app.caption), [c.value for c in app.caption]
