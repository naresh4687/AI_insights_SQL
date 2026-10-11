"""Value types for imported data: detection and strict conversion.

Imported values arrive as text. A column gets a type only when **every** non-missing value
matches it, so automatic detection never turns a value into NULL. Converting to a type the
values do not all match is an explicit user choice, and the failures are counted.
"""

import re
from dataclasses import dataclass

import pandas as pd

TYPES = ("text", "integer", "float", "boolean", "date", "datetime")
SQL_TYPES = {"text": "TEXT", "integer": "INTEGER", "float": "REAL", "boolean": "INTEGER",
             "date": "TEXT", "datetime": "TEXT", "empty": "TEXT"}

_INTEGER = r"[+-]?\d+"
_FLOAT = r"[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?"
_LEADING_ZERO = r"[+-]?0\d+"  # 007, 01234: identifiers such as ZIP codes, kept as text
_INT64_MAX = 2**63 - 1
TRUE_WORDS, FALSE_WORDS = frozenset({"true", "yes"}), frozenset({"false", "no"})

# Tried in this order. When a column matches several (e.g. 03/04/2025 as day-first and
# month-first) the first is used and the column is reported as ambiguous.
DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%m-%d-%Y", "%d.%m.%Y",
                "%d %b %Y", "%b %d %Y", "%d %B %Y", "%B %d %Y")
DATETIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M",
                    "%d/%m/%Y %H:%M", "%m/%d/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S")
FORMATS = DATE_FORMATS + DATETIME_FORMATS
MOSTLY = 0.8  # share of values that makes a column "mostly" numeric or dates


def is_datetime_format(fmt: str) -> bool:
    return "%H" in fmt


@dataclass(frozen=True)
class Detection:
    kind: str  # one of TYPES, or "empty" when there are no values
    date_format: str | None = None
    ambiguous_formats: tuple[str, ...] = ()  # other formats that also matched every value
    mostly: str | None = None  # "float" or "date" when ≥ 80 % (but not all) values match
    mostly_format: str | None = None
    best_format: str | None = None  # the format matching the most values, if any matched
    mismatches: int = 0  # values that do not match ``mostly``
    mismatch_examples: tuple[str, ...] = ()
    leading_zeros: bool = False


def numeric_mask(values: pd.Series) -> pd.Series:
    return values.str.fullmatch(_FLOAT)


def parse_dates(values: pd.Series, fmt: str) -> pd.Series:
    return pd.to_datetime(values, format=fmt, errors="coerce")


def _matching_formats(values: pd.Series) -> tuple[list[str], str | None, int]:
    """Formats matching every value, and the format matching the most values. Formats that
    match nothing in a sample are skipped, so ordinary text columns stay fast."""
    head = values.head(200)
    candidates = [fmt for fmt in FORMATS if parse_dates(head, fmt).notna().any()]
    full, best, best_count = [], None, 0
    for fmt in candidates:
        count = int(parse_dates(values, fmt).notna().sum())
        if count == len(values):
            full.append(fmt)
        if count > best_count:
            best, best_count = fmt, count
    return full, best, best_count


def detect(values: pd.Series) -> Detection:
    """Detect the type of ``values``: non-missing strings, already trimmed if wanted."""
    values = values.astype(str)
    if values.empty:
        return Detection("empty")
    lowered = values.str.lower()
    if lowered.isin(TRUE_WORDS | FALSE_WORDS).all():
        return Detection("boolean")

    numeric = numeric_mask(values)
    leading_zeros = bool(values.str.fullmatch(_LEADING_ZERO).any())
    if numeric.all() and not leading_zeros:
        integers = values.str.fullmatch(_INTEGER)
        if integers.all() and pd.to_numeric(values, errors="coerce").abs().max() <= _INT64_MAX:
            return Detection("integer")
        return Detection("float")

    sample = values.drop_duplicates()
    full, best, best_count = _matching_formats(sample)
    if full:
        kind = "datetime" if is_datetime_format(full[0]) else "date"
        same_kind = tuple(f for f in full[1:] if is_datetime_format(f) == (kind == "datetime"))
        return Detection(kind, date_format=full[0], ambiguous_formats=same_kind)

    detection = Detection("text", leading_zeros=leading_zeros, best_format=best)
    numeric_share = numeric.mean()
    date_share = (parse_dates(values, best).notna().mean()) if best else 0.0
    if not leading_zeros and numeric_share >= MOSTLY and numeric_share >= date_share:
        bad = values[~numeric]
        return Detection("text", mostly="float", best_format=best, mismatches=len(bad), mismatch_examples=_examples(bad))
    if date_share >= MOSTLY:
        bad = values[parse_dates(values, best).isna()]
        return Detection("text", mostly="date", mostly_format=best, best_format=best, mismatches=len(bad),
                         mismatch_examples=_examples(bad))
    return detection


def _examples(values: pd.Series, limit: int = 3) -> tuple[str, ...]:
    return tuple(values.drop_duplicates().head(limit).tolist())


def convert(values: pd.Series, kind: str, date_format: str | None = None) -> tuple[pd.Series, int]:
    """Convert non-missing strings (index preserved) to ``kind``.

    Returns the converted values (missing where conversion failed) and the number of
    values that could not be converted. Dates become ISO 8601 text.
    """
    values = values.astype(str)
    if kind == "text":
        return values.astype(object), 0
    if kind == "boolean":
        lowered = values.str.lower()
        out = pd.Series(pd.NA, index=values.index, dtype="Int64")
        out[lowered.isin(TRUE_WORDS) | (lowered == "1")] = 1
        out[lowered.isin(FALSE_WORDS) | (lowered == "0")] = 0
        return out, int(out.isna().sum())
    if kind in ("integer", "float"):
        numbers = pd.to_numeric(values.where(numeric_mask(values)), errors="coerce")
        if kind == "integer":
            whole = numbers.notna() & (numbers % 1 == 0) & (numbers.abs() <= _INT64_MAX)
            exact = values.str.fullmatch(_INTEGER)
            exact_values = values[exact].map(int)  # exact for big integers (no float rounding)
            exact_values = exact_values[exact_values.map(lambda v: abs(v) <= _INT64_MAX)]
            out = pd.Series(pd.NA, index=values.index, dtype="Int64")
            out[exact_values.index] = exact_values.astype("int64")
            loose = whole & ~exact
            out[loose] = numbers[loose].astype("int64")
            return out, int(out.isna().sum())
        return numbers.astype("Float64"), int(numbers.isna().sum())
    if kind in ("date", "datetime"):
        if date_format is None:
            raise ValueError("A date format is needed to convert dates.")
        parsed = parse_dates(values, date_format)
        text = parsed.dt.strftime("%Y-%m-%d" if kind == "date" else "%Y-%m-%d %H:%M:%S")
        return text.astype(object).where(parsed.notna(), None), int(parsed.isna().sum())
    raise ValueError(f"Unknown type: {kind}")
