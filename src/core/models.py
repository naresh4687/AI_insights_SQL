"""Core data models shared by the catalog, importers, connectors and the query layer.

Plain frozen dataclasses: they hold metadata only, never dataset rows or secrets.
"""

import re
from dataclasses import dataclass, field
from enum import StrEnum

DEMO_DATASET_ID = "demo_sales"  # the built-in demo data (products, sales)

# Lower-case SQL identifiers that need no quoting; also the rule for dataset ids.
IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


class SourceType(StrEnum):
    DEMO = "demo"
    CSV = "csv"
    EXCEL = "excel"
    POSTGRES = "postgres"
    MYSQL = "mysql"
    REST = "rest"


class Storage(StrEnum):
    """Which SQLite file holds a dataset's tables."""

    DEMO = "demo"  # data/insightsql.db (products, sales)
    DATASETS = "datasets"  # data/datasets.db (imported and synchronised data)


class QualityStatus(StrEnum):
    UNKNOWN = "unknown"
    PASSED = "passed"
    WARNINGS = "warnings"
    FAILED = "failed"


class RefreshStatus(StrEnum):
    NEVER = "never"  # static data, or not refreshed yet
    RUNNING = "running"
    OK = "ok"
    FAILED = "failed"


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    data_type: str  # SQLite declared type, e.g. "INTEGER", "REAL", "TEXT"
    nullable: bool = True


@dataclass(frozen=True)
class TableInfo:
    name: str
    columns: tuple[ColumnInfo, ...]
    row_count: int | None = None

    def __post_init__(self) -> None:
        if not IDENTIFIER.match(self.name):
            raise ValueError(f"Invalid table name: {self.name!r}")
        if not self.columns:
            raise ValueError(f"Table {self.name!r} has no columns.")


@dataclass(frozen=True)
class Dataset:
    dataset_id: str
    name: str
    source_type: SourceType
    storage: Storage
    tables: tuple[TableInfo, ...]
    description: str = ""
    owner: str | None = None  # user_id of the account that created it (``accounts``)
    builtin: bool = False  # built-in datasets cannot be removed; everyone can read them
    shared: bool = False  # readable by every signed-in user (only the owner and admins change it)
    quality_status: QualityStatus = QualityStatus.UNKNOWN
    refresh_status: RefreshStatus = RefreshStatus.NEVER
    created_at: str | None = None  # ISO 8601 UTC, set by the catalog
    updated_at: str | None = None
    last_refresh_at: str | None = None
    extra: dict = field(default_factory=dict, compare=False, hash=False)  # non-secret settings only

    def __post_init__(self) -> None:
        if not IDENTIFIER.match(self.dataset_id):
            raise ValueError(f"Invalid dataset id: {self.dataset_id!r}")
        if not self.name.strip():
            raise ValueError("A dataset needs a name.")
        if not self.tables:
            raise ValueError(f"Dataset {self.dataset_id!r} has no tables.")
        names = [t.name for t in self.tables]
        if len(set(names)) != len(names):
            raise ValueError(f"Dataset {self.dataset_id!r} lists a table twice.")

    @property
    def table_names(self) -> frozenset[str]:
        """The query scope for this dataset: the only tables a question about it may read."""
        return frozenset(t.name for t in self.tables)
