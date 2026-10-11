"""Save an approved import: the original file, the cleaned table, and its catalog entry.

All or nothing: if any part fails, the parts already written are removed again.
- The original upload is kept byte-for-byte in ``<uploads>/<dataset_id>/original.<ext>``
  (the user's file name is stored as metadata only, never used as a path).
- The cleaned table goes into the datasets database (never the demo database) as a STRICT
  table named after the dataset id, so SQLite itself enforces the column types.
- The dataset is registered in the catalog with how it was read and cleaned (no data).
"""

import hashlib
import os
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path, PurePath

import pandas as pd

from src import catalog as catalog_module
from src.catalog import CatalogError, DatasetCatalog
from src.core.models import ColumnInfo, Dataset, IDENTIFIER, QualityStatus, SourceType, Storage, TableInfo
from src.ingest.preprocess import CleanOptions, CleanResult, normalize_name
from src.ingest.readers import ImportFileError, RawTable, ReadOptions
from src.ingest.validation import Check, has_errors, summary
from src.sql_guard import ALLOWED_TABLES

RESERVED_IDS = ALLOWED_TABLES | {"query_history", "schema_migrations", catalog_module.DEMO_DATASET_ID}
MAX_NAME_LENGTH = 80
INSERT_BATCH = 5_000


def connect_datasets(db_path: Path) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(db_path)


def existing_tables(db_path: Path) -> set[str]:
    if not Path(db_path).exists():
        return set()
    conn = sqlite3.connect(f"{Path(db_path).resolve().as_uri()}?mode=ro", uri=True)
    try:
        return {row[0].lower() for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        conn.close()


def suggest_dataset_id(name: str, catalog: DatasetCatalog, datasets_db: Path, uploads_dir: Path) -> str:
    """A free, valid dataset id (also the table name) derived from ``name``. Ids already used
    by a dataset, a table or a storage folder (e.g. left over from a crash) are skipped."""
    base = normalize_name(name, 0).rstrip("_")[:50] or "dataset"
    if not IDENTIFIER.match(base) or base.startswith("sqlite_"):
        base = f"ds_{base}"[:50]
    folders = {p.name for p in Path(uploads_dir).iterdir()} if Path(uploads_dir).is_dir() else set()
    taken = RESERVED_IDS | {d.dataset_id for d in catalog.list()} | existing_tables(datasets_db) | folders
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}_{n}", n + 1
    return candidate


def _python_value(value):
    """pandas missing values → None; numpy scalars → Python numbers, for sqlite3."""
    if value is None or value is pd.NA or (isinstance(value, float) and value != value):
        return None
    return value.item() if hasattr(value, "item") else value


def save_import(
    *,
    name: str,
    description: str,
    raw: RawTable,
    content: bytes,
    read_options: ReadOptions,
    clean_options: CleanOptions,
    result: CleanResult,
    checks: list[Check],
    confirmed_destructive: bool,
    catalog: DatasetCatalog,
    datasets_db: Path,
    uploads_dir: Path,
    source: dict | None = None,
    owner: str | None = None,
) -> Dataset:
    """Store the import and register it, owned by ``owner`` (an accounts user_id; None for the
    system). Raises ``ImportFileError`` with a user-safe message."""
    name = re.sub(r"\s+", " ", name or "").strip()
    if not name:
        raise ImportFileError("Enter a name for the dataset.")
    if len(name) > MAX_NAME_LENGTH:
        raise ImportFileError(f"The dataset name is too long (limit {MAX_NAME_LENGTH} characters).")
    if has_errors(checks) or not result.ok:
        raise ImportFileError("Fix the errors listed above before saving.")
    if result.destructive_steps and not confirmed_destructive:
        raise ImportFileError("Confirm the changes that remove or replace data before saving.")
    clash = next((d for d in catalog.list() if d.name.lower() == name.lower()), None)
    if clash:
        raise ImportFileError(f"A dataset named '{clash.name}' already exists. Choose another name.")

    dataset_id = suggest_dataset_id(name, catalog, datasets_db, uploads_dir)
    original = _save_original(uploads_dir, dataset_id, raw.file_name, content)
    try:
        _write_table(datasets_db, dataset_id, result)
        try:
            return catalog.register(_dataset(dataset_id, name, description, raw, content, original, uploads_dir,
                                             read_options, clean_options, result, checks, source, owner))
        except CatalogError as exc:
            _drop_table(datasets_db, dataset_id)
            raise ImportFileError(exc.message) from None
        except Exception:
            _drop_table(datasets_db, dataset_id)
            raise
    except Exception:
        shutil.rmtree(original.parent, ignore_errors=True)
        raise


