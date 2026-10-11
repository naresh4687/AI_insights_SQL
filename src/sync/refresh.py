"""Refresh a dataset imported from a connection, keeping the last good data on any failure.

A refresh fetches again with the stored source, runs the same quality checks and the cleaning
options approved at import, and checks that the columns and types are unchanged. Only then:
- **full** mode replaces the table atomically (``store.swap_table``);
- **incremental** mode (databases only) fetches rows whose cursor column is at least the last
  value seen and inserts or replaces them by a unique key column in one transaction
  (``store.upsert_rows``). Deleted source rows are not detected; run a full refresh for that.
Nothing is changed when any step fails. Every run is logged; one refresh per dataset at a time
(a lock); temporary failures are retried a limited number of times with a growing wait.
"""

import logging
import os
import time
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src import config, data_access
from src.connectors import databases, rest
from src.connectors.profiles import ConnectorError, store as connection_store
from src.core import secrets
from src.core.models import Dataset, QualityStatus, RefreshStatus, TableInfo
from src.ingest import store
from src.ingest.preprocess import CleanOptions, clean
from src.ingest.profiling import profile
from src.ingest.readers import RawTable
from src.ingest.validation import ERROR, has_errors, summary, validate
from src.sync.state import MIN_INTERVAL_MINUTES, MODES, RefreshSettings, SyncState

logger = logging.getLogger(__name__)

DATABASE_KINDS = ("postgres", "mysql")
CURSOR_KINDS = ("integer", "float", "date", "datetime")


class RefreshError(Exception):
    """A refresh cannot complete. ``message`` is user-safe; ``retryable`` marks temporary problems."""

    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class RefreshResult:
    status: str  # success, failed or skipped
    message: str
    run_id: int | None = None
    rows_fetched: int | None = None
    rows_inserted: int | None = None
    rows_updated: int | None = None
    rows_total: int | None = None


def state() -> SyncState:
    return SyncState(config.get_app_db_path())


def source_of(dataset: Dataset) -> dict | None:
    """The stored connection source, if the dataset can be refreshed."""
    source = dataset.extra.get("source")
    return source if source and source.get("kind") in (*DATABASE_KINDS, "rest") else None


# --- Settings --------------------------------------------------------------------------

def check_settings(dataset: Dataset, settings: RefreshSettings) -> RefreshSettings:
    """Validate refresh settings for ``dataset``; raises ``RefreshError`` with the reason."""
    source = source_of(dataset)
    if source is None:
        raise RefreshError("Only datasets imported from a connection can be refreshed. Import a file again instead.")
    if settings.mode not in MODES:
        raise RefreshError("Choose full or incremental refresh.")
    if settings.interval_minutes is not None and settings.interval_minutes < MIN_INTERVAL_MINUTES:
        raise RefreshError(f"The schedule must be at least every {MIN_INTERVAL_MINUTES} minutes.")
    if settings.enabled and not settings.interval_minutes:
        raise RefreshError("Choose how often to refresh before turning the schedule on.")
    if settings.mode == "full":
        return replace(settings, key_column=None, cursor_column=None)
    if source["kind"] not in DATABASE_KINDS:
        raise RefreshError("Incremental refresh is available for database tables only; APIs use full refresh.")
    columns = {c.name: c for c in dataset.tables[0].columns}
    kinds = dataset.extra.get("column_types", {})
    for role, name in (("key", settings.key_column), ("cursor", settings.cursor_column)):
        if not name or name not in columns:
            raise RefreshError(f"Choose the {role} column from the dataset's columns.")
    if kinds.get(settings.cursor_column) not in CURSOR_KINDS:
        raise RefreshError("The cursor column must hold numbers, dates or times that grow for new or changed rows.")
    options = CleanOptions.from_dict(dataset.extra["clean_options"])
    if options.remove_duplicate_rows or options.outliers == "remove_rows" or any(
            c.missing in ("fill_mean", "fill_median", "fill_mode") for c in options.columns.values()):
        raise RefreshError("Incremental refresh needs cleaning rules that work row by row. Removing duplicate rows "
                           "or outliers, and filling with an average, median or most common value depend on all "
                           "rows, so use full refresh for this dataset.")
    db_path = config.get_datasets_db_path()
    conn = store.connect_datasets(db_path)
    try:
        key = settings.key_column
        empty, repeated = conn.execute(
            f'SELECT SUM("{key}" IS NULL), COUNT("{key}") - COUNT(DISTINCT "{key}") FROM "{dataset.dataset_id}"'
        ).fetchone()
    finally:
        conn.close()
    if empty or repeated:
        raise RefreshError(f"The key column '{key}' must have a value in every row and no repeats.")
    return settings


def save_settings(dataset: Dataset, settings: RefreshSettings) -> RefreshSettings:
    return state().save_settings(check_settings(dataset, settings))


# --- Running ---------------------------------------------------------------------------

