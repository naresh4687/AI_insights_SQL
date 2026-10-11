"""Saving imports (src/ingest/store.py): all-or-nothing storage, integrity and isolation."""

import sqlite3
import time

import pytest

from src import config
from src.catalog import DEMO_DATASET_ID, CatalogError, DatasetCatalog
from src.core.models import QualityStatus, SourceType, Storage
from src.ingest import store
from src.ingest.preprocess import CleanOptions, ColumnOptions, clean
from src.ingest.profiling import profile
from src.ingest.readers import ImportFileError, Limits, ReadOptions, read_file
from src.ingest.validation import validate
from src.query_service import QueryError, run_query

LIMITS = Limits(max_bytes=50_000_000, max_rows=200_000, max_columns=50)
CSV = b"Order ID,Amount,Region\n1,10.5,East\n2,,West\n3,7,East\n"


@pytest.fixture
def paths(tmp_path):
    catalog = DatasetCatalog(config.get_app_db_path())
    catalog.ensure_builtin()
    return {"catalog": catalog, "datasets_db": config.get_datasets_db_path(), "uploads_dir": config.get_uploads_dir()}


def prepare(content: bytes = CSV, name: str = "orders.csv", options: CleanOptions | None = None,
            read_options: ReadOptions | None = None):
    read_options = read_options or ReadOptions()
    raw = read_file(name, content, read_options, LIMITS)
    checks = validate(raw, profile(raw))
    options = options or CleanOptions()
    return dict(raw=raw, content=content, read_options=read_options, clean_options=options,
                result=clean(raw, options), checks=checks)


def save(paths, name="Orders", confirmed=False, **prepared):
    prepared = prepared or prepare()
    return store.save_import(name=name, description="Test data", confirmed_destructive=confirmed, **prepared, **paths)


def table_rows(db, table):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
    finally:
        conn.close()


# --- Successful save ----------------------------------------------------------------

def test_save_stores_table_original_and_catalog_entry(paths):
    dataset = save(paths)
    assert dataset.dataset_id == "orders" and dataset.storage is Storage.DATASETS
    assert dataset.source_type is SourceType.CSV and dataset.quality_status is QualityStatus.WARNINGS
    assert table_rows(paths["datasets_db"], "orders") == [(1, 10.5, "East"), (2, None, "West"), (3, 7.0, "East")]
    original = paths["uploads_dir"] / "orders" / "original.csv"
    assert original.read_bytes() == CSV  # byte-for-byte
    stored = paths["catalog"].get("orders")
    assert stored.tables[0].row_count == 3 and [c.name for c in stored.tables[0].columns] == ["order_id", "amount",
                                                                                               "region"]
    extra = stored.extra
    assert extra["original_file"] == "orders.csv" and extra["stored_original"] == "orders/original.csv"
    assert len(extra["sha256"]) == 64 and extra["column_types"]["amount"] == "float"
    assert CleanOptions.from_dict(extra["clean_options"]) == CleanOptions()  # reproducible


def test_table_is_strict_with_declared_types(paths):
    save(paths, **prepare(options=CleanOptions(columns={0: ColumnOptions(required=True)})))
    conn = sqlite3.connect(paths["datasets_db"])
    try:
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'orders'").fetchone()[0]
        assert sql == 'CREATE TABLE "orders" ("order_id" INTEGER NOT NULL, "amount" REAL, "region" TEXT) STRICT'
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO orders VALUES ('not a number', 1.0, 'x')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO orders VALUES (NULL, 1.0, 'x')")
    finally:
        conn.close()


def test_excel_import_is_recorded_as_excel(paths):
    from tests.test_ingest_readers import workbook_bytes
    content = workbook_bytes({"Sheet A": [["x"], [1]], "Sheet B": [["y", "z"], ["a", 2]]})
    dataset = save(paths, name="Book", **prepare(content, "book.xlsx", read_options=ReadOptions(sheet="Sheet B")))
    assert dataset.source_type is SourceType.EXCEL and dataset.extra["sheet"] == "Sheet B"
    assert (paths["uploads_dir"] / "book" / "original.xlsx").read_bytes() == content
    assert table_rows(paths["datasets_db"], "book") == [("a", 2)]


def test_dataset_ids_never_collide(paths):
    first = save(paths, name="Sales")  # 'sales' is a demo table name
    second = save(paths, name="Sales 2024")
    third = save(paths, name="sales-2024")  # same id as the second
    assert first.dataset_id == "sales_2" and second.dataset_id == "sales_2024" and third.dataset_id == "sales_2024_2"


@pytest.mark.parametrize("name", ["products", "query_history", "demo_sales", "sqlite master"])
def test_reserved_names_get_other_ids(paths, name):
    dataset = save(paths, name=name)
    assert dataset.dataset_id not in {"products", "query_history", DEMO_DATASET_ID, "sqlite_master"}


def test_hostile_file_names_never_become_paths(paths):
    dataset = save(paths, name="Evil", **prepare(name="../../etc/passwd.csv"))
    files = [p.relative_to(paths["uploads_dir"]).as_posix() for p in paths["uploads_dir"].rglob("*") if p.is_file()]
    assert files == [f"{dataset.dataset_id}/original.csv"]
    assert dataset.extra["original_file"] == "../../etc/passwd.csv"  # kept only as metadata


