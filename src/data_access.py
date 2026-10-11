"""Where each registered dataset's data lives, and what a question about it may read.

A question is always about exactly one dataset. ``target()`` resolves it through the catalog:
only registered datasets can be queried, the database file follows from where the dataset
is stored, and the query scope is the dataset's own tables. ``query_service`` enforces the
scope with both SQL guard layers, so a question about one dataset cannot read another
dataset, the demo tables, or internal tables.

``user`` (an ``accounts.User``) limits both functions to what that user may read; a dataset
they may not read is reported exactly like one that does not exist. ``None`` is the system.
"""

from dataclasses import dataclass
from pathlib import Path

from src import accounts, config
from src.catalog import DatasetCatalog
from src.core.models import DEMO_DATASET_ID, Dataset, Storage


@dataclass(frozen=True)
class Target:
    dataset: Dataset
    db_path: Path

    @property
    def dataset_id(self) -> str:
        return self.dataset.dataset_id

    @property
    def scope(self) -> frozenset[str]:
        return self.dataset.table_names

    @property
    def is_demo(self) -> bool:
        return self.dataset.dataset_id == DEMO_DATASET_ID


class UnknownDatasetError(LookupError):
    """The dataset is not (or no longer) registered, or the user may not read it."""


def catalog() -> DatasetCatalog:
    """The dataset catalog, with the built-in demo dataset registered."""
    datasets = DatasetCatalog(config.get_app_db_path())
    datasets.ensure_builtin()
    return datasets


def visible(dataset: Dataset, user: "accounts.User | None") -> bool:
    return accounts.can_view(user, dataset.owner, dataset.shared, dataset.builtin)


def datasets(user: "accounts.User | None" = None) -> list[Dataset]:
    """Every dataset ``user`` can query, the demo data first."""
    return [d for d in catalog().list() if visible(d, user)]


def target(dataset_id: str, demo_db: Path, user: "accounts.User | None" = None) -> Target:
    """Resolve ``dataset_id`` to its database file and scope. ``demo_db`` is the demo database."""
    dataset = catalog().get(dataset_id)
    if dataset is None or not visible(dataset, user):
        raise UnknownDatasetError(dataset_id)
    db_path = Path(demo_db) if dataset.storage == Storage.DEMO else config.get_datasets_db_path()
    return Target(dataset, db_path)
