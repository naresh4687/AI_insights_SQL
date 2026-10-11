"""Profile a raw (text) table: structure, missing values, types, duplicates and outliers.

Profiles describe the file as uploaded. They never change it.
"""

from dataclasses import dataclass, field

import pandas as pd

from src.ingest import types
from src.ingest.readers import RawTable

# Text that often stands for "no value". Reported, but treated as missing only if the user
# chooses to (e.g. "NA" can also mean North America).
MISSING_MARKERS = ("NA", "N/A", "n/a", "na", "null", "NULL", "None", "none", "NaN", "nan", "-", "#N/A", "?")
OUTLIER_MIN_VALUES = 8
OUTLIER_IQR_FACTOR = 1.5


@dataclass(frozen=True)
class Outliers:
    count: int
    low: float
    high: float


@dataclass
class ColumnProfile:
    position: int
    header: str
    missing: int  # empty or whitespace-only cells
    distinct: int
    detection: types.Detection  # on trimmed, non-missing values
    whitespace: int  # values with leading or trailing spaces
    markers: dict[str, int] = field(default_factory=dict)
    minimum: float | None = None
    maximum: float | None = None
    mean: float | None = None
    outliers: Outliers | None = None
    examples: tuple[str, ...] = ()

    duplicate_header: bool = False

    @property
    def label(self) -> str:
        """How the column is named in messages; unique even when headers repeat."""
        if not self.header:
            return f"Column {self.position + 1}"
        return f"{self.header} (column {self.position + 1})" if self.duplicate_header else self.header


@dataclass
class DatasetProfile:
    rows: int
    columns: int
    duplicate_rows: int
    empty_rows: int
    columns_profile: list[ColumnProfile]

    @property
    def empty_columns(self) -> list[ColumnProfile]:
        return [c for c in self.columns_profile if c.detection.kind == "empty"]


def non_missing(series: pd.Series) -> pd.Series:
    """Trimmed values that are not empty."""
    trimmed = series.astype(str).str.strip()
    return trimmed[trimmed != ""]


def find_outliers(numbers: pd.Series) -> Outliers | None:
    """Values outside Q1 − 1.5·IQR … Q3 + 1.5·IQR (Tukey's fences)."""
    numbers = numbers.dropna().astype(float)
    if len(numbers) < OUTLIER_MIN_VALUES:
        return None
    q1, q3 = numbers.quantile(0.25), numbers.quantile(0.75)
    iqr = q3 - q1
    if iqr == 0:
        return None
    low, high = q1 - OUTLIER_IQR_FACTOR * iqr, q3 + OUTLIER_IQR_FACTOR * iqr
    count = int(((numbers < low) | (numbers > high)).sum())
    return Outliers(count, float(low), float(high)) if count else None


def profile_column(position: int, header: str, series: pd.Series) -> ColumnProfile:
    text = series.astype(str)
    values = non_missing(text)
    detection = types.detect(values)
    column = ColumnProfile(
        position=position, header=header, missing=len(text) - len(values), distinct=int(values.nunique()),
        detection=detection, whitespace=int((text != text.str.strip()).sum()),
        markers={m: int(n) for m, n in values.value_counts().items() if m in MISSING_MARKERS},
        examples=tuple(values.drop_duplicates().head(3).tolist()),
    )
    if detection.kind in ("integer", "float"):
        numbers = pd.to_numeric(values, errors="coerce")
        column.minimum, column.maximum, column.mean = float(numbers.min()), float(numbers.max()), float(numbers.mean())
        column.outliers = find_outliers(numbers)
    return column


def profile(raw: RawTable) -> DatasetProfile:
    frame = raw.frame
    columns = [profile_column(i, h, frame[i]) for i, h in enumerate(raw.headers)]
    seen = [h.lower() for h in raw.headers]
    for column in columns:
        column.duplicate_header = bool(column.header) and seen.count(column.header.lower()) > 1
    trimmed = frame.apply(lambda s: s.astype(str).str.strip()) if len(frame) else frame
    empty_rows = int((trimmed == "").all(axis=1).sum()) if len(frame) else 0
    return DatasetProfile(
        rows=raw.rows,
        columns=raw.columns,
        duplicate_rows=int(frame.duplicated().sum()) if len(frame) else 0,
        empty_rows=empty_rows,
        columns_profile=columns,
    )
