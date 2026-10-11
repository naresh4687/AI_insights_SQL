"""Datasets page (AppTest): list, details, refresh settings, Refresh now and history."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import data_access
from src.sync import refresh as sync
from tests.test_refresh import api, import_api, rows  # noqa: F401 (fixture)

APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")
DATASETS = "views/datasets.py"


@pytest.fixture
def app(seeded_db, monkeypatch, api):  # noqa: F811
    monkeypatch.setenv("INSIGHTSQL_DB_PATH", str(seeded_db))
    import_api(api)
    at = AppTest.from_file(APP_PATH, default_timeout=60).run()
    ok(at.switch_page(DATASETS).run())
    return ok(at.selectbox(key="ds_selected").set_value("orders").run())


def ok(at):
    assert not at.exception, [e.value for e in at.exception]
    return at


def table(at, column):
    return next(d.value for d in at.dataframe if column in d.value.columns)


def test_lists_every_dataset_with_its_source(app):
    listed = table(app, "Dataset id")
    assert listed["Dataset id"].tolist() == ["demo_sales", "orders"]
    assert listed["Source"].tolist() == ["DEMO", "REST"] and listed["Schedule"].tolist() == ["—", "Manual"]
    assert any("API endpoint /orders" in m.value for m in app.markdown)


def test_refresh_now_shows_the_result_and_history(app, api):  # noqa: F811
    api.orders[0]["amount"] = 77.0
    ok(app.button(key="ds_refresh_now").click().run())
    assert any("Replaced with 7 rows." in s.value for s in app.success)
    assert rows()[0] == (1, 77.0)
    history = table(app, "Trigger")
    assert history["Status"].tolist() == ["success"] and history["Total"].tolist() == [7]


def test_failed_refresh_is_explained_and_data_kept(app, api):  # noqa: F811
    before = rows()
    api.orders.clear()
    ok(app.button(key="ds_refresh_now").click().run())
    assert any("previous data is kept" in e.value for e in app.error)
    assert rows() == before and table(app, "Trigger")["Status"].tolist() == ["failed"]


def test_schedule_is_saved(app):
    ok(app.selectbox(key="ds_schedule_orders").set_value(60).run())
    ok(app.button(key="ds_save").click().run())
    assert any("Refresh settings saved. Next run:" in s.value for s in app.success)
    settings = sync.state().settings("orders")
    assert settings.enabled and settings.interval_minutes == 60
    assert table(app, "Dataset id")["Schedule"].tolist()[1] == "Every hour"


def test_api_datasets_offer_full_refresh_only(app):
    assert app.radio(key="ds_mode_orders").options == ["Full (replace all rows)"]


def test_file_datasets_explain_how_to_update(app, seeded_db):
    from tests.test_dataset_integration import STAFF_CSV, import_csv
    import_csv("Staff", STAFF_CSV)
    ok(app.run())
    ok(app.selectbox(key="ds_selected").set_value("staff").run())
    assert any("Imported from a file" in c.value for c in app.caption)
    assert not [b for b in app.button if b.key == "ds_refresh_now"]
    assert data_access.catalog().get("staff").refresh_status.value == "never"
