"""Dashboard tests using Streamlit's AppTest (runs the real app script and widgets, no browser).

Each test points the app at a fresh temporary database via INSIGHTSQL_DB_PATH. Pages are
reached with ``AppTest.switch_page`` or by clicking the app's own buttons. Browser-level
tests with Playwright are in test_app_e2e.py.

The scenarios of the single-page UI (before the dark redesign) are all kept, under the same
test names, adapted to the page where that feature now lives.
"""

import json
from pathlib import Path

import pyarrow as pa
import pytest
from streamlit.testing.v1 import AppTest

from src import analytics, database, demo_queries
from tests.conftest import GEMINI_TEST_KEY, TEST_TOKEN

APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")
TOP5, BY_REGION, BY_CATEGORY, MONTHLY, BOTTOM5 = demo_queries.demo_questions()
DASHBOARD, ANALYST, HISTORY, EXPLORER, SETTINGS = (
    "views/dashboard.py", "views/analyst.py", "views/history.py", "views/explorer.py", "views/settings.py")
AI_SQL = (
    "SELECT s.region, ROUND(SUM(s.quantity * s.unit_price), 2) AS revenue "
    "FROM sales s GROUP BY s.region ORDER BY revenue DESC"
)
HF_MODE, GEMINI_MODE = "AI Mode (Hugging Face)", "AI Mode (Gemini)"


@pytest.fixture
def app(seeded_db, monkeypatch):
    monkeypatch.setenv("INSIGHTSQL_DB_PATH", str(seeded_db))
    at = AppTest.from_file(APP_PATH, default_timeout=30).run()
    assert not at.exception
    return at


# --- Helpers ------------------------------------------------------------------

def _go(at, page):
    at.switch_page(page).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _switch_mode(at, label):
    at.run()  # re-render so the mode labels reflect settings made after the first render
    at.radio(key="mode").set_value(label).run()
    assert not at.exception
    return at


def _ask(at, text):
    """Type a question in the AI Analyst chat input and submit it."""
    at.chat_input(key="chat_question").set_value(text).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _run_sql(at, sql):
    """SQL Explorer: type and submit in one run (form widgets are sent with the submit)."""
    at.text_area(key="custom_sql").input(sql)
    next(b for b in at.button if b.label == "Run SQL").click()
    at.run()
    assert not at.exception
    return at


def _html(at) -> str:
    return "\n".join(element.proto.body for element in at.get("html"))


def _chart_marks(at) -> list[set]:
    """Mark types used by each chart on the page (searching layered specs too)."""
    def marks(node):
        if isinstance(node, dict):
            found = {node["mark"]["type"]} if isinstance(node.get("mark"), dict) else set()
            if isinstance(node.get("mark"), str):
                found.add(node["mark"])
            for child in node.values():
                found |= marks(child)
            return found
        if isinstance(node, list):
            return set().union(*(marks(item) for item in node)) if node else set()
        return set()
    return [marks(json.loads(chart.proto.spec)) for chart in at.get("vega_lite_chart")]


def _chart_data(at, index) -> list[list]:
    """Rows the chart actually draws (Streamlit sends them as an Arrow dataset)."""
    dataset = at.get("vega_lite_chart")[index].proto.datasets[0]
    return pa.ipc.open_stream(dataset.data.data).read_pandas().values.tolist()


def _turns(at):
    return at.session_state["chat"]


def _last_table(at):
    return at.dataframe[-1].value


def _errors(at) -> list[str]:
    return [e.value for e in at.error]


def _sales(db) -> int:
    conn = database.connect(db)
    try:
        return conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
    finally:
        conn.close()


# --- Start-up, navigation and layout ---------------------------------------------

def test_initial_page_shows_title_mode_and_examples(app):
    """The app starts on the Dashboard in Demo Mode; the AI Analyst shows the 5 suggestions."""
    assert "Your Data, Intelligently Analyzed" in _html(app)
    assert app.radio(key="mode").value == "Demo Mode"
    assert "Demo Mode" in _html(app)
    _go(app, ANALYST)
    assert [app.button(key=f"example_{i}").label for i in range(5)] == demo_queries.demo_questions()
    assert len(app.code) == 0 and len(app.dataframe) == 0


