"""PostgreSQL and MySQL connectors against real servers in Docker (each test runs on both)."""

import json
import logging

import pytest
from cryptography.fernet import Fernet

from src import config, data_access
from src.connectors import databases, snapshot
from src.connectors.profiles import ConnectionStore, ConnectorError
from src.ingest import store
from src.ingest.preprocess import CleanOptions, clean
from src.ingest.profiling import profile as profile_of
from src.ingest.readers import ReadOptions
from src.ingest.validation import validate
from src.query_service import answer_question
from tests.servers import ADMIN_PASSWORD, READER_PASSWORD, db_servers  # noqa: F401 (fixture)

pytestmark = pytest.mark.docker
KINDS = ["postgres", "mysql"]
SCHEMA = {"postgres": "shop", "mysql": "shop"}
ITEMS_SCHEMA = {"postgres": "public", "mysql": "shop"}
ADMIN = {"postgres": "postgres", "mysql": "root"}


@pytest.fixture
def env(monkeypatch, db_servers):  # noqa: F811
    monkeypatch.setenv("INSIGHTSQL_SECRET_KEY", Fernet.generate_key().decode())
    allowed = ",".join(f"127.0.0.1:{s.port}" for s in db_servers.values())
    monkeypatch.setenv("INSIGHTSQL_ALLOWED_PRIVATE_HOSTS", allowed)
    monkeypatch.setenv("INSIGHTSQL_CONNECTOR_TIMEOUT_SECONDS", "10")
    return db_servers


def connect(env, kind, username="reader", password=READER_PASSWORD, **overrides):
    profile = ConnectionStore(config.get_app_db_path()).save(
        f"{kind} {username}", kind, env[kind].settings(username, **overrides), password)
    return profile, ConnectionStore(config.get_app_db_path()).secret(profile.connection_id)


@pytest.mark.parametrize("kind", KINDS)
def test_connection_test_reports_a_read_only_session(env, kind):
    profile, password = connect(env, kind)
    version = databases.test(profile, password)
    assert ("PostgreSQL" in version) if kind == "postgres" else version.startswith("8.4")


@pytest.mark.parametrize("kind", KINDS)
def test_tables_are_listed_without_system_schemas(env, kind):
    profile, password = connect(env, kind)
    tables = databases.list_tables(profile, password)
    schema = SCHEMA[kind]
    assert (schema, "orders") in tables and (schema, "big_orders") in tables  # views too
    assert (ITEMS_SCHEMA[kind], "Order Items") in tables
    assert not any(s in databases.SYSTEM_SCHEMAS[kind] for s, _ in tables)


@pytest.mark.parametrize("kind", KINDS)
def test_column_types_are_mapped(env, kind):
    profile, password = connect(env, kind)
    kinds = {c.name: c.kind for c in databases.columns(profile, password, SCHEMA[kind], "orders")}
    assert kinds == {"order_id": "integer", "customer": "text", "amount": "float", "ordered_on": "date",
                     "created_at": "datetime", "paid": "boolean" if kind == "postgres" else "integer",
                     "note": "text", "photo": "unsupported"}


@pytest.mark.parametrize("kind", KINDS)
def test_preview_and_fetch_convert_values_to_text(env, kind):
    profile, password = connect(env, kind)
    frame = databases.preview(profile, password, SCHEMA[kind], "orders",
                              ["order_id", "customer", "amount", "ordered_on", "created_at", "paid", "note"])
    first = frame.iloc[0].tolist()
    created = "2025-01-05 04:30:00" if kind == "postgres" else "2025-01-05 10:00:00"  # +05:30 converted to UTC
    paid = "true" if kind == "postgres" else "1"
    assert first == ["1", "Zoë", "10.50", "2025-01-05", created, paid, '=HYPERLINK("x")']
    assert frame.iloc[2].tolist() == ["3", "", "", "", "", "", "plain"]  # NULL → empty


@pytest.mark.parametrize("kind", KINDS)
def test_names_that_need_quoting_work(env, kind):
    profile, password = connect(env, kind)
    frame, truncated = databases.fetch(profile, password, ITEMS_SCHEMA[kind], "Order Items", ["id", "qty"], 100)
    assert frame.values.tolist() == [["1", "5"], ["2", "7"]] and not truncated


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("table, columns", [
    ("orders; DROP TABLE orders", ["order_id"]),
    ("salaries", ["salary"]),  # exists, but the reader may not see it
    ("orders", ["order_id", "1; DROP TABLE orders"]),
    ("orders", ["photo"]),  # binary columns cannot be imported
    ("orders", []),
])
def test_only_listed_tables_and_columns_can_be_read(env, kind, table, columns):
    profile, password = connect(env, kind)
    with pytest.raises(ConnectorError):
        databases.fetch(profile, password, SCHEMA[kind] if table != "salaries" else ITEMS_SCHEMA[kind], table,
                        columns, 10)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("schema, table", [("information_schema", "tables"), ("information_schema", "columns")])
