"""Dataset catalog: the registry of every dataset the app can query.

Each dataset lists its tables, and that list is the query scope for questions about it
(``Dataset.table_names`` → ``run_query(..., allowed_tables=...)``). Only registered
datasets can be queried. The demo data is registered as the built-in dataset ``demo_sales``,
read from the real demo schema; it cannot be removed or replaced.

The catalog stores metadata only, never dataset rows or secrets.
"""

import functools
import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import sqlglot
from sqlglot import exp

from src import database, sql_guard
from src.core.models import (  # noqa: F401 (DEMO_DATASET_ID is part of this module's API)
    DEMO_DATASET_ID, ColumnInfo, Dataset, QualityStatus, RefreshStatus, SourceType, Storage, TableInfo,
)
from src.storage import app_db


class CatalogError(Exception):
    """A catalog operation was refused. ``message`` is safe to show to users."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@functools.cache  # built from a constant: parse it once, not on every page draw
def demo_dataset() -> Dataset:
    """The built-in demo dataset: the tables the SQL guard allows by default, with columns
    taken from ``database.SCHEMA_SQL`` (so it cannot drift from the real schema)."""
    tables = []
    for statement in sqlglot.parse(database.SCHEMA_SQL, read="sqlite"):
        if not (isinstance(statement, exp.Create) and statement.kind == "TABLE"):
            continue
        name = statement.find(exp.Table).name
        if name not in sql_guard.ALLOWED_TABLES:
            continue  # internal tables such as query_history are never part of a dataset
        columns = tuple(
            ColumnInfo(
                name=col.name,
                data_type=col.args["kind"].sql(dialect="sqlite") if col.args.get("kind") else "",
                nullable=not any(isinstance(c.kind, (exp.NotNullColumnConstraint, exp.PrimaryKeyColumnConstraint))
                                 for c in col.constraints),
            )
            for col in statement.this.expressions if isinstance(col, exp.ColumnDef)
        )
        tables.append(TableInfo(name=name, columns=columns))
    return Dataset(
        dataset_id=DEMO_DATASET_ID,
        name="Demo sales",
        source_type=SourceType.DEMO,
        storage=Storage.DEMO,
        tables=tuple(tables),
        description="Synthetic products and sales for 2025, used by Demo Mode.",
        builtin=True,
        quality_status=QualityStatus.PASSED,
    )


class DatasetCatalog:
    """Repository for dataset metadata in the app database."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        app_db.migrate(self.db_path)

    def ensure_builtin(self) -> Dataset:
        """Register (or update) the built-in demo dataset. Safe to call on every start."""
        dataset = demo_dataset()
        existing = self.get(dataset.dataset_id)
        if existing is None:
            return self.register(dataset, _allow_builtin=True)
        if existing.tables != dataset.tables or existing.description != dataset.description:
            return self._save(replace(dataset, created_at=existing.created_at), is_new=False)
        return existing

    def register(self, dataset: Dataset, *, _allow_builtin: bool = False) -> Dataset:
        """Add a new dataset. Refuses duplicate ids or names and reserved built-in datasets."""
        if dataset.builtin and not _allow_builtin:
            raise CatalogError("Built-in datasets cannot be registered by users.")
        if self.get(dataset.dataset_id) is not None:
            raise CatalogError(f"A dataset with id '{dataset.dataset_id}' already exists.")
        try:
            return self._save(dataset, is_new=True)
        except sqlite3.IntegrityError:
            raise CatalogError(f"A dataset named '{dataset.name}' already exists.") from None

    def set_shared(self, dataset_id: str, shared: bool) -> Dataset:
        """Share a dataset (read-only) with every signed-in user, or stop sharing it."""
        dataset = self._require(dataset_id)
        if dataset.builtin:
            raise CatalogError("Built-in datasets are always available to everyone.")
        return self._save(replace(dataset, shared=bool(shared)), is_new=False)

    def update_status(
        self,
        dataset_id: str,
        *,
        quality_status: QualityStatus | None = None,
        refresh_status: RefreshStatus | None = None,
        last_refresh_at: str | None = None,
    ) -> Dataset:
        dataset = self._require(dataset_id)
        changes = {k: v for k, v in {"quality_status": quality_status, "refresh_status": refresh_status,
                                     "last_refresh_at": last_refresh_at}.items() if v is not None}
        return self._save(replace(dataset, **changes), is_new=False)

    def replace(self, dataset: Dataset) -> Dataset:
        """Store new metadata for an existing dataset (e.g. after a refresh); built-ins excluded."""
        existing = self._require(dataset.dataset_id)
        if existing.builtin:
            raise CatalogError("Built-in datasets cannot be changed.")
        return self._save(replace(dataset, created_at=existing.created_at), is_new=False)

    def remove(self, dataset_id: str) -> None:
        """Remove a dataset's catalog entry (its stored data is handled by its importer)."""
        dataset = self._require(dataset_id)
        if dataset.builtin:
            raise CatalogError("Built-in datasets cannot be removed.")
        conn = app_db.connect(self.db_path)
        try:
            with conn:
                conn.execute("DELETE FROM datasets WHERE dataset_id = ?", (dataset_id,))
        finally:
            conn.close()

    def get(self, dataset_id: str) -> Dataset | None:
        conn = app_db.connect(self.db_path)
        try:
            row = conn.execute("SELECT * FROM datasets WHERE dataset_id = ?", (dataset_id,)).fetchone()
            return None if row is None else _to_dataset(conn, row)
        finally:
            conn.close()

    def list(self) -> list[Dataset]:
        """All datasets, built-in first, then by name."""
        conn = app_db.connect(self.db_path)
        try:
            rows = conn.execute("SELECT * FROM datasets ORDER BY builtin DESC, name COLLATE NOCASE").fetchall()
            return [_to_dataset(conn, row) for row in rows]
        finally:
            conn.close()

    def scope(self, dataset_id: str) -> frozenset[str]:
        """The tables a query about this dataset may read. Unknown datasets get no scope."""
        return self._require(dataset_id).table_names

    def _require(self, dataset_id: str) -> Dataset:
        dataset = self.get(dataset_id)
        if dataset is None:
            raise CatalogError(f"Dataset '{dataset_id}' is not registered.")
        return dataset

    def _save(self, dataset: Dataset, *, is_new: bool) -> Dataset:
        now = app_db.utc_now()
        dataset = replace(dataset, created_at=dataset.created_at or now, updated_at=now)
        values = {
            "name": dataset.name, "source_type": dataset.source_type.value, "storage": dataset.storage.value,
            "description": dataset.description, "owner": dataset.owner, "builtin": int(dataset.builtin),
            "shared": int(dataset.shared),
            "quality_status": dataset.quality_status.value, "refresh_status": dataset.refresh_status.value,
            "extra_json": json.dumps(dataset.extra, sort_keys=True), "created_at": dataset.created_at,
            "updated_at": dataset.updated_at, "last_refresh_at": dataset.last_refresh_at,
        }
        if is_new:
            sql = (f"INSERT INTO datasets (dataset_id, {', '.join(values)}) "
                   f"VALUES (?{', ?' * len(values)})")
            params = (dataset.dataset_id, *values.values())
        else:
            sql = f"UPDATE datasets SET {', '.join(f'{k} = ?' for k in values)} WHERE dataset_id = ?"
            params = (*values.values(), dataset.dataset_id)
        conn = app_db.connect(self.db_path)
        try:
            with conn:  # one transaction: the dataset and its tables change together
                conn.execute(sql, params)
                conn.execute("DELETE FROM dataset_tables WHERE dataset_id = ?", (dataset.dataset_id,))
                conn.executemany(
                    "INSERT INTO dataset_tables VALUES (?, ?, ?, ?, ?)",
                    [(dataset.dataset_id, t.name, i, _columns_json(t), t.row_count)
                     for i, t in enumerate(dataset.tables)],
                )
        finally:
            conn.close()
        return dataset


def _columns_json(table: TableInfo) -> str:
    return json.dumps([{"name": c.name, "data_type": c.data_type, "nullable": c.nullable} for c in table.columns])


def _to_dataset(conn: sqlite3.Connection, row: sqlite3.Row) -> Dataset:
    tables = tuple(
        TableInfo(name=t["table_name"], row_count=t["row_count"],
                  columns=tuple(ColumnInfo(**c) for c in json.loads(t["columns_json"])))
        for t in conn.execute("SELECT * FROM dataset_tables WHERE dataset_id = ? ORDER BY position",
                              (row["dataset_id"],))
    )
    return Dataset(
        dataset_id=row["dataset_id"], name=row["name"], source_type=SourceType(row["source_type"]),
        storage=Storage(row["storage"]), tables=tables, description=row["description"], owner=row["owner"],
        builtin=bool(row["builtin"]), shared=bool(row["shared"]), quality_status=QualityStatus(row["quality_status"]),
        refresh_status=RefreshStatus(row["refresh_status"]), created_at=row["created_at"],
        updated_at=row["updated_at"], last_refresh_at=row["last_refresh_at"],
        extra=json.loads(row["extra_json"]),
    )