@pytest.mark.parametrize("page, heading", [
    (DASHBOARD, "Your Data, Intelligently Analyzed"),
    (ANALYST, "Ask your data a question"),
    (HISTORY, "Every question, with its outcome"),
    (EXPLORER, "Inspect and run read-only SQL"),
    (SETTINGS, "Configuration and status"),
])
def test_every_page_renders_without_errors(app, page, heading):
    _go(app, page)
    assert heading in _html(app)


def test_dashboard_button_opens_the_ai_analyst(app):
    app.button(key="cta_analyst").click().run()
    assert "Ask your data a question" in _html(app)


def test_mode_is_kept_when_changing_pages(app, fake_gemini):
    _switch_mode(app, GEMINI_MODE)
    _go(app, HISTORY)
    _go(app, ANALYST)
    assert app.radio(key="mode").value == GEMINI_MODE
    assert "AI Mode (Gemini)" in _html(app)


def test_sidebar_shows_version_and_demo_status(app):
    sidebar = _html(app)
    assert "InsightSQL v" in sidebar and "works offline" in sidebar


# --- Dashboard: real figures --------------------------------------------------------

def test_kpis_match_the_database(app, seeded_db):
    conn = database.connect(seeded_db)
    revenue, sales, units = conn.execute(
        "SELECT ROUND(SUM(quantity * unit_price), 2), COUNT(*), SUM(quantity) FROM sales").fetchone()
    products = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    conn.close()

    metrics = {m.label: m.value for m in app.metric}
    assert metrics == {
        "Total revenue": f"${revenue:,.2f}",
        "Total sales": f"{sales:,}",
        "Products": f"{products:,}",
        "Average sale value": f"${revenue / sales:,.2f}",
    }
    assert metrics["Total revenue"] == "$283,700.56"  # golden value of the sample data
    assert units == 7332


def test_dashboard_charts_draw_the_query_results(app, seeded_db):
    marks = _chart_marks(app)
    assert len(marks) == 4
    assert "line" in marks[0] and all("bar" in m for m in marks[1:])

    expected = [
        analytics.monthly_revenue(seeded_db),
        analytics.revenue_by_region(seeded_db),
        analytics.revenue_by_category(seeded_db),
        analytics.top_products(seeded_db),
    ]
    for index, frame in enumerate(expected):
        assert _chart_data(app, index) == frame.values.tolist()


def test_month_over_month_caption_uses_real_months(app, seeded_db):
    monthly = analytics.monthly_revenue(seeded_db)
    last, prev = monthly.iloc[-1], monthly.iloc[-2]
    pct = (last["revenue"] - prev["revenue"]) / prev["revenue"] * 100
    caption = next(c.value for c in app.caption if c.value.startswith(last["month"]))
    assert f"up {pct:.1f}% from {prev['month']}" in caption
    assert "\\$" in caption  # money is escaped so Markdown does not treat it as maths


def test_dashboard_recent_activity_lists_history(app):
    _go(app, ANALYST)
    app.button(key="example_1").click().run()
    _go(app, DASHBOARD)
    assert any(BY_REGION in m.value for m in app.markdown)
    assert "No questions asked yet" not in _html(app)


def test_empty_database_shows_empty_states(tmp_path, monkeypatch):
    db = tmp_path / "empty.db"
    database.init_db(db)
    monkeypatch.setenv("INSIGHTSQL_DB_PATH", str(db))
    at = AppTest.from_file(APP_PATH, default_timeout=30).run()
    assert not at.exception
    page = _html(at)
    assert "No sales data yet" in page and "No questions asked yet" in page
    assert len(at.metric) == 0 and len(at.get("vega_lite_chart")) == 0
    _go(at, HISTORY)
    assert "No history yet" in _html(at)
    _go(at, EXPLORER)
    assert "No query run yet" in _html(at)


# --- AI Analyst: main workflow ------------------------------------------------------

def test_example_button_shows_sql_table_chart_explanation_and_history(app):
    _go(app, ANALYST)
    app.button(key="example_0").click().run()
    assert not app.exception

    assert "LIMIT 5" in app.code[0].value
    table = _last_table(app)
    assert len(table) == 5
    assert table.iloc[0].tolist() == ["Laptop Pro 14", 102900.0]
    assert _chart_marks(app) == [{"bar"}]
    assert any("Laptop Pro 14 has the highest revenue" in m.value for m in app.markdown)
    assert any("no AI request was made" in c.value for c in app.caption)
    assert [t.label.split(" ", 1)[1] for t in app.tabs[:3]] == ["Results", "Visualization", "SQL"]
    assert "Success" in _html(app)

    _go(app, HISTORY)
    assert any(TOP5 in m.value for m in app.markdown)
    assert "Success" in _html(app)