def test_system_tables_cannot_be_imported_even_when_readable(env, kind, schema, table):
    """The user can read these, but only tables in the listed (non-system) schemas may be imported."""
    profile, password = connect(env, kind)
    with pytest.raises(ConnectorError, match="not available on this connection"):
        databases.fetch(profile, password, schema, table, ["table_name"], 10)


@pytest.mark.parametrize("kind", KINDS)
def test_sessions_are_read_only_even_for_an_admin_account(env, kind):
    profile, password = connect(env, kind, username=ADMIN[kind], password=ADMIN_PASSWORD)
    databases.test(profile, password)
    with pytest.raises(ConnectorError, match="read-only|error"):
        with databases._connect(profile, password) as conn:  # simulate a bug that tries to write
            conn.exec_driver_sql("DELETE FROM shop.orders" if kind == "postgres" else "DELETE FROM orders")
    profile, password = connect(env, kind)
    assert len(databases.preview(profile, password, SCHEMA[kind], "orders", ["order_id"])) == 3  # unchanged


@pytest.mark.parametrize("kind", KINDS)
def test_wrong_password_is_reported_without_leaking(env, kind, caplog):
    caplog.set_level(logging.DEBUG)
    profile, _ = connect(env, kind)
    with pytest.raises(ConnectorError, match="rejected the user name or password") as exc:
        databases.test(profile, "wrong-pass-NOT-TO-LEAK")
    assert "wrong-pass-NOT-TO-LEAK" not in exc.value.message and "wrong-pass-NOT-TO-LEAK" not in caplog.text
    assert READER_PASSWORD not in caplog.text


@pytest.mark.parametrize("kind", KINDS)
def test_unknown_database_and_closed_port(env, kind):
    profile, password = connect(env, kind, username=ADMIN[kind], password=ADMIN_PASSWORD, database="nope")
    with pytest.raises(ConnectorError, match="does not exist|rejected"):
        databases.test(profile, password)


def test_closed_port_is_reported(env, monkeypatch):
    monkeypatch.setenv("INSIGHTSQL_ALLOWED_PRIVATE_HOSTS", "127.0.0.1:1")
    profile = ConnectionStore(config.get_app_db_path()).save(
        "closed", "postgres", {"host": "127.0.0.1", "port": 1, "database": "x", "username": "u", "ssl": "disable"}, "p")
    with pytest.raises(ConnectorError, match="Could not reach 127.0.0.1:1"):
        databases.test(profile, "p")


@pytest.mark.parametrize("kind", KINDS)
def test_local_server_is_refused_without_the_allow_list(env, kind, monkeypatch):
    profile, password = connect(env, kind)
    monkeypatch.setenv("INSIGHTSQL_ALLOWED_PRIVATE_HOSTS", "")
    with pytest.raises(ConnectorError, match="private or local network"):
        databases.test(profile, password)


@pytest.mark.parametrize("kind", KINDS)
def test_tables_above_the_row_limit_are_refused_not_cut(env, kind):
    profile, password = connect(env, kind)
    with pytest.raises(ConnectorError, match="more than 1,000 rows"):
        snapshot.from_database(profile, password, SCHEMA[kind], "many", ["n"], max_rows=1000)


@pytest.mark.parametrize("kind", KINDS)
def test_database_snapshot_imports_into_a_queryable_dataset(env, kind, seeded_db):
    profile, password = connect(env, kind)
    columns = ["order_id", "customer", "amount", "ordered_on", "created_at", "paid", "note"]
    snap = snapshot.from_database(profile, password, SCHEMA[kind], "orders", columns, max_rows=1000)
    options = CleanOptions(columns=snap.type_presets)
    result = clean(snap.raw, options)
    assert result.ok and {c.name: c.kind for c in result.columns} == {
        "order_id": "integer", "customer": "text", "amount": "float", "ordered_on": "date",
        "created_at": "datetime", "paid": "boolean" if kind == "postgres" else "integer", "note": "text"}
    dataset = store.save_import(
        name=f"{kind} orders", description="", raw=snap.raw, content=snap.content, read_options=ReadOptions(),
        clean_options=options, result=result, checks=validate(snap.raw, profile_of(snap.raw)),
        confirmed_destructive=True, catalog=data_access.catalog(), datasets_db=config.get_datasets_db_path(),
        uploads_dir=config.get_uploads_dir(), source=snap.source)
    assert dataset.source_type.value == kind
    source = dataset.extra["source"]
    assert (source["connection_id"], source["table"], source["columns"]) == (profile.connection_id, "orders", columns)
    assert READER_PASSWORD not in json.dumps(dataset.extra)
    target = data_access.target(dataset.dataset_id, seeded_db)
    answer = answer_question(seeded_db, "q", source="sql", target=target, generate_sql=lambda q: (
        f"SELECT COUNT(*), SUM(amount), MIN(ordered_on) FROM {dataset.dataset_id}"))
    assert answer.data.values.tolist() == [[3, 30.5, "2025-01-05"]]