def _save_original(uploads_dir: Path, dataset_id: str, file_name: str, content: bytes) -> Path:
    folder = Path(uploads_dir) / dataset_id
    if folder.exists():
        raise ImportFileError("Storage for this dataset already exists. Choose another name.")
    folder.mkdir(parents=True)
    suffix = PurePath(file_name).suffix.lower()
    target = folder / ("original" + (suffix if re.fullmatch(r"\.[a-z0-9]{1,5}", suffix) else ""))
    temporary = folder / ".upload.tmp"
    temporary.write_bytes(content)
    os.replace(temporary, target)  # never leaves a half-written original behind
    return target


def _create_and_fill(conn: sqlite3.Connection, table: str, result: CleanResult) -> None:
    """CREATE a STRICT table for ``result`` and insert its rows (inside the caller's transaction)."""
    column_sql = ", ".join(
        f'"{c.name}" {c.sql_type}{" NOT NULL" if c.required else ""}' for c in result.columns
    )
    conn.execute(f'CREATE TABLE "{table}" ({column_sql}) STRICT')
    _insert(conn, table, result)


def _insert(conn: sqlite3.Connection, table: str, result: CleanResult) -> None:
    placeholders = ", ".join("?" for _ in result.columns)
    rows = ([_python_value(v) for v in row] for row in result.frame.itertuples(index=False, name=None))
    batch = []
    for row in rows:
        batch.append(row)
        if len(batch) >= INSERT_BATCH:
            conn.executemany(f'INSERT INTO "{table}" VALUES ({placeholders})', batch)
            batch = []
    if batch:
        conn.executemany(f'INSERT INTO "{table}" VALUES ({placeholders})', batch)


def _transaction(db_path: Path):
    """A connection in explicit-transaction mode: in sqlite3's default mode CREATE/DROP/ALTER
    would commit on their own, breaking all-or-nothing writes."""
    conn = connect_datasets(db_path)
    conn.isolation_level = None
    conn.execute("BEGIN IMMEDIATE")
    return conn


def _write_table(db_path: Path, table: str, result: CleanResult) -> None:
    if not IDENTIFIER.match(table) or table in RESERVED_IDS:
        raise ImportFileError("The dataset name cannot be used.")
    try:
        conn = _transaction(db_path)
    except sqlite3.Error:
        raise ImportFileError("The cleaned data could not be saved.") from None
    try:
        try:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE lower(name) = ?", (table,)).fetchone():
                raise ImportFileError("A table with this name already exists. Choose another name.")
            _create_and_fill(conn, table, result)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    except sqlite3.Error:
        raise ImportFileError("The cleaned data could not be saved.") from None
    finally:
        conn.close()


