"""Full and incremental refresh against real PostgreSQL and MySQL servers (Docker)."""

import sqlite3
import uuid

import pytest
from cryptography.fernet import Fernet

from src import config, data_access
from src.connectors import snapshot
from src.connectors.profiles import ConnectionStore
from src.ingest import store
from src.ingest.preprocess import CleanOptions, clean
from src.ingest.profiling import profile as profile_of
from src.ingest.readers import ReadOptions
from src.ingest.validation import validate
from src.sync import refresh as sync
from src.sync.state import RefreshSettings
from tests.servers import READER_PASSWORD, _admin_connection, db_servers  # noqa: F401 (fixture)

pytestmark = pytest.mark.docker
KINDS = ["postgres", "mysql"]


@pytest.fixture(params=KINDS)
def source(request, db_servers, monkeypatch):  # noqa: F811
    """A fresh source table for one test: (server, table name, admin connection)."""
    kind = request.param
    server = db_servers[kind]
    monkeypatch.setenv("INSIGHTSQL_SECRET_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("INSIGHTSQL_ALLOWED_PRIVATE_HOSTS", f"127.0.0.1:{server.port}")
    monkeypatch.setenv("INSIGHTSQL_REFRESH_RETRY_SECONDS", "0")
    table = f"events_{uuid.uuid4().hex[:8]}"
    admin = _admin_connection(server)
    stamp = "timestamptz" if kind == "postgres" else "DATETIME"
    qualified = f"shop.{table}"
    execute(admin, f"CREATE TABLE {qualified} (id INTEGER PRIMARY KEY, label VARCHAR(20), amount DECIMAL(10, 2), "
                   f"updated_at {stamp})")
    execute(admin, f"INSERT INTO {qualified} VALUES (1, 'a', 1.00, '2025-01-01 10:00:00'), "
                   f"(2, 'b', 2.00, '2025-01-02 10:00:00'), (3, 'a', 3.00, '2025-01-03 10:00:00')")
    execute(admin, f"GRANT SELECT ON {qualified} TO reader" + ("" if kind == "postgres" else "@'%'"))
    yield server, table, admin
    execute(admin, f"DROP TABLE {qualified}")
    admin.close()


def execute(conn, sql):
    cursor = conn.cursor()
    cursor.execute(sql)


def import_table(server, table, options: CleanOptions | None = None):
    store_ = ConnectionStore(config.get_app_db_path())
    profile = store_.save(f"{server.kind} db", server.kind, server.settings(), READER_PASSWORD)
    snap = snapshot.from_database(profile, READER_PASSWORD, "shop", table, ["id", "label", "amount", "updated_at"], 1000)
    options = options or CleanOptions(columns=snap.type_presets)
    return store.save_import(
        name="Events", description="", raw=snap.raw, content=snap.content, read_options=ReadOptions(),
        clean_options=options, result=clean(snap.raw, options), checks=validate(snap.raw, profile_of(snap.raw)),
        confirmed_destructive=True, catalog=data_access.catalog(), datasets_db=config.get_datasets_db_path(),
        uploads_dir=config.get_uploads_dir(), source=snap.source)


def rows():
    conn = sqlite3.connect(config.get_datasets_db_path())
    try:
        return conn.execute("SELECT id, label, amount FROM events ORDER BY id").fetchall()
    finally:
        conn.close()


def incremental(dataset, key="id", cursor="updated_at"):
    return sync.save_settings(dataset, RefreshSettings(dataset.dataset_id, "incremental", key, cursor))


def test_incremental_refresh_inserts_new_and_replaces_changed_rows(source):
    server, table, admin = source
    dataset = import_table(server, table)
    incremental(dataset)
    first = sync.refresh("events")  # first incremental run: everything from the beginning
    assert first.status == "success" and (first.rows_inserted, first.rows_updated) == (0, 0)  # nothing changed
    execute(admin, f"INSERT INTO shop.{table} VALUES (4, 'new', 4.00, '2025-02-01 10:00:00')")
    execute(admin, f"UPDATE shop.{table} SET amount = 99.00, updated_at = '2025-02-02 10:00:00' WHERE id = 2")
    result = sync.refresh("events")
    assert result.status == "success"
    assert rows() == [(1, "a", 1.0), (2, "b", 99.0), (3, "a", 3.0), (4, "new", 4.0)]
    assert (result.rows_inserted, result.rows_updated, result.rows_total) == (1, 1, 4)
    assert sync.state().settings("events").last_cursor == "2025-02-02 10:00:00"


def test_incremental_refresh_twice_creates_no_duplicates(source):
    server, table, _ = source
    incremental(import_table(server, table))
    for _ in range(3):
        assert sync.refresh("events").status == "success"
    assert rows() == [(1, "a", 1.0), (2, "b", 2.0), (3, "a", 3.0)]
    last = sync.state().runs("events")[0]
    assert (last.rows_fetched, last.rows_inserted, last.rows_updated, last.rows_total) == (1, 0, 0, 3)  # the row
    # at the previous cursor value is fetched again (rows sharing that value are not missed) but is unchanged


def test_incremental_with_an_increasing_id(source):
    server, table, admin = source
    incremental(import_table(server, table), key="id", cursor="id")
    sync.refresh("events")
    execute(admin, f"INSERT INTO shop.{table} VALUES (5, 'later', 5.00, NULL)")
    result = sync.refresh("events")
    assert result.rows_inserted == 1 and rows()[-1] == (5, "later", 5.0)


def test_full_refresh_removes_rows_deleted_at_the_source(source):
    server, table, admin = source
    import_table(server, table)
    execute(admin, f"DELETE FROM shop.{table} WHERE id = 1")
    assert sync.refresh("events").status == "success"
    assert [r[0] for r in rows()] == [2, 3]


def test_incremental_needs_a_unique_key(source):
    server, table, _ = source
    dataset = import_table(server, table)
    with pytest.raises(sync.RefreshError, match="no repeats"):
        incremental(dataset, key="label")  # 'a' appears twice


def test_incremental_needs_row_by_row_cleaning(source):
    server, table, _ = source
    dataset = import_table(server, table, CleanOptions(remove_duplicate_rows=True))
    with pytest.raises(sync.RefreshError, match="row by row"):
        incremental(dataset)


def test_cursor_must_be_a_growing_type(source):
    server, table, _ = source
    with pytest.raises(sync.RefreshError, match="numbers, dates or times"):
        incremental(import_table(server, table), cursor="label")


def test_too_many_new_rows_fail_and_change_nothing(source, monkeypatch):
    server, table, admin = source
    incremental(import_table(server, table))
    sync.refresh("events")
    for i in range(10, 16):
        execute(admin, f"INSERT INTO shop.{table} VALUES ({i}, 'x', 1.00, '2025-03-01 10:00:00')")
    monkeypatch.setenv("INSIGHTSQL_IMPORT_MAX_ROWS", "3")
    result = sync.refresh("events")
    assert result.status == "failed" and "more than 3 new or changed rows" in result.message
    assert len(rows()) == 3


def test_schema_change_at_the_source_keeps_the_old_data(source):
    server, table, admin = source
    import_table(server, table)
    before = rows()
    execute(admin, f"ALTER TABLE shop.{table} DROP COLUMN label")
    result = sync.refresh("events")
    assert result.status == "failed" and "previous data is kept" in result.message
    assert rows() == before


def test_emptied_source_table_is_refused(source):
    server, table, admin = source
    import_table(server, table)
    before = rows()
    execute(admin, f"DELETE FROM shop.{table}")
    result = sync.refresh("events")
    assert result.status == "failed" and "previous data is kept" in result.message
    assert rows() == before