# --- Refusals -----------------------------------------------------------------------

def test_destructive_changes_need_confirmation(paths):
    prepared = prepare(options=CleanOptions(columns={1: ColumnOptions(missing="drop_rows")}))
    with pytest.raises(ImportFileError, match="Confirm"):
        save(paths, **prepared)
    assert paths["catalog"].get("orders") is None and not paths["datasets_db"].exists()
    assert save(paths, confirmed=True, **prepared).tables[0].row_count == 2


@pytest.mark.parametrize("content", [b"a,b\n", b"a,b\n1,2,3\n"])
def test_validation_errors_block_saving(paths, content):
    with pytest.raises(ImportFileError, match="Fix the errors"):
        save(paths, **prepare(content))


def test_cleaning_errors_block_saving(paths):
    with pytest.raises(ImportFileError, match="Fix the errors"):
        save(paths, **prepare(options=CleanOptions(columns={1: ColumnOptions(required=True)})))


@pytest.mark.parametrize("name, message", [("", "Enter a name"), ("   ", "Enter a name"), ("x" * 81, "too long")])
def test_invalid_names(paths, name, message):
    with pytest.raises(ImportFileError, match=message):
        save(paths, name=name)


def test_duplicate_name_is_refused(paths):
    save(paths, name="Orders")
    with pytest.raises(ImportFileError, match="'Orders' already exists"):
        save(paths, name="  orders ")


# --- All or nothing -----------------------------------------------------------------

def test_catalog_failure_removes_table_and_original(paths, monkeypatch):
    def fail(*args, **kwargs):
        raise CatalogError("Catalog unavailable.")
    monkeypatch.setattr(paths["catalog"], "register", fail)
    with pytest.raises(ImportFileError, match="Catalog unavailable"):
        save(paths)
    assert "orders" not in store.existing_tables(paths["datasets_db"])
    assert not (paths["uploads_dir"] / "orders").exists()


def test_unexpected_catalog_error_also_rolls_back(paths, monkeypatch):
    monkeypatch.setattr(paths["catalog"], "register", lambda *a, **k: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        save(paths)
    assert "orders" not in store.existing_tables(paths["datasets_db"])
    assert not (paths["uploads_dir"] / "orders").exists()


def test_table_write_failure_leaves_nothing(paths, monkeypatch):
    prepared = prepare()
    frame = prepared["result"].frame
    frame["order_id"] = frame["order_id"].astype(object)
    frame.loc[1, "order_id"] = "text in an integer column"  # STRICT rejects it mid-insert
    with pytest.raises(ImportFileError, match="could not be saved"):
        save(paths, **prepared)
    assert "orders" not in store.existing_tables(paths["datasets_db"])
    assert not (paths["uploads_dir"] / "orders").exists() and paths["catalog"].get("orders") is None


def test_leftover_storage_is_never_overwritten(paths):
    (paths["uploads_dir"] / "orders").mkdir(parents=True)
    (paths["uploads_dir"] / "orders" / "keep.txt").write_text("existing")
    dataset = save(paths)
    assert dataset.dataset_id == "orders_2"
    assert (paths["uploads_dir"] / "orders" / "keep.txt").read_text() == "existing"
    assert (paths["uploads_dir"] / "orders_2" / "original.csv").read_bytes() == CSV


# --- Isolation from the demo data and the existing query path ------------------------

def test_demo_database_and_history_are_untouched(paths, seeded_db):
    before = seeded_db.read_bytes()
    save(paths)
    assert seeded_db.read_bytes() == before
    assert paths["datasets_db"] != seeded_db


def test_imported_table_is_not_reachable_with_the_default_scope(paths):
    save(paths)
    with pytest.raises(QueryError) as exc:
        run_query(paths["datasets_db"], "SELECT * FROM orders")
    assert exc.value.status == "rejected"


def test_imported_table_is_readable_only_with_its_own_scope(paths):
    save(paths, name="Orders")
    save(paths, name="Other")
    scope = paths["catalog"].scope("orders")
    assert run_query(paths["datasets_db"], "SELECT COUNT(*) FROM orders", allowed_tables=scope).data.iloc[0, 0] == 3
    with pytest.raises(QueryError):
        run_query(paths["datasets_db"], "SELECT * FROM other", allowed_tables=scope)


# --- Large input --------------------------------------------------------------------

def test_large_file_imports_within_limits(paths):
    rows = 100_000
    lines = ["id,region,amount,day"] + [f"{i},R{i % 7},{i % 1000}.25,2025-01-{i % 28 + 1:02d}" for i in range(rows)]
    content = ("\n".join(lines) + "\n").encode()
    start = time.perf_counter()
    dataset = save(paths, name="Big", **prepare(content, "big.csv"))
    elapsed = time.perf_counter() - start
    assert dataset.tables[0].row_count == rows
    assert table_rows(paths["datasets_db"], "big")[-1] == (rows - 1, "R4", 999.25, "2025-01-12")
    assert elapsed < 60, f"import took {elapsed:.1f} s"
