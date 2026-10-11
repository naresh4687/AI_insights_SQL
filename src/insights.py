"""Chart selection and result explanations derived only from the returned data.

Both functions are deterministic and make no AI calls, so explanations can only state
facts present in the result (counts, highest/lowest values, period range). They never
claim trends or causes.
"""

import numbers
import re
from dataclasses import dataclass

import pandas as pd

MIN_CHART_ROWS = 2
MAX_CHART_ROWS = 50
_PERIOD_PATTERN = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")  # YYYY-MM or YYYY-MM-DD


@dataclass(frozen=True)
class ChartSpec:
    kind: str  # "bar" (compare magnitudes) or "line" (change over time)
    x: str  # label column
    y: str  # numeric column


def humanize(column: str) -> str:
    """'units_sold' -> 'units sold'."""
    return column.replace("_", " ").strip()


def format_value(value) -> str:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, numbers.Integral):
        return f"{value:,}"
    if isinstance(value, numbers.Real):
        return f"{value:,.2f}"
    return str(value)


def _label_and_value_columns(data: pd.DataFrame) -> tuple[str, str] | None:
    """Return (label, value) if the result is one text label column plus one numeric column."""
    if data.shape[1] != 2:
        return None
    label, value = data.columns
    if pd.api.types.is_numeric_dtype(data[label]) or pd.api.types.is_bool_dtype(data[label]):
        return None
    if not pd.api.types.is_numeric_dtype(data[value]) or pd.api.types.is_bool_dtype(data[value]):
        return None
    if data[label].isna().any() or data[value].isna().any() or not data[label].is_unique:
        return None
    return label, value


def _is_period_column(series: pd.Series) -> bool:
    return series.map(lambda v: bool(_PERIOD_PATTERN.match(str(v)))).all()


def choose_chart(data: pd.DataFrame) -> ChartSpec | None:
    """Pick a suitable chart for the result, or None when a chart would not be meaningful."""
    if not MIN_CHART_ROWS <= len(data) <= MAX_CHART_ROWS:
        return None
    columns = _label_and_value_columns(data)
    if columns is None:
        return None
    label, value = columns
    kind = "line" if _is_period_column(data[label]) else "bar"
    return ChartSpec(kind=kind, x=label, y=value)


def explain(data: pd.DataFrame, truncated: bool = False) -> str:
    """A short, factual summary of the result."""
    summary = _summary(data)
    if truncated:
        summary += f" Only the first {len(data):,} rows are shown; the full result is larger."
    return summary


def _summary(data: pd.DataFrame) -> str:
    rows, cols = data.shape
    if rows == 0:
        return "The query returned no rows, so there is nothing to summarise."
    if rows == 1 and cols == 1:
        return f"The result is {humanize(data.columns[0])}: {format_value(data.iloc[0, 0])}."

    columns = _label_and_value_columns(data)
    if columns is None:
        return f"The query returned {rows:,} rows and {cols} columns."

    label, value = columns
    metric = humanize(value)
    if rows == 1:
        return f"{data[label].iloc[0]} has a {metric} of {format_value(data[value].iloc[0])}."

    high, low = data.loc[data[value].idxmax()], data.loc[data[value].idxmin()]
    high_ties = int((data[value] == high[value]).sum())
    low_ties = int((data[value] == low[value]).sum())

    if _is_period_column(data[label]):
        periods = sorted(data[label].astype(str))
        text = (
            f"The results cover {rows} periods from {periods[0]} to {periods[-1]}. "
            f"The highest {metric} was {format_value(high[value])} in {high[label]}"
        )
        text += " (shared with other periods)" if high_ties > 1 else ""
        text += f"; the lowest was {format_value(low[value])} in {low[label]}"
        text += " (shared with other periods)." if low_ties > 1 else "."
        return text

    if high_ties == rows:
        return f"All {rows} rows returned have the same {metric} ({format_value(high[value])})."
    text = f"Across the {rows} rows returned, {high[label]} has the highest {metric} ({format_value(high[value])})"
    text += " (tied with others)" if high_ties > 1 else ""
    text += f" and {low[label]} the lowest ({format_value(low[value])})"
    text += " (tied with others)." if low_ties > 1 else "."
    return text
