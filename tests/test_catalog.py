"""Dataset catalog, its models, and the app metadata database migrations."""

import sqlite3

import pytest

from src import config, database
from src.catalog import DEMO_DATASET_ID, CatalogError, DatasetCatalog, demo_dataset
from src.core.models import (
    ColumnInfo, Dataset, QualityStatus, RefreshStatus, SourceType, Storage, TableInfo,
)
from src.query_service import run_query
from src.storage import app_db


def _dataset(dataset_id="orders_2025", name="Orders 2025", table="orders_2025") -> Dataset:
    return Dataset(
        dataset_id=dataset_id, name=name, source_type=SourceType.CSV, storage=Storage.DATASETS,
        tables=(TableInfo(table, (ColumnInfo("order_id", "INTEGER", False), ColumnInfo("amount", "REAL")),
                          row_count=2),),
        extra={"file_name": "orders.csv"},
    )


@pytest.fixture
def catalog(tmp_path):
    return DatasetCatalog(tmp_path / "app.db")


# --- Models -----------------------------------------------------------------------

@pytest.mark.parametrize("bad_id", ["", "Orders", "1orders", "orders-2025", "orders;drop", "a" * 64])
def test_invalid_dataset_ids_are_refused(bad_id):
    with pytest.raises(ValueError):
        _dataset(dataset_id=bad_id)


@pytest.mark.parametrize("bad_table", ["", "Orders", "orders 2025", 'x"y', "sqlite_master;"])
def test_invalid_table_names_are_refused(bad_table):
    with pytest.raises(ValueError):
        _dataset(table=bad_table)


def test_dataset_needs_name_tables_and_columns():
    with pytest.raises(ValueError):
        _dataset(name="  ")
    with pytest.raises(ValueError):
        Dataset("x", "X", SourceType.CSV, Storage.DATASETS, tables=())
    with pytest.raises(ValueError):
        TableInfo("t", columns=())
    table = TableInfo("t", (ColumnInfo("a", "TEXT"),))
    with pytest.raises(ValueError):
        Dataset("x", "X", SourceType.CSV, Storage.DATASETS, tables=(table, table))


def test_table_names_is_the_query_scope():
    assert _dataset().table_names == frozenset({"orders_2025"})


# --- Demo dataset -----------------------------------------------------------------

def test_demo_dataset_matches_the_real_schema(seeded_db):
    demo = demo_dataset()
    assert demo.dataset_id == DEMO_DATASET_ID and demo.builtin and demo.storage is Storage.DEMO
    conn = sqlite3.connect(seeded_db)
    try:
        for table in demo.tables:
            real = [(r[1], r[2], not r[3] and not r[5]) for r in conn.execute(f"PRAGMA table_info({table.name})")]
            assert [(c.name, c.data_type, c.nullable) for c in table.columns] == real
    finally:
        conn.close()


def test_demo_dataset_scope_equals_the_guard_default_and_excludes_history():
    assert demo_dataset().table_names == frozenset({"products", "sales"})
    assert "query_history" not in demo_dataset().table_names


def test_demo_scope_from_catalog_runs_demo_queries(catalog, seeded_db):
    catalog.ensure_builtin()
    result = run_query(seeded_db, "SELECT COUNT(*) FROM sales", allowed_tables=catalog.scope(DEMO_DATASET_ID))
    assert result.data.iloc[0, 0] == 600


# --- Catalog ----------------------------------------------------------------------

def test_register_get_and_list_round_trip(catalog):
    catalog.ensure_builtin()
    saved = catalog.register(_dataset())
    loaded = catalog.get("orders_2025")
    assert loaded == saved
    assert loaded.extra == {"file_name": "orders.csv"}
    assert loaded.tables[0].row_count == 2 and loaded.tables[0].columns[0].nullable is False
    assert loaded.created_at and loaded.updated_at
    assert [d.dataset_id for d in catalog.list()] == [DEMO_DATASET_ID, "orders_2025"]


def test_unknown_dataset_has_no_scope(catalog):
    assert catalog.get("missing") is None
    with pytest.raises(CatalogError, match="not registered"):
        catalog.scope("missing")


def test_duplicate_id_or_name_is_refused(catalog):
    catalog.register(_dataset())
    with pytest.raises(CatalogError, match="id"):
        catalog.register(_dataset(name="Another name"))
    with pytest.raises(CatalogError, match="named"):
        catalog.register(_dataset(dataset_id="other_id"))
    assert len(catalog.list()) == 1  # nothing partial was written


def test_builtin_dataset_cannot_be_registered_replaced_or_removed(catalog):
    catalog.ensure_builtin()
    with pytest.raises(CatalogError):
        catalog.register(demo_dataset())
    fake = Dataset("my_demo", "Mine", SourceType.CSV, Storage.DATASETS, demo_dataset().tables, builtin=True)
    with pytest.raises(CatalogError):
        catalog.register(fake)
    with pytest.raises(CatalogError, match="cannot be removed"):
        catalog.remove(DEMO_DATASET_ID)
    assert catalog.get(DEMO_DATASET_ID) is not None


def test_ensure_builtin_is_idempotent(catalog):
    first = catalog.ensure_builtin()
    second = catalog.ensure_builtin()
    assert first == second
    assert [d.dataset_id for d in catalog.list()] == [DEMO_DATASET_ID]