def test_typed_question_is_answered(app):
    _go(app, ANALYST)
    _ask(app, "what is the total revenue by region?")
    assert _last_table(app)["region"].tolist() == ["East", "South", "West", "North"]
    assert _chart_marks(app) == [{"bar"}]


def test_monthly_question_renders_a_line_chart(app):
    _go(app, ANALYST)
    _ask(app, MONTHLY)
    assert len(_last_table(app)) == 12
    assert "line" in _chart_marks(app)[0]


def test_conversation_persists_across_reruns_and_pages(app):
    _go(app, ANALYST)
    app.button(key="example_0").click().run()
    _ask(app, BY_REGION)
    assert len(_turns(app)) == 2
    app.run()
    app.run()
    assert len(_turns(app)) == 2  # reruns do not repeat or lose questions
    _go(app, SETTINGS)
    _go(app, ANALYST)
    assert [t.question for t in _turns(app)] == [TOP5, BY_REGION]
    assert len(app.code) == 2  # both answers still shown


def test_each_question_runs_exactly_once(app, seeded_db):
    _go(app, ANALYST)
    app.button(key="example_2").click().run()
    app.run()
    app.run()
    assert [h["question"] for h in database.recent_history(seeded_db)] == [BY_CATEGORY]


def test_new_chat_clears_the_conversation(app):
    _go(app, ANALYST)
    assert app.button(key="new_chat").disabled
    app.button(key="example_0").click().run()
    app.button(key="new_chat").click().run()
    assert _turns(app) == []
    assert len(app.code) == 0
    assert app.button(key="example_0")  # suggestions are back


def test_history_lists_newest_first(app):
    _go(app, ANALYST)
    app.button(key="example_1").click().run()
    app.button(key="example_2").click().run()
    _go(app, HISTORY)
    questions = [m.value.strip("*") for m in app.markdown if m.value.startswith("**")]
    assert questions[:2] == [BY_CATEGORY, BY_REGION]


# --- Errors -------------------------------------------------------------------

def test_empty_question_shows_error(app, seeded_db):
    _go(app, ANALYST)
    _ask(app, "   ")
    assert any("Please enter a question" in e for e in _errors(app))
    assert len(app.code) == 0
    assert database.recent_history(seeded_db) == []


def test_unsupported_question_is_rejected_and_logged(app, seeded_db):
    _go(app, ANALYST)
    _ask(app, "Who is our best salesperson?")
    assert any("Request rejected" in e and "Demo Mode only answers" in e for e in _errors(app))
    assert "Rejected" in _html(app)
    assert database.recent_history(seeded_db)[0]["status"] == "rejected"


def test_error_replaces_previous_answer(app):
    """SQL Explorer shows one result: a later error replaces an earlier success.
    (In the chat, each question keeps its own answer.)"""
    _go(app, EXPLORER)
    _run_sql(app, "SELECT COUNT(*) AS n FROM sales")
    assert len(app.code) == 1
    _run_sql(app, "DROP TABLE sales")
    assert len(app.code) == 0
    assert len(app.error) == 1


# --- SQL Explorer and security regression -------------------------------------------

def test_unsafe_sql_is_rejected_and_data_unchanged(app, seeded_db):
    _go(app, EXPLORER)
    _run_sql(app, "DROP TABLE sales")
    assert any("Request rejected" in e and "read-only SELECT" in e for e in _errors(app))
    assert len(app.code) == 0
    assert _sales(seeded_db) == 600


def test_restricted_table_via_sql_is_rejected(app):
    _go(app, EXPLORER)
    _run_sql(app, "SELECT * FROM query_history")
    assert any("query" in e and "history" in e and "not available" in e for e in _errors(app))


