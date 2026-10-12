"""Run scheduled dataset refreshes.

Streamlit cannot run reliable background jobs, so scheduled refreshes run in this separate
process. Run it every few minutes from cron or a systemd timer:

    */5 * * * *  cd /path/to/insightsql && .venv/bin/python scripts/refresh_worker.py --once

or keep it running:  python scripts/refresh_worker.py --loop --interval 60

With --loop it can also make the daily backup (src/backup.py), as in the Docker setup:
    python scripts/refresh_worker.py --loop --backup-at 02:00 --backup-dir /backups --backup-keep 7

Each run refreshes the datasets whose schedule is due (see the Datasets page). This is periodic
polling, not real-time streaming. It needs the same .env as the app (INSIGHTSQL_SECRET_KEY for
saved connection secrets). Exit code: 0 if every due refresh succeeded or was skipped, 1 if any failed.
"""

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import backup  # noqa: E402
from src.core.logging_setup import configure_logging  # noqa: E402
from src.sync import refresh  # noqa: E402


def run_once() -> int:
    results = refresh.refresh_due()
    for dataset_id, result in results:
        print(f"{dataset_id}: {result.status} - {result.message}", flush=True)
    if not results:
        print("No refresh is due.", flush=True)
    return 1 if any(r.status == "failed" for _, r in results) else 0


def backup_if_due(root: Path, at, keep: int) -> None:
    """Make today's backup if its time has come. A failed backup is reported and retried at the
    next check; it never stops the refreshes."""
    try:
        if not backup.backup_due(datetime.now(), at, backup.last_backup_time(root)):
            return
        print(f"Backup created: {backup.create_backup(root, keep=keep)}", flush=True)
    except (backup.BackupError, OSError) as exc:
        print(f"Backup failed: {exc}", file=sys.stderr, flush=True)


def _clock_time(text: str):
    try:
        return datetime.strptime(text, "%H:%M").time()
    except ValueError:
        raise argparse.ArgumentTypeError("use HH:MM, for example 02:00") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="run due refreshes once and exit (default)")
    mode.add_argument("--loop", action="store_true", help="keep checking for due refreshes")
    parser.add_argument("--interval", type=int, default=60, help="seconds between checks with --loop (default 60)")
    parser.add_argument("--backup-at", type=_clock_time, help="with --loop: make a daily backup at this time (HH:MM)")
    parser.add_argument("--backup-dir", type=Path, default=Path("backups"), help="folder for the backups")
    parser.add_argument("--backup-keep", type=int, default=7, help="how many backups to keep (default 7)")
    args = parser.parse_args(argv)
    configure_logging()
    if not args.loop:
        return run_once()
    while True:  # pragma: no cover - stopped by the service manager
        run_once()
        if args.backup_at:
            backup_if_due(args.backup_dir, args.backup_at, args.backup_keep)
        time.sleep(max(10, args.interval))


if __name__ == "__main__":
    sys.exit(main())
