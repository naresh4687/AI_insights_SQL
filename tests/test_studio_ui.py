"""Dashboard Studio in the app (AppTest): add charts from answers, view, filter, arrange, manage."""

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import dashboards as dsh, data_access, demo_queries

APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")
ANALYST, STUDIO = "views/analyst.py", "views/studio.py"
TOP5, BY_REGION, BY_CATEGORY, MONTHLY, BOTTOM5 = demo_queries.demo_questions()


@pytest.fixture
def app(seeded_db, monkeypatch):
    monkeypatch.setenv("INSIGHTSQL_DB_PATH", str(seeded_db))
    return ok(AppTest.from_file(APP_PATH, default_timeout=60).run())


def ok(at):
    assert not at.exception, [e.value for e in at.exception]
    return at


def marks(at) -> list[str]:
    found = []
    for chart in at.get("vega_lite_chart"):
        mark = json.loads(chart.proto.spec).get("mark")
        found.append(mark["type"] if isinstance(mark, dict) else mark)
    return found


def add_answer(at, example: int, dashboard: str, chart_index: int = 0, new: bool = False):
    """Ask a demo question and add its answer to a dashboard (choosing a chart type first)."""
    ok(at.switch_page(ANALYST).run())
    ok(at.button(key=f"example_{example}").click().run())
    turn = len(at.session_state["chat"]) - 1
    key = f"turn_{turn}"
    if chart_index:
        ok(next(b for b in at.get("button_group") if b.key == f"charttype_{key}").set_value(chart_index).run())
    if new:
        at.text_input(key=f"adddash_name_{key}").set_value(dashboard)
    else:
        ok(at.selectbox(key=f"adddash_target_{key}").set_value(dashboard).run())
    ok(at.button(key=f"adddash_add_{key}").click().run())
    return at


@pytest.fixture
def board(app):
    add_answer(app, 3, "Sales", new=True)  # monthly → line
    add_answer(app, 1, "sales", chart_index=2)  # by region → pie
    return ok(app.switch_page(STUDIO).run())


def test_empty_studio_explains_and_creates(app):
    ok(app.switch_page(STUDIO).run())
    assert any("No dashboards yet" in h.proto.body for h in app.get("html"))
    app.text_input(key="studio_new_name").set_value("Empty one")
    ok(app.button(key="studio_create").click().run())
    assert app.selectbox(key="studio_dash").value == "empty_one"


def test_answers_are_added_with_their_chart_type(board):
    saved = dsh.store().get("sales")
    assert [(w.title, w.chart_kind, w.dataset_id) for w in saved.widgets] == [
        (MONTHLY, "line", "demo_sales"), (BY_REGION, "pie", "demo_sales")]
    assert marks(board) == ["line", "arc"]


def test_category_filter_narrows_compatible_charts(board):
    ok(board.selectbox(key="studio_filter_kind").set_value("category").run())
    ok(board.selectbox(key="studio_filter_column").set_value("region").run())
    ok(board.button(key="studio_add_filter").click().run())
    flt = dsh.store().get("sales").filters[0]
    ok(board.multiselect(key=f"studio_filter_{flt.filter_id}").set_value(["East", "West"]).run())
    captions = " ".join(c.value for c in board.caption)
    assert "Filtered by Region" in captions
    pie = next(d for d in board.dataframe if "region" in d.value.columns).value
    assert pie["region"].tolist() == ["East", "West"]


def test_date_filter_on_months(board):
    ok(board.selectbox(key="studio_filter_kind").set_value("date").run())
    ok(board.selectbox(key="studio_filter_column").set_value("month").run())
    ok(board.button(key="studio_add_filter").click().run())
    flt = dsh.store().get("sales").filters[0]
    from datetime import date
    ok(board.date_input(key=f"studio_filter_{flt.filter_id}").set_value((date(2025, 3, 1), date(2025, 4, 30))).run())
    monthly = next(d for d in board.dataframe if "month" in d.value.columns).value
    assert monthly["month"].tolist() == ["2025-03", "2025-04"]


def test_layout_editing(board):
    ok(board.toggle(key="studio_edit").set_value(True).run())
    first, second = dsh.store().get("sales").widgets
    ok(board.button(key=f"dwup_{second.widget_id}").click().run())
    assert [w.title for w in dsh.store().get("sales").widgets] == [BY_REGION, MONTHLY]
    board.text_input(key=f"dwtitle_{second.widget_id}").set_value("Regions")
    ok(board.selectbox(key=f"dwwidth_{second.widget_id}").set_value("full").run())
    ok(board.selectbox(key=f"dwkind_{second.widget_id}").set_value("donut").run())
    ok(board.button(key=f"dwsave_{second.widget_id}").click().run())
    saved = dsh.store().get("sales").widgets[0]
    assert (saved.title, saved.width, saved.chart_kind) == ("Regions", "full", "donut")
    ok(board.button(key=f"dwremove_{first.widget_id}").click().run())
    assert [w.title for w in dsh.store().get("sales").widgets] == ["Regions"]


def test_rename_duplicate_delete(board):
    board.text_input(key="studio_rename_sales").set_value("Sales 2025")
    ok(board.button(key="studio_rename").click().run())
    assert dsh.store().get("sales").name == "Sales 2025"
    ok(board.button(key="studio_duplicate").click().run())
    assert board.selectbox(key="studio_dash").value == "sales_2025_copy"
    assert len(dsh.store().get("sales_2025_copy").widgets) == 2
    assert board.button(key="studio_delete").disabled
    ok(board.checkbox(key="studio_delete_ok_sales_2025_copy").check().run())
    ok(board.button(key="studio_delete").click().run())
    assert [d.dashboard_id for d in dsh.store().list()] == ["sales"]


def test_exports_are_offered(board):
    keys = [d.key for d in board.get("download_button")]
    assert "studio_export" in keys and sum(k.startswith("dwcsv_") for k in keys) == 2


def test_chart_of_a_removed_dataset_shows_an_error(app, seeded_db):
    from tests.test_dataset_integration import STAFF_CSV, import_csv
    import_csv("Staff", STAFF_CSV)
    store = dsh.store()
    d = store.create("Staff board")
    store.add_widget(d.dashboard_id, "People", "", "staff", "SELECT name, salary FROM staff", "bar", "half", seeded_db)
    data_access.catalog().remove("staff")
    ok(app.switch_page(STUDIO).run())
    assert any("no longer available" in e.value for e in app.error)


def test_refresh_source_data(app, seeded_db, monkeypatch):
    from tests.servers import running_fake_api
    from tests.test_refresh import import_api
    from cryptography.fernet import Fernet
    monkeypatch.setenv("INSIGHTSQL_SECRET_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("INSIGHTSQL_REFRESH_RETRY_SECONDS", "0")
    with running_fake_api() as api:
        monkeypatch.setenv("INSIGHTSQL_ALLOWED_PRIVATE_HOSTS", f"127.0.0.1:{api.port}")
        import_api(api)
        store = dsh.store()
        d = store.create("Live")
        store.add_widget(d.dashboard_id, "Orders", "", "orders", "SELECT COUNT(*) AS n FROM orders", "kpi", "third",
                         seeded_db)
        ok(app.switch_page(STUDIO).run())
        assert {m.label: m.value for m in app.metric} == {"N": "7"}
        api.orders[:] = api.orders[:2]
        ok(app.button(key="studio_sync").click().run())
        assert any("Refreshed 1 of 1 source datasets." in s.value for s in app.success)
        assert {m.label: m.value for m in app.metric} == {"N": "2"}