@pytest.mark.parametrize("sql", [
    "INSERT INTO products VALUES (99, 'x', 'y', 1.0)",
    "UPDATE sales SET quantity = 0",
    "DELETE FROM sales",
    "DROP TABLE sales",
    "ALTER TABLE sales ADD COLUMN hacked TEXT",
    "SELECT 1; DROP TABLE sales",
    "SELECT name FROM sqlite_master",
    "SELECT * FROM query_history",
    "SELEC * FRM sales",
])
def test_explorer_rejects_unsafe_or_malformed_sql(app, seeded_db, sql):
    _go(app, EXPLORER)
    _run_sql(app, sql)
    assert any("Request rejected" in e or "Query failed" in e for e in _errors(app))
    assert len(app.code) == 0
    assert _sales(seeded_db) == 600
    conn = database.connect(seeded_db)
    assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 12
    assert "hacked" not in [r[1] for r in conn.execute("PRAGMA table_info(sales)")]
    conn.close()


def test_safe_custom_sql_runs_without_a_chart_for_single_value(app):
    _go(app, EXPLORER)
    _run_sql(app, "SELECT COUNT(*) AS sale_count FROM sales")
    assert any("The result is sale count: 600." in m.value for m in app.markdown)
    assert _chart_marks(app) == []
    assert any("not suited to a simple chart" in c.value for c in app.caption)
    assert any("Your SQL" in c.value for c in app.caption)


def test_empty_sql_is_explained(app):
    _go(app, EXPLORER)
    _run_sql(app, "  ")
    assert any("Enter a SQL query to run" in e for e in _errors(app))


def test_explorer_measures_the_run(app):
    _go(app, EXPLORER)
    _run_sql(app, "SELECT region FROM sales GROUP BY region")
    assert "4 rows" in _html(app) and " s</span>" in _html(app)


# --- Query History: search, filter, reruns (always revalidated) ---------------------

def test_history_search_and_status_filter(app):
    _go(app, ANALYST)
    app.button(key="example_0").click().run()
    _ask(app, "Who is our best salesperson?")
    _go(app, HISTORY)
    app.text_input(key="history_search").input("salesperson").run()
    questions = [m.value for m in app.markdown if m.value.startswith("**")]
    assert questions == ["**Who is our best salesperson?**"]
    app.text_input(key="history_search").input("").run()
    app.segmented_control(key="history_status").set_value("Success").run()
    questions = [m.value for m in app.markdown if m.value.startswith("**")]
    assert questions == [f"**{TOP5}**"]


def test_ask_again_reruns_the_question_through_the_pipeline(app, seeded_db):
    _go(app, ANALYST)
    app.button(key="example_1").click().run()
    first_id = database.recent_history(seeded_db)[0]["history_id"]
    _go(app, HISTORY)
    app.button(key=f"rerun_{first_id}").click().run()
    assert "Ask your data a question" in _html(app)  # moved to the AI Analyst
    assert len(_turns(app)) == 2 and _turns(app)[-1].answer is not None
    assert [h["question"] for h in database.recent_history(seeded_db)][:2] == [BY_REGION, BY_REGION]


def test_tampered_history_sql_is_revalidated_in_the_explorer(app, seeded_db):
    """Even if the history table held malicious SQL, it only reaches the editor and is
    validated again when run."""
    database.add_history(seeded_db, "Looks harmless", "DELETE FROM sales", "success")
    entry_id = database.recent_history(seeded_db)[0]["history_id"]
    _go(app, HISTORY)
    app.button(key=f"explore_{entry_id}").click().run()
    _go(app, EXPLORER)  # AppTest re-runs the test's selected page; the browser stays on the Explorer
    assert app.text_area(key="custom_sql").value == "DELETE FROM sales"
    assert _sales(seeded_db) == 600  # opening it ran nothing
    next(b for b in app.button if b.label == "Run SQL").click().run()
    assert any("Request rejected" in e for e in _errors(app))
    assert _sales(seeded_db) == 600


def test_tampered_history_question_is_answered_by_the_current_mode(app, seeded_db):
    """'Ask again' sends the stored question, never the stored SQL."""
    database.add_history(seeded_db, TOP5, "DROP TABLE sales", "success")
    entry_id = database.recent_history(seeded_db)[0]["history_id"]
    _go(app, HISTORY)
    app.button(key=f"rerun_{entry_id}").click().run()
    assert _turns(app)[-1].answer.sql.endswith("LIMIT 5")
    assert _sales(seeded_db) == 600


