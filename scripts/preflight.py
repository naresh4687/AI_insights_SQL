"""Check the settings before the app starts (used by the Docker image; see src/preflight.py).

    python scripts/preflight.py

Prints warnings and errors. Exit code 0 if the app can start, 1 if a setting must be fixed first.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Importing the sign-in checks loads Streamlit outside a running app; hide its "no runtime" notice.
from streamlit import logger as _streamlit_logger  # noqa: E402

_streamlit_logger.set_log_level("error")

from src import preflight  # noqa: E402

if __name__ == "__main__":
    sys.exit(preflight.main())
