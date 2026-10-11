"""Controlled export of a query result as CSV.

Only the rows already shown (at most ``query_service.DEFAULT_MAX_ROWS``) are exported:
there is no way to download a whole table from here. Text that a spreadsheet would treat
as a formula (starting with = + - @ or a tab/carriage return) is prefixed with an
apostrophe, so opening the file cannot run anything (CSV/formula injection). Numbers are
left as numbers. The file is UTF-8 with a byte-order mark so Excel shows accents correctly.
"""

import re
from datetime import datetime

import pandas as pd

FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def neutralise(value):
    """Make one text value safe to open in a spreadsheet."""
    if isinstance(value, str) and value.startswith(FORMULA_START):
        return "'" + value
    return value


def to_csv(data: pd.DataFrame) -> bytes:
    safe = data.copy()
    safe.columns = [neutralise(str(c)) for c in safe.columns]
    for column in safe.columns:
        if not pd.api.types.is_numeric_dtype(safe[column]):
            safe[column] = safe[column].map(neutralise)
    return safe.to_csv(index=False).encode("utf-8-sig")


def file_name(dataset_name: str, when: datetime | None = None) -> str:
    """'insightsql_<dataset>_<YYYYMMDD-HHMMSS>.csv' with only safe characters."""
    slug = re.sub(r"[^a-z0-9]+", "-", dataset_name.lower()).strip("-")[:40] or "result"
    return f"insightsql_{slug}_{(when or datetime.now()).strftime('%Y%m%d-%H%M%S')}.csv"