def swap_table(db_path: Path, table: str, result: CleanResult) -> None:
    """Replace ``table`` with ``result`` atomically: the new rows go into a staging table, then the
    old table is dropped and the staging table renamed, all in one transaction. Readers see either
    the old or the new data; on any failure the old table is unchanged."""
    staging = f"{table}__refresh"
    conn = _transaction(db_path)
    try:
        conn.execute(f'DROP TABLE IF EXISTS "{staging}"')
        _create_and_fill(conn, staging, result)
        conn.execute(f'DROP TABLE "{table}"')
        conn.execute(f'ALTER TABLE "{staging}" RENAME TO "{table}"')
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def upsert_rows(db_path: Path, table: str, result: CleanResult, key: str) -> tuple[int, int]:
    """Insert new rows and replace existing ones, matched by the unique ``key`` column, in one
    transaction. Returns (inserted, changed): rows fetched again with identical values are not
    counted as changed. Fails (changing nothing) if keys would repeat."""
    keys = [_python_value(v) for v in result.frame[key]]
    if any(k is None for k in keys) or len(set(keys)) != len(keys):
        raise ValueError(f"The fetched rows have empty or repeated values in the key column '{key}'.")
    position = list(result.frame.columns).index(key)
    incoming = {row[position]: row for row in
                (tuple(_python_value(v) for v in r) for r in result.frame.itertuples(index=False, name=None))}
    conn = _transaction(db_path)
    try:
        existing = changed = 0
        for start in range(0, len(keys), 500):
            chunk = keys[start:start + 500]
            marks = ", ".join("?" for _ in chunk)
            for row in conn.execute(f'SELECT * FROM "{table}" WHERE "{key}" IN ({marks})', chunk):
                existing += 1
                changed += tuple(row) != incoming[row[position]]
            conn.execute(f'DELETE FROM "{table}" WHERE "{key}" IN ({marks})', chunk)
        _insert(conn, table, result)
        repeated = conn.execute(f'SELECT 1 FROM "{table}" GROUP BY "{key}" HAVING COUNT(*) > 1 LIMIT 1').fetchone()
        if repeated:
            raise ValueError(f"The key column '{key}' is not unique in the dataset.")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return len(keys) - existing, changed


def row_count(db_path: Path, table: str) -> int:
    conn = sqlite3.connect(f"{Path(db_path).resolve().as_uri()}?mode=ro", uri=True)
    try:
        return conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    finally:
        conn.close()


def _drop_table(db_path: Path, table: str) -> None:
    conn = connect_datasets(db_path)
    try:
        with conn:
            conn.execute(f'DROP TABLE IF EXISTS "{table}"')
    finally:
        conn.close()


SOURCE_TYPES = {"csv": SourceType.CSV, "excel": SourceType.EXCEL, "postgres": SourceType.POSTGRES,
                "mysql": SourceType.MYSQL, "rest": SourceType.REST}


def _dataset(dataset_id, name, description, raw, content, original, uploads_dir, read_options, clean_options,
             result, checks, source, owner=None) -> Dataset:
    counts = summary(checks)
    extra_source = {"source": source} if source else {}
    return Dataset(
        dataset_id=dataset_id,
        name=name,
        source_type=SOURCE_TYPES[raw.file_type],
        storage=Storage.DATASETS,
        tables=(TableInfo(
            name=dataset_id,
            columns=tuple(ColumnInfo(c.name, c.sql_type, not c.required) for c in result.columns),
            row_count=len(result.frame),
        ),),
        description=description.strip(),
        owner=owner,
        quality_status=QualityStatus.WARNINGS if counts["warning"] else QualityStatus.PASSED,
        extra={
            "original_file": raw.file_name,
            "stored_original": original.relative_to(uploads_dir).as_posix(),
            "file_type": raw.file_type,
            "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "encoding": raw.encoding,
            "delimiter": raw.delimiter,
            "sheet": raw.sheet,
            "read_options": read_options.to_dict(),
            "clean_options": clean_options.to_dict(),
            "column_types": {c.name: c.kind for c in result.columns},
            "column_sources": {c.name: c.header for c in result.columns},
            "raw_headers": list(raw.headers),  # positions used by clean_options (needed to refresh)
            "rows_in_file": result.rows_before,
            "steps": [{"name": s.name, "detail": s.detail, "rows": s.rows, "columns": s.columns,
                       "cells": s.cells, "destructive": s.destructive} for s in result.steps],
            "validation": counts,
            "imported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **extra_source,
        },
    )