def refresh(dataset_id: str, trigger: str = "manual", sleep=time.sleep) -> RefreshResult:
    """Refresh one dataset now. Never raises for refresh problems: the result says what happened."""
    sync = state()
    catalog = data_access.catalog()
    dataset = catalog.get(dataset_id)
    if dataset is None or source_of(dataset) is None:
        return RefreshResult("skipped", "This dataset cannot be refreshed.")
    settings = sync.settings(dataset_id)
    owner = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
    if not sync.acquire(dataset_id, owner):
        run_id = sync.start_run(dataset_id, trigger, settings.mode)
        message = "Another refresh of this dataset is running; this one was skipped."
        sync.finish_run(run_id, "skipped", message)
        return RefreshResult("skipped", message, run_id)
    run_id = sync.start_run(dataset_id, trigger, settings.mode)
    try:
        catalog.update_status(dataset_id, refresh_status=RefreshStatus.RUNNING)
        attempts, max_attempts = 0, config.get_refresh_max_attempts()
        while True:
            attempts += 1
            try:
                outcome = _attempt(dataset, settings)
                break
            except RefreshError as exc:
                if exc.retryable and attempts < max_attempts:
                    wait = config.get_refresh_retry_seconds() * 2 ** (attempts - 1)
                    logger.warning("Refresh of %s failed (attempt %d): %s; retrying in %.0f s",
                                   dataset_id, attempts, exc.message, wait)
                    sleep(wait)
                    continue
                return _failed(sync, catalog, dataset_id, run_id, attempts, exc.message)
            except Exception:  # unexpected: never leave the run open; the old data is untouched
                logger.exception("Refresh of %s failed unexpectedly", dataset_id)
                return _failed(sync, catalog, dataset_id, run_id, attempts,
                               "The refresh failed unexpectedly; the previous data is kept. See the log for details.")
        updated = _updated_metadata(dataset, outcome)
        catalog.replace(updated)
        sync.finish_run(run_id, "success", outcome["message"], attempts, outcome["fetched"], outcome["inserted"],
                        outcome["updated"], outcome["total"])
        sync.after_run(dataset_id, True, outcome.get("cursor"))
        return RefreshResult("success", outcome["message"], run_id, outcome["fetched"], outcome["inserted"],
                             outcome["updated"], outcome["total"])
    finally:
        sync.release(dataset_id, owner)


def _failed(sync: SyncState, catalog, dataset_id: str, run_id: int, attempts: int, message: str) -> RefreshResult:
    message = f"{message} The previous data is kept."
    sync.finish_run(run_id, "failed", message, attempts)
    catalog.update_status(dataset_id, refresh_status=RefreshStatus.FAILED)
    sync.after_run(dataset_id, False)
    return RefreshResult("failed", message, run_id)


def _updated_metadata(dataset: Dataset, outcome: dict) -> Dataset:
    table = dataset.tables[0]
    extra = dict(dataset.extra)
    extra["last_refresh"] = {k: outcome[k] for k in ("fetched", "inserted", "updated", "total", "message")}
    if outcome.get("validation"):
        extra["validation"] = outcome["validation"]
    quality = dataset.quality_status
    if outcome.get("validation"):
        quality = QualityStatus.WARNINGS if outcome["validation"]["warning"] else QualityStatus.PASSED
    return replace(dataset, tables=(replace(table, row_count=outcome["total"]),), extra=extra,
                   quality_status=quality, refresh_status=RefreshStatus.OK,
                   last_refresh_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))


