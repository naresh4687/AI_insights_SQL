"""Refreshing datasets imported from connections: full, failures, locks, retries, schedule, worker.

Uses the fake REST API (no Docker). Incremental refresh against real databases is in
test_refresh_databases.py.
"""

import hashlib
import sqlite3
from datetime import timedelta

import pytest
from cryptography.fernet import Fernet

from src import config, data_access
from src.connectors import rest, snapshot
from src.connectors.profiles import ConnectionStore
from src.core.models import RefreshStatus
from src.ingest import store
from src.ingest.preprocess import CleanOptions, ColumnOptions, clean
from src.ingest.profiling import profile as profile_of
from src.ingest.readers import ReadOptions
from src.ingest.validation import validate
from src.query_service import answer_question
from src.sync import refresh as sync
from src.sync.state import RefreshSettings, utc, now
from tests.servers import API_TOKEN, running_fake_api


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("INSIGHTSQL_SECRET_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("INSIGHTSQL_REFRESH_RETRY_SECONDS", "0")
    monkeypatch.setenv("INSIGHTSQL_CONNECTOR_TIMEOUT_SECONDS", "2")
    with running_fake_api() as fake:
        monkeypatch.setenv("INSIGHTSQL_ALLOWED_PRIVATE_HOSTS", f"127.0.0.1:{fake.port}")
        yield fake


def import_api(api, options: CleanOptions | None = None, path="/orders"):
    profile = ConnectionStore(config.get_app_db_path()).save(
        "API", "rest", {"base_url": api.base_url, "auth": "bearer"}, API_TOKEN)
    snap = snapshot.from_api(profile, API_TOKEN, rest.Endpoint(path, records_path="data"), 1000, 50)
    options = options or CleanOptions()
    return store.save_import(
        name="Orders", description="", raw=snap.raw, content=snap.content, read_options=ReadOptions(),
        clean_options=options, result=clean(snap.raw, options), checks=validate(snap.raw, profile_of(snap.raw)),
        confirmed_destructive=True, catalog=data_access.catalog(), datasets_db=config.get_datasets_db_path(),
        uploads_dir=config.get_uploads_dir(), source=snap.source)


def rows(sql="SELECT id, amount FROM orders ORDER BY id"):
    conn = sqlite3.connect(config.get_datasets_db_path())
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def fingerprint() -> str:
    return hashlib.sha256(str(rows("SELECT * FROM orders ORDER BY id")).encode()).hexdigest()


# --- Full refresh -----------------------------------------------------------------------

def test_full_refresh_replaces_the_data_and_updates_metadata(api):
    import_api(api)
    api.orders[0]["amount"] = 999.5
    api.orders.append({**api.orders[1], "id": 8})
    result = sync.refresh("orders")
    assert (result.status, result.rows_fetched, result.rows_total) == ("success", 8, 8)
    assert rows()[0] == (1, 999.5) and len(rows()) == 8
    dataset = data_access.catalog().get("orders")
    assert dataset.tables[0].row_count == 8 and dataset.refresh_status is RefreshStatus.OK
    assert dataset.last_refresh_at and dataset.extra["last_refresh"]["total"] == 8
    run = sync.state().runs("orders")[0]
    assert (run.status, run.trigger, run.mode, run.rows_total, run.attempts) == ("success", "manual", "full", 8, 1)
    folder = config.get_uploads_dir() / "orders"
    assert (folder / "latest.json").exists() and (folder / "original.json").exists()  # original kept as imported


def test_refreshed_data_is_what_questions_see(api, seeded_db):
    import_api(api)
    api.orders[:] = api.orders[:2]
    sync.refresh("orders")
    target = data_access.target("orders", seeded_db)
    answer = answer_question(seeded_db, "n", source="sql", target=target, generate_sql=lambda q: "SELECT COUNT(*) FROM orders")
    assert answer.data.iloc[0, 0] == 2


def test_repeated_refreshes_do_not_duplicate_rows(api):
    import_api(api)
    for _ in range(3):
        assert sync.refresh("orders").status == "success"
    assert len(rows()) == 7 and len(sync.state().runs("orders")) == 3


# --- The last good data is kept on every kind of failure ----------------------------------

@pytest.mark.parametrize("break_it, message", [
    (lambda api: api.orders.clear(), "returned no records"),
    (lambda api: [o.pop("amount") for o in api.orders], "Fields are missing"),  # structure changed
    (lambda api: [o.update(amount="lots") for o in api.orders], "columns or types have changed"),
])
def test_bad_new_data_never_replaces_the_good_data(api, break_it, message):
    import_api(api)
    before = fingerprint()
    break_it(api)
    result = sync.refresh("orders")
    assert result.status == "failed" and message in result.message and "previous data is kept" in result.message
    assert fingerprint() == before
    dataset = data_access.catalog().get("orders")
    assert dataset.refresh_status is RefreshStatus.FAILED and dataset.tables[0].row_count == 7
    assert sync.state().runs("orders")[0].status == "failed"


def test_cleaning_rules_still_apply(api):
    import_api(api, CleanOptions(columns={4: ColumnOptions(required=True, missing="fill_value", fill_value="-")}))
    api.orders[0]["note"] = None
    assert sync.refresh("orders").status == "success"
    assert rows("SELECT note FROM orders WHERE id = 1") == [("-",)]


def test_new_source_fields_are_reported_not_hidden(api):
    import_api(api)
    for order in api.orders:
        order["discount"] = 1
    result = sync.refresh("orders")
    assert result.status == "success" and "New source fields not in this dataset were not imported: discount" in result.message


def test_failure_in_the_middle_of_the_swap_keeps_the_old_table(api, monkeypatch):
    import_api(api)
    before = fingerprint()
    api.orders[0]["amount"] = 1.0
    original = store._insert

    def fail_after_insert(conn, table, result):
        original(conn, table, result)
        raise sqlite3.OperationalError("disk I/O error")  # after the staging table is filled
    monkeypatch.setattr(store, "_insert", fail_after_insert)
    result = sync.refresh("orders")
    assert result.status == "failed" and "previous data is kept" in result.message
    assert fingerprint() == before
    assert rows("SELECT name FROM sqlite_master WHERE name LIKE '%refresh%'") == []  # no staging table left


def test_deleted_connection_is_explained(api):
    import_api(api)
    ConnectionStore(config.get_app_db_path()).delete("api")
    result = sync.refresh("orders")
    assert result.status == "failed" and "connection this dataset came from was deleted" in result.message


def test_file_imports_cannot_be_refreshed(api, seeded_db):
    from tests.test_dataset_integration import ORDERS_CSV, import_csv
    import_csv("File orders", ORDERS_CSV)
    assert sync.refresh("file_orders").status == "skipped"
    with pytest.raises(sync.RefreshError, match="Only datasets imported from a connection"):
        sync.check_settings(data_access.catalog().get("file_orders"), RefreshSettings("file_orders"))


# --- Retries and locks ----------------------------------------------------------------------

def test_temporary_failures_are_retried_with_growing_waits(api, monkeypatch):
    import_api(api)
    monkeypatch.setenv("INSIGHTSQL_REFRESH_RETRY_SECONDS", "5")
    calls = {"n": 0}
    original = rest.fetch

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise rest.ConnectorError("The API did not answer in time.", retryable=True)
        return original(*args, **kwargs)
    monkeypatch.setattr(rest, "fetch", flaky)
    waits = []
    result = sync.refresh("orders", sleep=waits.append)
    assert result.status == "success" and waits == [5.0, 10.0]
    assert sync.state().runs("orders")[0].attempts == 3


def test_permanent_failures_are_not_retried(api, monkeypatch):
    import_api(api)
    monkeypatch.setattr(rest, "fetch", lambda *a, **k: (_ for _ in ()).throw(
        rest.ConnectorError("The API rejected the credentials (or they lack permission).")))
    waits = []
    result = sync.refresh("orders", sleep=waits.append)
    assert result.status == "failed" and waits == [] and sync.state().runs("orders")[0].attempts == 1


def test_retries_stop_at_the_limit(api, monkeypatch):
    import_api(api)
    monkeypatch.setenv("INSIGHTSQL_REFRESH_MAX_ATTEMPTS", "2")
    monkeypatch.setattr(rest, "fetch", lambda *a, **k: (_ for _ in ()).throw(
        rest.ConnectorError("The API is rate limiting requests. Try again later.", retryable=True)))
    result = sync.refresh("orders", sleep=lambda s: None)
    assert result.status == "failed" and sync.state().runs("orders")[0].attempts == 2


def test_one_refresh_at_a_time(api):
    import_api(api)
    state = sync.state()
    assert state.acquire("orders", "someone-else")
    result = sync.refresh("orders")
    assert result.status == "skipped" and "Another refresh" in result.message
    state.release("orders", "someone-else")
    assert sync.refresh("orders").status == "success"


def test_a_crashed_runs_lock_expires(api):
    import_api(api)
    state = sync.state()
    conn = sqlite3.connect(config.get_app_db_path())
    with conn:
        conn.execute("INSERT INTO refresh_locks VALUES ('orders', 'crashed', ?)", (utc(now() - timedelta(hours=1)),))
    conn.close()
    assert sync.refresh("orders").status == "success"


def test_unexpected_errors_close_the_run_and_release_the_lock(api, monkeypatch):
    import_api(api)
    monkeypatch.setattr(sync, "_attempt", lambda *a: 1 / 0)
    result = sync.refresh("orders")
    assert result.status == "failed" and "unexpectedly" in result.message
    assert sync.state().acquire("orders", "next")  # the lock was released


# --- Settings and schedule ------------------------------------------------------------------

def test_api_datasets_allow_full_refresh_only(api):
    dataset = import_api(api)
    with pytest.raises(sync.RefreshError, match="database tables only"):
        sync.check_settings(dataset, RefreshSettings("orders", "incremental", "id", "id"))


@pytest.mark.parametrize("settings, message", [
    (RefreshSettings("orders", interval_minutes=2), "at least every 5 minutes"),
    (RefreshSettings("orders", enabled=True), "how often"),
    (RefreshSettings("orders", mode="sometimes"), "full or incremental"),
])
def test_invalid_settings(api, settings, message):
    dataset = import_api(api)
    with pytest.raises(sync.RefreshError, match=message):
        sync.check_settings(dataset, settings)


def test_schedule_due_and_next_run(api):
    dataset = import_api(api)
    state = sync.state()
    saved = sync.save_settings(dataset, RefreshSettings("orders", interval_minutes=60, enabled=True))
    assert saved.next_run_at and state.due() == []
    assert state.due(at=now() + timedelta(minutes=61)) == ["orders"]
    sync.save_settings(dataset, RefreshSettings("orders", interval_minutes=60, enabled=False))
    assert state.due(at=now() + timedelta(days=1)) == []


def test_worker_runs_due_refreshes_and_reschedules(api, capsys):
    from scripts import refresh_worker
    dataset = import_api(api)
    sync.save_settings(dataset, RefreshSettings("orders", interval_minutes=30, enabled=True))
    conn = sqlite3.connect(config.get_app_db_path())
    with conn:
        conn.execute("UPDATE refresh_settings SET next_run_at = ?", (utc(now() - timedelta(minutes=1)),))
    conn.close()
    api.orders[0]["amount"] = 42.0
    assert refresh_worker.main(["--once"]) == 0
    assert "orders: success" in capsys.readouterr().out
    assert rows()[0] == (1, 42.0)
    run = sync.state().runs("orders")[0]
    assert run.trigger == "scheduled"
    next_run = sync.state().settings("orders").next_run_at
    assert next_run > utc(now() + timedelta(minutes=29))  # from now, so missed runs do not pile up
    assert refresh_worker.main(["--once"]) == 0 and "No refresh is due." in capsys.readouterr().out


def test_worker_exit_code_reports_failures(api, capsys):
    from scripts import refresh_worker
    dataset = import_api(api)
    sync.save_settings(dataset, RefreshSettings("orders", interval_minutes=30, enabled=True))
    conn = sqlite3.connect(config.get_app_db_path())
    with conn:
        conn.execute("UPDATE refresh_settings SET next_run_at = ?", (utc(now() - timedelta(minutes=1)),))
    conn.close()
    api.orders.clear()
    assert refresh_worker.main(["--once"]) == 1
    assert "orders: failed" in capsys.readouterr().out


def test_disabled_schedule_is_never_due_even_with_a_leftover_time(api):
    dataset = import_api(api)
    sync.save_settings(dataset, RefreshSettings("orders", interval_minutes=30, enabled=True))
    conn = sqlite3.connect(config.get_app_db_path())
    with conn:
        conn.execute("UPDATE refresh_settings SET enabled = 0, next_run_at = ?", (utc(now() - timedelta(hours=1)),))
    conn.close()
    assert sync.state().due() == []