def test_ai_generated_sql_can_be_loaded_into_the_explorer(app, fake_gemini):
    fake_gemini.reply_sql(AI_SQL)
    _switch_mode(app, GEMINI_MODE)
    _go(app, ANALYST)
    _ask(app, "Revenue per region please")
    _go(app, EXPLORER)
    app.button(key="load_ai_sql").click().run()
    assert "GROUP BY s.region" in app.text_area(key="custom_sql").value


# --- Mode selection and AI Mode (Hugging Face replaced by a local fake server) -------

def test_demo_mode_is_the_default(app):
    assert app.radio(key="mode").value == "Demo Mode"


def test_ai_mode_answers_with_model_sql(app, fake_hf):
    fake_hf.reply_sql(AI_SQL)
    _switch_mode(app, HF_MODE)
    assert "Qwen/Qwen2.5-Coder-32B-Instruct is available" in _html(app)

    _go(app, ANALYST)
    _ask(app, "Show revenue for each region")

    assert fake_hf.chat_requests[0]["messages"][1]["content"] == "Show revenue for each region"
    assert _last_table(app)["region"].tolist() == ["East", "South", "West", "North"]
    assert _chart_marks(app) == [{"bar"}]
    assert any("AI-generated SQL" in c.value for c in app.caption)
    assert any("East has the highest revenue" in m.value for m in app.markdown)


def test_example_button_in_ai_mode_asks_the_model(app, fake_hf):
    fake_hf.reply_sql(AI_SQL)
    _switch_mode(app, HF_MODE)
    _go(app, ANALYST)
    app.button(key="example_1").click().run()
    assert len(fake_hf.chat_requests) == 1
    assert any("AI-generated SQL" in c.value for c in app.caption)


def test_ai_mode_rejects_malicious_model_output(app, fake_hf, seeded_db):
    fake_hf.reply_sql("DROP TABLE sales")
    _switch_mode(app, HF_MODE)
    _go(app, ANALYST)
    _ask(app, "Remove the sales table")
    assert any("Request rejected" in e and "read-only SELECT" in e for e in _errors(app))
    assert len(app.code) == 0
    assert _sales(seeded_db) == 600


def test_hf_unreachable_shows_help_and_demo_mode_still_works(app, hf_down):
    _switch_mode(app, HF_MODE)
    assert "Could not connect to Hugging Face" in _html(app)
    _go(app, ANALYST)
    _ask(app, "Show revenue for each region")
    assert any("Query failed" in e and "Could not connect" in e for e in _errors(app))

    _switch_mode(app, "Demo Mode")
    app.button(key="example_0").click().run()  # suggestions stay available under the chat
    assert len(_last_table(app)) == 5
    assert any("no AI request was made" in c.value for c in app.caption)


def test_unavailable_model_is_reported_in_ai_mode(app, fake_hf):
    fake_hf.models = ["meta-llama/Llama-3.3-70B-Instruct"]
    _switch_mode(app, HF_MODE)
    assert "HF_MODEL" in _html(app)


def test_missing_token_shows_setup_help(app, no_hf_token):
    _switch_mode(app, HF_MODE)
    assert "huggingface.co/settings/tokens" in _html(app)
    _go(app, ANALYST)
    _ask(app, "Show revenue for each region")
    assert any("Query failed" in e and "HF\\_TOKEN" in e for e in _errors(app))
    assert no_hf_token.requests == []


# --- AI Mode with Gemini (the default provider; Gemini replaced by a local fake server) ----

def test_gemini_is_the_default_ai_mode(app):
    assert app.radio(key="mode").options == ["Demo Mode", GEMINI_MODE]


def test_gemini_mode_answers_with_model_sql(app, fake_gemini, seeded_db):
    fake_gemini.reply_sql(AI_SQL)
    _switch_mode(app, GEMINI_MODE)
    assert "Gemini model gemini-3.5-flash-lite is available" in _html(app)

    _go(app, ANALYST)
    _ask(app, "Show revenue for each region")

    assert fake_gemini.generate_requests[0]["contents"][0]["parts"][0]["text"] == "Show revenue for each region"
    assert _last_table(app)["region"].tolist() == ["East", "South", "West", "North"]
    assert _chart_marks(app) == [{"bar"}]
    assert any("AI-generated SQL (Gemini model)" in c.value for c in app.caption)
    assert any("East has the highest revenue" in m.value for m in app.markdown)
    assert database.recent_history(seeded_db)[0]["status"] == "success"


