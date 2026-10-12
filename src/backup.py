"""Backups of everything the app stores: the three SQLite databases and the uploaded files.

A database file that is being written to cannot safely be copied byte by byte, so each database
is copied with SQLite's online backup API (consistent even while the app and the refresh worker
are running), then checked with ``PRAGMA integrity_check``. Each backup is one dated folder:

    <backup root>/20261012-020000/
        insightsql.db  app.db  datasets.db  uploads/  manifest.json

Restoring replaces the live data with a backup's; stop the app and the worker first.
The encryption key for saved connection secrets (INSIGHTSQL_SECRET_KEY) is never part of a
backup: keep a copy of it somewhere else.
"""

import json
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path

from src import config

NAME_FORMAT = "%Y%m%d-%H%M%S"


@dataclass(frozen=True)
class Targets:
    """The live data: database files by backup name, and the uploads folder."""
    databases: dict[str, Path]
    uploads: Path


def live_targets() -> Targets:
    return Targets(
        databases={"insightsql.db": config.get_db_path(), "app.db": config.get_app_db_path(),
                   "datasets.db": config.get_datasets_db_path()},
        uploads=config.get_uploads_dir(),
    )


class BackupError(Exception):
    """A backup could not be made, checked or restored; the message says why."""


def _copy_database(source: Path, destination: Path) -> None:
    src = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
    dst = sqlite3.connect(destination)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def check_database(path: Path) -> None:
    """Raise BackupError unless ``path`` is a readable, intact SQLite database."""
    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise BackupError(f"{path.name} is not a readable database: {exc}") from exc
    if result != "ok":
        raise BackupError(f"{path.name} failed the integrity check: {result}")


def _table_rows(path: Path) -> dict[str, int]:
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
    finally:
        conn.close()


def create_backup(root: Path, targets: Targets | None = None, keep: int = 7,
                  now: datetime | None = None) -> Path:
    """Back up every database that exists and the uploads folder into a new dated folder under
    ``root``; check each copy; then delete all but the newest ``keep`` backups. Returns the folder.
    Nothing is left behind if any step fails."""
    targets = targets or live_targets()
    stamp = (now or datetime.now()).strftime(NAME_FORMAT)  # server's local time, like the schedule
    root.mkdir(parents=True, exist_ok=True)
    folder = root / stamp
    if folder.exists():
        raise BackupError(f"A backup named {stamp} already exists.")
    work = root / f".{stamp}.partial"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()
    try:
        manifest = {"created": stamp, "databases": {}, "uploads_files": 0}
        for name, source in targets.databases.items():
            if not source.exists():
                continue
            _copy_database(source, work / name)
            check_database(work / name)
            manifest["databases"][name] = _table_rows(work / name)
        if targets.uploads.exists():
            shutil.copytree(targets.uploads, work / "uploads")
            manifest["uploads_files"] = sum(1 for p in (work / "uploads").rglob("*") if p.is_file())
        (work / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
        work.rename(folder)  # a backup folder only ever appears complete
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise
    prune(root, keep)
    return folder


def list_backups(root: Path) -> list[Path]:
    """Complete backups under ``root``, oldest first."""
    if not root.exists():
        return []
    found = []
    for path in root.iterdir():
        try:
            datetime.strptime(path.name, NAME_FORMAT)
        except ValueError:
            continue
        if path.is_dir() and (path / "manifest.json").exists():
            found.append(path)
    return sorted(found, key=lambda p: p.name)


def last_backup_time(root: Path) -> datetime | None:
    backups = list_backups(root)
    return datetime.strptime(backups[-1].name, NAME_FORMAT) if backups else None


def backup_due(now: datetime, at: time, last: datetime | None) -> bool:
    """True once a day: when ``now`` has passed today's backup time ``at`` and no backup was made
    since then. A manual backup earlier in the day does not replace the scheduled one, and a
    worker started after the time makes today's backup straight away."""
    scheduled = datetime.combine(now.date(), at)
    return now >= scheduled and (last is None or last < scheduled)


def prune(root: Path, keep: int) -> list[Path]:
    """Delete all but the newest ``keep`` backups (at least one is always kept)."""
    backups = list_backups(root)
    removed = backups[:-max(1, keep)]
    for path in removed:
        shutil.rmtree(path)
    return removed


def restore_backup(folder: Path, targets: Targets | None = None) -> list[str]:
    """Replace the live databases and uploads with those in ``folder``. Every database in the
    backup is checked before anything is changed. Stop the app and the worker first."""
    targets = targets or live_targets()
    if not (folder / "manifest.json").exists():
        raise BackupError(f"{folder} is not a complete backup.")
    names = [name for name in targets.databases if (folder / name).exists()]
    if not names:
        raise BackupError(f"{folder} contains no database.")
    for name in names:
        check_database(folder / name)
    restored = []
    for name in names:
        destination = targets.databases[name]
        destination.parent.mkdir(parents=True, exist_ok=True)
        _copy_database(folder / name, destination)  # writes the pages into the live file
        restored.append(name)
    if (folder / "uploads").exists():
        shutil.rmtree(targets.uploads, ignore_errors=True)
        shutil.copytree(folder / "uploads", targets.uploads)
        restored.append("uploads")
    return restored
