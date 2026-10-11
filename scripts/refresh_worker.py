"""Run scheduled dataset refreshes.

Streamlit cannot run reliable background jobs, so scheduled refreshes run in this separate
process. Run it every few minutes from cron or a systemd timer:

    */5 * * * *  cd /path/to/insightsql && .venv/bin/python scripts/refresh_worker.py --once

or keep it running:  python scripts/refresh_worker.py --loop --interval 60

Each run refreshes the datasets whose schedule is due (see the Datasets page). This is periodic
polling, not real-time streaming. It needs the same .env as the app (INSIGHTSQL_SECRET_KEY for
saved connection secrets). Exit code: 0 if every due refresh succeeded or was skipped, 1 if any failed.
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.logging_setup import configure_logging  # noqa: E402
from src.sync import refresh  # noqa: E402


def run_once() -> int:
    results = refresh.refresh_due()
    for dataset_id, result in results:
        print(f"{dataset_id}: {result.status} - {result.message}", flush=True)
    if not results:
        print("No refresh is due.", flush=True)
    return 1 if any(r.status == "failed" for _, r in results) else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="run due refreshes once and exit (default)")
    mode.add_argument("--loop", action="store_true", help="keep checking for due refreshes")
    parser.add_argument("--interval", type=int, default=60, help="seconds between checks with --loop (default 60)")
    args = parser.parse_args(argv)
    configure_logging()
    if not args.loop:
        return run_once()
    while True:  # pragma: no cover - stopped by the service manager
        run_once()
        time.sleep(max(10, args.interval))


if __name__ == "__main__":
    sys.exit(main())
