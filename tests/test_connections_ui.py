"""Connections page (AppTest): saving, testing, browsing and importing; secrets never shown."""

import json
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from streamlit.testing.v1 import AppTest

from src import config, data_access
from src.connectors.profiles import ConnectionStore
from tests.servers import API_TOKEN, READER_PASSWORD, db_servers, running_fake_api  # noqa: F401

APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")
CONNECTIONS = "views/connections.py"


@pytest.fixture
def api(monkeypatch):
    with running_fake_api() as fake:
        monkeypatch.setenv("INSIGHTSQL_ALLOWED_PRIVATE_HOSTS", f"127.0.0.1:{fake.port}")
        yield fake


@pytest.fixture
def app(seeded_db, monkeypatch):
    monkeypatch.setenv("INSIGHTSQL_DB_PATH", str(seeded_db))
    monkeypatch.setenv("INSIGHTSQL_SECRET_KEY", Fernet.generate_key().decode())
    at = AppTest.from_file(APP_PATH, default_timeout=60).run()
    return ok(at.switch_page(CONNECTIONS).run())


def ok(at):
    assert not at.exception, [e.value for e in at.exception]
    return at


def plain(text: str) -> str:
    """Message text without Markdown escaping (\\_ → _)."""
    return text.replace("\\", "")


def everything_shown(at) -> str:
    """All text the page shows, including widget values, to check secrets never appear."""
    parts = [str(getattr(e, "value", "")) for kind in ("markdown", "caption", "success", "error", "warning", "info")
             for e in getattr(at, kind)]
    parts += [str(w.value) for w in at.text_input] + [d.value.to_csv() for d in at.dataframe]
    parts += [e.proto.body for e in at.get("html")]
    return "\n".join(parts)


def save_api(at, api, name="Shop API", auth="bearer", secret=API_TOKEN):
    ok(at.selectbox(key="conn_kind___new__").set_value("rest").run())
    at.text_input(key="conn_name___new__").set_value(name)
    at.text_input(key="conn_url___new__").set_value(api.base_url)
    ok(at.selectbox(key="conn_auth___new__").set_value(auth).run())
    if secret:
        at.text_input(key="conn_secret___new__").set_value(secret)
    return ok(at.button(key="conn_save").click().run())


def test_page_starts_empty_with_a_key_warning_when_needed(seeded_db, monkeypatch):
    monkeypatch.setenv("INSIGHTSQL_DB_PATH", str(seeded_db))
    at = ok(AppTest.from_file(APP_PATH, default_timeout=60).run().switch_page(CONNECTIONS).run())
    assert any("INSIGHTSQL_SECRET_KEY" in plain(w.value) for w in at.warning)
    assert "No connections yet" in everything_shown(at)


def test_saving_an_api_connection_never_shows_the_secret(app, api):
    save_api(app, api)
    assert any("Saved connection 'Shop API'" in s.value for s in app.success)
    profile = ConnectionStore(config.get_app_db_path()).get("shop_api")
    assert profile.has_secret and profile.settings["auth"] == "bearer"
    assert API_TOKEN not in everything_shown(app)
    assert app.selectbox(key="conn_edit_id").value == "shop_api"
    assert app.text_input(key="conn_secret_shop_api").value == ""  # never filled back in


def test_saving_without_a_key_explains_how_to_create_one(seeded_db, monkeypatch, api):
    monkeypatch.setenv("INSIGHTSQL_DB_PATH", str(seeded_db))
    at = ok(AppTest.from_file(APP_PATH, default_timeout=60).run().switch_page(CONNECTIONS).run())
    save_api(at, api)
    assert any("Fernet.generate_key" in plain(e.value) for e in at.error)
    assert ConnectionStore(config.get_app_db_path()).list() == []


def test_invalid_settings_are_explained(app):
    ok(app.selectbox(key="conn_kind___new__").set_value("rest").run())
    app.text_input(key="conn_name___new__").set_value("Bad")
    app.text_input(key="conn_url___new__").set_value("http://api.example.com")
    ok(app.button(key="conn_save").click().run())
    assert any("Use https://" in e.value for e in app.error)