def _attempt(dataset: Dataset, settings: RefreshSettings) -> dict:
    source = source_of(dataset)
    connections = connection_store()
    connection = connections.get(source["connection_id"])
    if connection is None:
        raise RefreshError("The connection this dataset came from was deleted. Add it again with the same name, "
                           "or import the data again.")
    try:
        secret = connections.secret(connection.connection_id)
        raw, content, ignored = _fetch(dataset, source, connection, secret, settings)
    except secrets.SecretError as exc:
        raise RefreshError(exc.message) from None
    except ConnectorError as exc:
        raise RefreshError(exc.message, retryable=exc.retryable) from None

    incremental = settings.mode == "incremental"
    if incremental and raw.rows == 0:
        total = store.row_count(config.get_datasets_db_path(), dataset.dataset_id)
        return {"fetched": 0, "inserted": 0, "updated": 0, "total": total, "cursor": settings.last_cursor,
                "message": "No new or changed rows since the last refresh."}

    checks = validate(raw, profile(raw))
    if has_errors(checks):
        first = next(c for c in checks if c.level == ERROR)
        raise RefreshError(f"The new data failed a quality check: {first.message}")
    options = CleanOptions.from_dict(dataset.extra["clean_options"])
    result = clean(raw, options)
    if not result.ok:
        raise RefreshError(f"The new data does not pass the dataset's cleaning rules: {result.checks[0].message}")
    expected = [(c.name, c.data_type) for c in dataset.tables[0].columns]
    found = [(c.name, c.sql_type) for c in result.columns]
    if found != expected:
        raise RefreshError("The source's columns or types have changed (expected "
                           f"{', '.join(f'{n} {t}' for n, t in expected)}; got {', '.join(f'{n} {t}' for n, t in found)}). "
                           "Import it again as a new dataset to use the new structure.")

    db_path = config.get_datasets_db_path()
    removed = sum(s.rows for s in result.steps)
    if incremental:
        try:
            inserted, updated = store.upsert_rows(db_path, dataset.dataset_id, result, settings.key_column)
        except ValueError as exc:
            raise RefreshError(str(exc)) from None
        total = store.row_count(db_path, dataset.dataset_id)
        message = f"{inserted:,} new and {updated:,} changed rows applied; {total:,} rows in total."
        if removed:
            message += (f" {removed:,} fetched rows were removed by the cleaning rules; any earlier versions of "
                        "them are kept.")
        cursor = _max_cursor(raw, settings.cursor_column, dataset)
    else:
        store.swap_table(db_path, dataset.dataset_id, result)
        inserted = updated = None
        total = len(result.frame)
        message = f"Replaced with {total:,} rows."
        cursor = None
    if ignored:
        message += f" New source fields not in this dataset were not imported: {', '.join(ignored)}."
    _keep_latest(dataset, raw, content)
    return {"fetched": raw.rows, "inserted": inserted, "updated": updated, "total": total, "cursor": cursor,
            "message": message, "validation": summary(checks)}


def _fetch(dataset: Dataset, source: dict, connection, secret, settings: RefreshSettings):
    limit = config.get_import_max_rows()
    if source["kind"] in DATABASE_KINDS:
        since = None
        if settings.mode == "incremental":
            header = dataset.extra["column_sources"][settings.cursor_column]
            since = (header, settings.last_cursor)
        frame, truncated = databases.fetch(connection, secret, source["schema"], source["table"], source["columns"],
                                           limit, since=since)
        if truncated:
            raise RefreshError(f"The source has more than {limit:,} {'new or changed ' if since else ''}rows, the "
                               "import limit.")
        raw = RawTable(file_name=f"{source['schema']}.{source['table']}.csv", file_type=source["kind"],
                       headers=list(source["columns"]), frame=frame.set_axis(range(frame.shape[1]), axis=1))
        return raw, frame.to_csv(index=False).encode("utf-8"), []
    endpoint = rest.Endpoint.from_dict(source["endpoint"])
    fetched = rest.fetch(connection, secret, endpoint, limit)
    if not fetched.records:
        raise RefreshError("The API returned no records, so there is nothing to replace the data with.")
    frame = rest.to_frame(fetched.records)
    headers = dataset.extra.get("raw_headers") or list(dataset.extra.get("column_sources", {}).values())
    missing = [h for h in headers if h not in frame.columns]
    if missing:
        raise RefreshError(f"Fields are missing from the API response: {', '.join(missing)}. The source's structure "
                           "changed; import it again as a new dataset to use the new structure.")
    ignored = [str(c) for c in frame.columns if c not in headers]
    frame = frame[headers]
    raw = RawTable(file_name=f"{endpoint.path.strip('/').replace('/', '_') or 'records'}.json", file_type="rest",
                   headers=list(headers), frame=frame.set_axis(range(len(headers)), axis=1).reset_index(drop=True))
    return raw, b"[" + b",\n".join(fetched.pages) + b"]", ignored


def _max_cursor(raw: RawTable, cursor_column: str, dataset: Dataset) -> str | None:
    """The highest cursor value fetched, as text (the next refresh fetches from it)."""
    header = dataset.extra["column_sources"][cursor_column]
    values = raw.frame[raw.headers.index(header)]
    values = values[values != ""]
    if values.empty:
        return None
    if dataset.extra["column_types"][cursor_column] in ("integer", "float"):
        return values.iloc[pd.to_numeric(values).values.argmax()]
    return max(values)  # ISO dates and times sort as text


def _keep_latest(dataset: Dataset, raw: RawTable, content: bytes) -> None:
    """Keep the latest fetched data next to the original import (replaced atomically)."""
    folder = config.get_uploads_dir() / dataset.dataset_id
    folder.mkdir(parents=True, exist_ok=True)
    suffix = Path(raw.file_name).suffix
    temporary = folder / ".latest.tmp"
    temporary.write_bytes(content)
    os.replace(temporary, folder / f"latest{suffix}")


def refresh_due(sleep=time.sleep) -> list[tuple[str, RefreshResult]]:
    """Run every due scheduled refresh (used by scripts/refresh_worker.py)."""
    return [(dataset_id, refresh(dataset_id, "scheduled", sleep)) for dataset_id in state().due()]
