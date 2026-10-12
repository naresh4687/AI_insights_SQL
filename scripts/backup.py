"""Back up or restore InsightSQL's data (the three databases and the uploaded files).

    python scripts/backup.py create [--dir backups] [--keep 7]
    python scripts/backup.py list   [--dir backups]
    python scripts/backup.py restore 20261012-020000 [--dir backups] --yes

Backups are safe while the app is running. Restoring replaces the current data: stop the app
and the refresh worker first. In Docker, see DEPLOYMENT.md for the matching commands.
Exit code: 0 on success, 1 on failure (the reason is printed).
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import backup  # noqa: E402
from src.core.logging_setup import configure_logging  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dir", type=Path, default=Path(os.getenv("INSIGHTSQL_BACKUP_DIR") or "backups"),
                        help="folder that holds the backups (default: INSIGHTSQL_BACKUP_DIR or ./backups)")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="make a new backup")
    create.add_argument("--keep", type=int, default=7, help="how many backups to keep (default 7)")
    commands.add_parser("list", help="show the backups, oldest first")
    restore = commands.add_parser("restore", help="replace the current data with a backup")
    restore.add_argument("name", help="the backup's folder name, e.g. 20261012-020000")
    restore.add_argument("--yes", action="store_true", help="confirm: the current data will be replaced")
    args = parser.parse_args(argv)
    configure_logging()

    try:
        if args.command == "create":
            folder = backup.create_backup(args.dir, keep=args.keep)
            print(f"Backup created: {folder}")
        elif args.command == "list":
            backups = backup.list_backups(args.dir)
            print("\n".join(p.name for p in backups) if backups else f"No backups in {args.dir}.")
        else:
            if not args.yes:
                print("Restoring replaces the current data. Stop the app and the worker, then run "
                      "again with --yes.")
                return 1
            restored = backup.restore_backup(args.dir / args.name)
            print(f"Restored from {args.name}: {', '.join(restored)}")
    except (backup.BackupError, OSError) as exc:
        print(f"Backup failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