def test_api_preview_fetch_and_import(app, api):
    save_api(app, api)
    app.text_input(key="conn_api_path").set_value("/orders")
    ok(app.text_input(key="conn_api_records").set_value("data").run())
    ok(app.selectbox(key="conn_api_pagination").set_value("page").run())
    ok(app.number_input(key="conn_api_page_size").set_value(3).run())
    ok(app.button(key="conn_api_preview").click().run())
    assert len(app.dataframe[-1].value) == 3
    ok(app.button(key="conn_api_fetch").click().run())
    assert any("Snapshot of /orders (3 page(s))" in c.value for c in app.caption)
    ok(app.button(key="import_save").click().run())
    assert any("Saved **orders** as dataset" in s.value for s in app.success)
    dataset = data_access.catalog().get("orders")
    assert dataset.source_type.value == "rest" and dataset.tables[0].row_count == 7
    assert API_TOKEN not in json.dumps(dataset.extra) and API_TOKEN not in everything_shown(app)


def test_api_errors_are_shown_safely(app, api):
    save_api(app, api)
    ok(app.text_input(key="conn_api_path").set_value("/redirect").run())
    ok(app.button(key="conn_api_preview").click().run())
    assert any("redirect" in e.value for e in app.error)
    app.text_area(key="conn_api_params").set_value("no equals sign")
    ok(app.run())
    assert any("name=value" in e.value for e in app.error)


def test_test_button_and_delete(app, api, monkeypatch):
    save_api(app, api)
    ok(app.button(key="conn_test").click().run())
    assert any("address is allowed" in s.value for s in app.success)
    monkeypatch.setenv("INSIGHTSQL_ALLOWED_PRIVATE_HOSTS", "")
    ok(app.button(key="conn_test").click().run())
    assert any("private or local network" in e.value for e in app.error)
    assert ConnectionStore(config.get_app_db_path()).get("shop_api").last_test_ok is False
    assert app.button(key="conn_delete").disabled
    ok(app.checkbox(key="conn_delete_ok_shop_api").check().run())
    ok(app.button(key="conn_delete").click().run())
    assert ConnectionStore(config.get_app_db_path()).list() == []
    assert app.selectbox(key="conn_edit_id").value == "__new__"


@pytest.mark.docker
def test_database_browse_and_import(app, db_servers, monkeypatch):  # noqa: F811
    server = db_servers["postgres"]
    monkeypatch.setenv("INSIGHTSQL_ALLOWED_PRIVATE_HOSTS", f"127.0.0.1:{server.port}")
    at = app
    at.text_input(key="conn_name___new__").set_value("Shop PG")
    at.text_input(key="conn_host___new__").set_value("127.0.0.1")
    at.number_input(key="conn_port___new__").set_value(server.port)
    at.text_input(key="conn_db___new__").set_value("shop")
    at.text_input(key="conn_user___new__").set_value("reader")
    ok(at.selectbox(key="conn_ssl___new__").set_value("disable").run())
    at.text_input(key="conn_secret___new__").set_value(READER_PASSWORD)
    ok(at.button(key="conn_save").click().run())
    ok(at.button(key="conn_test").click().run())
    assert any("Connected (read-only): PostgreSQL" in s.value for s in at.success)
    ok(at.button(key="conn_load_tables").click().run())
    ok(at.selectbox(key="conn_table").set_value(("shop", "orders")).run())
    assert any("photo" in c.value for c in at.caption)  # binary column skipped, and said so
    ok(at.button(key="conn_fetch").click().run())
    ok(at.button(key="import_save").click().run())
    dataset = data_access.catalog().get("shop_orders")
    assert dataset.source_type.value == "postgres" and dataset.tables[0].row_count == 3
    kinds = {c.name: c.data_type for c in dataset.tables[0].columns}
    assert kinds["amount"] == "REAL" and kinds["paid"] == "INTEGER" and "photo" not in kinds
    assert READER_PASSWORD not in everything_shown(at)