def test_gemini_mode_rejects_malicious_model_output(app, fake_gemini, seeded_db):
    fake_gemini.reply_sql("DROP TABLE sales")
    _switch_mode(app, GEMINI_MODE)
    _go(app, ANALYST)
    _ask(app, "Remove the sales table")
    assert any("Request rejected" in e and "read-only SELECT" in e for e in _errors(app))
    assert len(app.code) == 0
    assert _sales(seeded_db) == 600


@pytest.mark.parametrize("sql", ["INSERT INTO products VALUES (99, 'x', 'y', 1.0)", "UPDATE sales SET quantity = 0",
                                 "DELETE FROM sales", "ALTER TABLE sales ADD COLUMN x TEXT",
                                 "SELECT 1; DELETE FROM sales", "SELECT * FROM query_history"])
def test_unsafe_ai_sql_is_rejected_in_the_chat(app, fake_gemini, seeded_db, sql):
    fake_gemini.reply_sql(sql)
    _switch_mode(app, GEMINI_MODE)
    _go(app, ANALYST)
    _ask(app, "Do something")
    assert any("Request rejected" in e for e in _errors(app))
    assert _sales(seeded_db) == 600


def test_gemini_quota_error_is_shown_and_demo_mode_still_works(app, fake_gemini):
    fake_gemini.fail(429, "RESOURCE_EXHAUSTED", "Resource has been exhausted (e.g. check quota).")
    _switch_mode(app, GEMINI_MODE)
    _go(app, ANALYST)
    _ask(app, "Show revenue for each region")
    assert any("Query failed" in e and "quota or rate limit" in e for e in _errors(app))
    assert "Failed" in _html(app)

    _switch_mode(app, "Demo Mode")
    _ask(app, TOP5)
    assert len(_last_table(app)) == 5


def test_missing_gemini_key_shows_setup_help(app, no_gemini_key):
    _switch_mode(app, GEMINI_MODE)
    assert "aistudio.google.com/apikey" in _html(app)
    _go(app, ANALYST)
    _ask(app, "Show revenue for each region")
    assert any("Query failed" in e and "GEMINI\\_API\\_KEY" in e for e in _errors(app))
    assert no_gemini_key.requests == []


def test_invalid_ai_provider_setting_does_not_crash_the_app(app, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openai")
    _switch_mode(app, GEMINI_MODE)
    assert "AI_PROVIDER must be one of" in _html(app)
    _go(app, ANALYST)
    _ask(app, "Show revenue for each region")
    assert any("Query failed" in e and "AI\\_PROVIDER" in e for e in _errors(app))
    _go(app, SETTINGS)


# --- Settings: real status, secrets never shown ----------------------------------------

def test_settings_never_shows_the_key_and_checks_before_claiming(app, fake_gemini):
    _go(app, SETTINGS)
    page = _html(app) + "".join(m.value for m in app.markdown)
    assert GEMINI_TEST_KEY not in page
    assert "API key: **configured**" in page
    assert "Connection not checked yet" in "".join(c.value for c in app.caption)
    assert fake_gemini.requests == []  # opening Settings made no request

    app.button(key="test_connection").click().run()
    assert "Connected" in _html(app)
    assert [m for m, p, _ in fake_gemini.requests] == ["GET"]  # a real check, no generation
    assert GEMINI_TEST_KEY not in _html(app) + "".join(s.value for s in app.success)


def test_settings_reports_failed_connection(app, fake_gemini):
    fake_gemini.fail(400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid API key.")
    _go(app, SETTINGS)
    app.button(key="test_connection").click().run()
    assert "Not available" in _html(app)
    assert any("rejected the API key" in w.value for w in app.warning)


def test_settings_without_key_says_not_configured(app):
    _go(app, SETTINGS)
    assert any("API key: **not configured**" in m.value for m in app.markdown)
    assert any("Products: **12** · Sales: **600**" in m.value for m in app.markdown)


def test_hf_token_never_shown(app, fake_hf):
    _switch_mode(app, HF_MODE)
    _go(app, SETTINGS)
    assert TEST_TOKEN not in _html(app) + "".join(m.value for m in app.markdown)