def test_remove_deletes_dataset_and_its_tables(catalog):
    catalog.register(_dataset())
    catalog.remove("orders_2025")
    assert catalog.get("orders_2025") is None
    conn = app_db.connect(catalog.db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM dataset_tables").fetchone()[0] == 0
    finally:
        conn.close()


def test_update_status(catalog):
    catalog.register(_dataset())
    updated = catalog.update_status("orders_2025", quality_status=QualityStatus.WARNINGS,
                                    refresh_status=RefreshStatus.OK, last_refresh_at="2026-10-11T00:00:00+00:00")
    assert catalog.get("orders_2025") == updated
    assert (updated.quality_status, updated.refresh_status) == (QualityStatus.WARNINGS, RefreshStatus.OK)
    with pytest.raises(CatalogError):
        catalog.update_status("missing", refresh_status=RefreshStatus.OK)


def test_catalog_persists_across_instances(tmp_path):
    DatasetCatalog(tmp_path / "app.db").register(_dataset())
    assert DatasetCatalog(tmp_path / "app.db").get("orders_2025") is not None


def test_catalog_does_not_touch_the_demo_database(tmp_path, seeded_db):
    before = seeded_db.read_bytes()
    catalog = DatasetCatalog(tmp_path / "app.db")
    catalog.ensure_builtin()
    catalog.register(_dataset())
    assert seeded_db.read_bytes() == before
    assert catalog.db_path != seeded_db


# --- Migrations -------------------------------------------------------------------

def test_migrate_creates_schema_and_is_idempotent(tmp_path):
    path = tmp_path / "nested" / "app.db"
    assert app_db.migrate(path) == len(app_db.MIGRATIONS)
    assert app_db.migrate(path) == len(app_db.MIGRATIONS)
    conn = app_db.connect(path)
    try:
        rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
        assert [r[0] for r in rows] == list(range(1, len(app_db.MIGRATIONS) + 1))
    finally:
        conn.close()


def test_failed_migration_is_rolled_back_completely(tmp_path):
    path = tmp_path / "app.db"
    app_db.migrate(path)
    nxt = len(app_db.MIGRATIONS) + 1  # the next migration number, whatever exists today
    broken = app_db.MIGRATIONS + ((nxt, "broken", "CREATE TABLE new_one (a INTEGER); SELECT * FROM missing_table"),)
    with pytest.raises(app_db.MigrationError, match=f"Migration {nxt}"):
        app_db.migrate(path, broken)
    conn = app_db.connect(path)
    try:
        assert app_db.current_version(conn) == nxt - 1
        assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'new_one'").fetchone() is None
    finally:
        conn.close()


def test_newer_database_is_refused_not_modified(tmp_path):
    path = tmp_path / "app.db"
    newer = app_db.MIGRATIONS + ((len(app_db.MIGRATIONS) + 1, "future", "CREATE TABLE future (a INTEGER)"),)
    app_db.migrate(path, newer)
    before = path.read_bytes()
    with pytest.raises(app_db.MigrationError, match="newer"):
        app_db.migrate(path)
    assert path.read_bytes() == before


def test_migrations_must_be_numbered_without_gaps(tmp_path):
    with pytest.raises(app_db.MigrationError):
        app_db.migrate(tmp_path / "app.db", ((1, "a", "SELECT 1"), (3, "c", "SELECT 1")))


# --- Configuration ----------------------------------------------------------------

def test_storage_paths_default_to_data_folder(monkeypatch):
    monkeypatch.delenv("INSIGHTSQL_APP_DB_PATH")
    monkeypatch.delenv("INSIGHTSQL_DATASETS_DB_PATH")
    assert config.get_app_db_path() == config.PROJECT_ROOT / "data" / "app.db"
    assert config.get_datasets_db_path() == config.PROJECT_ROOT / "data" / "datasets.db"


def test_storage_paths_are_separate_from_the_demo_database(monkeypatch):
    monkeypatch.delenv("INSIGHTSQL_APP_DB_PATH")
    monkeypatch.delenv("INSIGHTSQL_DATASETS_DB_PATH")
    monkeypatch.delenv("INSIGHTSQL_DB_PATH", raising=False)
    paths = {config.get_db_path(), config.get_app_db_path(), config.get_datasets_db_path()}
    assert len(paths) == 3


def test_tests_use_isolated_storage(tmp_path):
    assert config.get_app_db_path() == tmp_path / "app.db"
    assert config.get_datasets_db_path() == tmp_path / "datasets.db"


def test_reseeding_demo_data_leaves_the_catalog_intact(tmp_path):
    catalog = DatasetCatalog(config.get_app_db_path())
    catalog.register(_dataset())
    database.seed_sample_data(tmp_path / "demo.db")
    database.seed_sample_data(tmp_path / "demo.db")
    assert catalog.get("orders_2025") is not None


def test_existing_version_1_database_upgrades_without_losing_datasets(tmp_path):
    """An app.db created before connections existed keeps every dataset after the upgrade."""
    path = tmp_path / "app.db"
    app_db.migrate(path, app_db.MIGRATIONS[:1])
    conn = app_db.connect(path)
    try:
        with conn:
            conn.execute("INSERT INTO datasets (dataset_id, name, source_type, storage, quality_status, refresh_status, "
                         "created_at, updated_at) VALUES ('old', 'Old', 'csv', 'datasets', 'passed', 'never', 'x', 'x')")
            conn.execute("INSERT INTO dataset_tables VALUES ('old', 'old', 0, '[{\"name\": \"a\", \"data_type\": "
                         "\"TEXT\", \"nullable\": true}]', 3)")
    finally:
        conn.close()
    assert app_db.migrate(path) == len(app_db.MIGRATIONS)
    old = DatasetCatalog(path).get("old")
    assert old is not None and old.tables[0].row_count == 3
    conn = app_db.connect(path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM connections").fetchone()[0] == 0
    finally:
        conn.close()
