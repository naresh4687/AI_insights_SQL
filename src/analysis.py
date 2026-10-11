"""Chart options, statistics, facts and follow-up questions computed from a query result.

Everything here is deterministic and uses only the rows the query returned: no AI call,
nothing sent anywhere, and no claim that the data does not support (no causes, no
forecasts). Results are at most ``query_service.DEFAULT_MAX_ROWS`` rows; when a result was
cut off, facts say they describe the rows shown.
"""

from dataclasses import dataclass

import pandas as pd

from src import demo_queries, insights
from src.ingest.profiling import find_outliers
from src.insights import format_value, humanize

CHART_LABELS = {
    "bar": "Bar", "column": "Column", "line": "Line", "area": "Area", "pie": "Pie", "donut": "Donut",
    "scatter": "Scatter", "histogram": "Histogram", "box": "Box plot", "kpi": "KPI cards",
}
MAX_PIE_SLICES = 6  # the theme has 6 distinct categorical colours
MAX_KPI_CARDS = 6
MIN_DISTRIBUTION_ROWS = 5
MAX_FOLLOW_UPS = 3


@dataclass(frozen=True)
class Chart:
    kind: str  # a key of CHART_LABELS
    x: str | None = None
    y: str | None = None

    @property
    def label(self) -> str:
        if self.kind == "box" and self.x:
            return f"Box plot by {humanize(self.x)}"
        return CHART_LABELS[self.kind]


@dataclass(frozen=True)
class ColumnStats:
    column: str
    count: int  # non-empty values
    missing: int
    total: float
    mean: float
    median: float
    minimum: float
    maximum: float
    std: float | None  # sample standard deviation; None for fewer than 2 values


def numeric_columns(data: pd.DataFrame) -> list[str]:
    """Columns holding numbers (not booleans) with at least one value."""
    return [c for c in data.columns
            if pd.api.types.is_numeric_dtype(data[c]) and not pd.api.types.is_bool_dtype(data[c])
            and data[c].notna().any()]


def label_columns(data: pd.DataFrame) -> list[str]:
    return [c for c in data.columns if c not in numeric_columns(data)]


# --- Charts -----------------------------------------------------------------------------

def chart_options(data: pd.DataFrame) -> list[Chart]:
    """Charts that suit the result, best first. The first is the existing default
    (``insights.choose_chart``: bar, or line over time) whenever that applies."""
    if data.empty:
        return []
    numbers, labels = numeric_columns(data), label_columns(data)
    options: list[Chart] = []
    base = insights.choose_chart(data)
    if base is not None:
        options.append(Chart(base.kind, base.x, base.y))
        if base.kind == "line":
            options += [Chart("area", base.x, base.y), Chart("column", base.x, base.y)]
        else:
            options.append(Chart("column", base.x, base.y))
            values = data[base.y]
            if len(data) <= MAX_PIE_SLICES and (values >= 0).all() and values.sum() > 0:
                options += [Chart("pie", base.x, base.y), Chart("donut", base.x, base.y)]
    if len(data) == 1 and numbers and len(numbers) <= MAX_KPI_CARDS:
        options.insert(0, Chart("kpi"))
    if len(data) >= 3 and len(numbers) >= 2:
        options.append(Chart("scatter", numbers[0], numbers[1]))
    if labels and numbers and not data[labels[0]].is_unique and len(data) >= MIN_DISTRIBUTION_ROWS:
        options.append(Chart("box", labels[0], numbers[-1]))  # distribution per category
    if numbers and len(data) >= MIN_DISTRIBUTION_ROWS:
        value = base.y if base is not None else numbers[-1]
        options += [Chart("histogram", value), Chart("box", None, value)]
    unique: list[Chart] = []
    for option in options:
        if option not in unique:
            unique.append(option)
    return unique


# --- Statistics -------------------------------------------------------------------------

def statistics(data: pd.DataFrame) -> list[ColumnStats]:
    stats = []
    for column in numeric_columns(data):
        values = data[column].dropna().astype(float)
        stats.append(ColumnStats(
            column=column, count=len(values), missing=int(data[column].isna().sum()), total=float(values.sum()),
            mean=float(values.mean()), median=float(values.median()), minimum=float(values.min()),
            maximum=float(values.max()), std=float(values.std()) if len(values) > 1 else None,
        ))
    return stats


@dataclass(frozen=True)
class PeriodChange:
    period: str
    value: float
    previous_period: str
    previous_value: float

    @property
    def change(self) -> float:
        return self.value - self.previous_value

    @property
    def percent(self) -> float | None:
        return None if self.previous_value == 0 else self.change / abs(self.previous_value) * 100


def period_changes(data: pd.DataFrame) -> list[PeriodChange]:
    """Change from each period to the next, for a periods-and-values result (in period order)."""
    base = insights.choose_chart(data)
    if base is None or base.kind != "line":
        return []
    ordered = data.sort_values(base.x)
    periods, values = ordered[base.x].astype(str).tolist(), ordered[base.y].astype(float).tolist()
    return [PeriodChange(periods[i], values[i], periods[i - 1], values[i - 1]) for i in range(1, len(periods))]


def _fmt(value: float, series: pd.Series) -> str:
    """Format like the column: whole numbers for integer columns, 2 decimals otherwise."""
    if pd.api.types.is_integer_dtype(series) and float(value).is_integer():
        return format_value(int(value))
    return format_value(round(float(value), 2))


def _percent(value: float | None) -> str:
    return "" if value is None else f" ({value:+.1f}%)"


def _signed(value: float) -> str:
    return ("+" if value > 0 else "") + format_value(round(value, 2))


# --- Facts ------------------------------------------------------------------------------

def facts(data: pd.DataFrame, truncated: bool = False) -> list[str]:
    """Short factual statements about the result, each computed from its values."""
    if data.empty:
        return []
    found: list[str] = []
    base = insights.choose_chart(data)

    changes = period_changes(data)
    if changes:
        metric = humanize(base.y)
        first, last = changes[0], changes[-1]
        overall = last.value - first.previous_value
        overall_pct = None if first.previous_value == 0 else overall / abs(first.previous_value) * 100
        pct = "" if overall_pct is None else f", {overall_pct:+.1f}%"
        column = data[base.y]
        found.append(f"From {first.previous_period} to {last.period}, {metric} went from "
                     f"{_fmt(first.previous_value, column)} to {_fmt(last.value, column)} ({_signed(overall)}{pct}).")
        found.append(f"Latest period {last.period}: {_fmt(last.value, column)}, {_signed(last.change)}"
                     f"{_percent(last.percent)} compared with {last.previous_period}.")
        rise = max(changes, key=lambda c: c.change)
        fall = min(changes, key=lambda c: c.change)
        if rise.change > 0:
            found.append(f"Largest increase: {rise.previous_period} → {rise.period} ({_signed(rise.change)}).")
        if fall.change < 0:
            found.append(f"Largest decrease: {fall.previous_period} → {fall.period} ({_signed(fall.change)}).")
    elif base is not None:
        metric, values = humanize(base.y), data[base.y].astype(float)
        total = values.sum()
        if (values >= 0).all() and total > 0 and len(data) > 1:
            ranked = data.sort_values(base.y, ascending=False)
            top = ranked.iloc[0]
            found.append(f"{top[base.x]} accounts for {top[base.y] / total:.1%} of the total {metric} in this "
                         f"result ({_fmt(total, data[base.y])}).")
            if len(data) > 3:
                top3 = ranked[base.y].head(3).sum()
                found.append(f"The 3 largest together account for {top3 / total:.1%} of that total.")
        ranked = data.sort_values(base.y, ascending=False)[base.y]
        if len(data) > 1 and ranked.iloc[0] > 0 and ranked.iloc[1] > 0:
            found.append(f"The highest {metric} is {ranked.iloc[0] / ranked.iloc[1]:.2f}× the second highest.")

    for stats in statistics(data):
        if stats.count >= 2:
            column = data[stats.column]
            found.append(f"{humanize(stats.column).capitalize()}: average {format_value(round(stats.mean, 2))}, "
                         f"median {_fmt(stats.median, column)}, range {_fmt(stats.minimum, column)} "
                         f"to {_fmt(stats.maximum, column)}.")
        outliers = find_outliers(data[stats.column])
        if outliers:
            values = data[stats.column]
            outside = data[(values < outliers.low) | (values > outliers.high)]
            names = outside[base.x].astype(str).tolist() if base is not None else []
            listed = f": {', '.join(names[:5])}" if names else ""
            found.append(f"Possible outliers in {humanize(stats.column)} ({outliers.count} outside "
                         f"{format_value(round(outliers.low, 2))} to {format_value(round(outliers.high, 2))}){listed}.")
    if truncated:
        found.append(f"These figures describe the {len(data):,} rows shown, not the full result.")
    return found


# --- Follow-up questions ----------------------------------------------------------------

def follow_ups(data: pd.DataFrame, source: str, asked: list[str]) -> list[str]:
    """Questions that naturally follow this result. They are only suggestions: clicking one
    asks it through the normal pipeline, where it is validated like any other question."""
    seen = {q.strip().lower() for q in asked}
    if source == "demo":
        candidates = demo_queries.demo_questions()
    elif source == "ai":
        candidates = _templates(data)
    else:
        return []
    return [q for q in candidates if q.lower() not in seen][:MAX_FOLLOW_UPS]


def _templates(data: pd.DataFrame) -> list[str]:
    base = insights.choose_chart(data)
    if base is None:
        return []
    label, metric = humanize(base.x), humanize(base.y)
    if base.kind == "line":
        unit = "month" if len(str(data[base.x].iloc[0])) == 7 else "day"
        return [f"Which {unit} had the highest {metric}?",
                f"How much did {metric} change from each {unit} to the next?",
                f"What was the average {metric} per {unit}?"]
    return [f"Which {label} has the lowest {metric}?",
            f"What share of the total {metric} does each {label} have?",
            f"What are the top 3 {label} values by {metric}?"]
