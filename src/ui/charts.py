"""Altair charts in the InsightSQL theme. Every chart is built from a query result DataFrame;
nothing is computed or invented here."""

import altair as alt
import pandas as pd
import streamlit as st

from src import insights
from src.ui.theme import CHART_COLORS, chart_config

PRIMARY, SECONDARY = CHART_COLORS[0], CHART_COLORS[1]  # readable on both themes


def _number_format(series: pd.Series) -> str:
    return ",.2f" if pd.api.types.is_float_dtype(series) else ",d"


def bar(data: pd.DataFrame, label: str, value: str, title: str | None = None, color: str | None = None) -> alt.Chart:
    """Horizontal bars sorted largest first (labels stay readable at any width)."""
    label_title, value_title = insights.humanize(label).capitalize(), insights.humanize(value).capitalize()
    chart = alt.Chart(data, title=title or alt.Undefined).mark_bar(
        color=color or PRIMARY, cornerRadiusEnd=4, height={"band": 0.7}
    ).encode(
        y=alt.Y(f"{label}:N", sort="-x", title=label_title),
        x=alt.X(f"{value}:Q", title=value_title, axis=alt.Axis(format="~s")),
        tooltip=[
            alt.Tooltip(f"{label}:N", title=label_title),
            alt.Tooltip(f"{value}:Q", title=value_title, format=_number_format(data[value])),
        ],
    )
    return chart.properties(height=max(160, 34 * len(data) + 40)).configure(**chart_config())


def line(data: pd.DataFrame, period: str, value: str, title: str | None = None) -> alt.Chart:
    """Values over time: straight segments between the real data points (no smoothing,
    which could exaggerate peaks), with a dot on every period."""
    period_title, value_title = insights.humanize(period).capitalize(), insights.humanize(value).capitalize()
    chart = alt.Chart(data, title=title or alt.Undefined).mark_line(
        color=PRIMARY, strokeWidth=2.5,
        point=alt.OverlayMarkDef(color=PRIMARY, size=55, filled=True),
    ).encode(
        x=alt.X(f"{period}:O", title=period_title, axis=alt.Axis(labelAngle=-40)),
        y=alt.Y(f"{value}:Q", title=value_title, axis=alt.Axis(format="~s")),
        tooltip=[
            alt.Tooltip(f"{period}:O", title=period_title),
            alt.Tooltip(f"{value}:Q", title=value_title, format=_number_format(data[value])),
        ],
    )
    return chart.properties(height=280).configure(**chart_config())


def result_chart(data: pd.DataFrame) -> alt.Chart | None:
    """A chart for a query result, or None when ``insights.choose_chart`` finds it unsuitable."""
    spec = insights.choose_chart(data)
    if spec is None:
        return None
    if spec.kind == "line":
        return line(data, spec.x, spec.y)
    return bar(data, spec.x, spec.y)


def show(chart: alt.Chart, description: str, key: str | None = None) -> None:
    """Render with the app's colours (not Streamlit's chart theme) and alt text."""
    st.altair_chart(chart, width="stretch", theme=None, key=key, alt=description)


# --- More chart types (chosen in the Visualization tab) --------------------------------

def _titles(*columns: str) -> list[str]:
    return [insights.humanize(c).capitalize() for c in columns]


def column(data: pd.DataFrame, label: str, value: str) -> alt.Chart:
    """Vertical bars. Periods keep their order; categories are sorted largest first."""
    label_title, value_title = _titles(label, value)
    sort = None if insights.is_period_column(data[label]) else "-y"
    chart = alt.Chart(data).mark_bar(color=PRIMARY, cornerRadiusEnd=4).encode(
        x=alt.X(f"{label}:N", sort=sort, title=label_title, axis=alt.Axis(labelAngle=-40)),
        y=alt.Y(f"{value}:Q", title=value_title, axis=alt.Axis(format="~s")),
        tooltip=[alt.Tooltip(f"{label}:N", title=label_title),
                 alt.Tooltip(f"{value}:Q", title=value_title, format=_number_format(data[value]))],
    )
    return chart.properties(height=300).configure(**chart_config())


def area(data: pd.DataFrame, period: str, value: str) -> alt.Chart:
    period_title, value_title = _titles(period, value)
    chart = alt.Chart(data).mark_area(
        color=PRIMARY, opacity=0.35, line={"color": PRIMARY, "strokeWidth": 2},
    ).encode(
        x=alt.X(f"{period}:O", title=period_title, axis=alt.Axis(labelAngle=-40)),
        y=alt.Y(f"{value}:Q", title=value_title, axis=alt.Axis(format="~s")),
        tooltip=[alt.Tooltip(f"{period}:O", title=period_title),
                 alt.Tooltip(f"{value}:Q", title=value_title, format=_number_format(data[value]))],
    )
    return chart.properties(height=280).configure(**chart_config())


def pie(data: pd.DataFrame, label: str, value: str, donut: bool = False) -> alt.Chart:
    """Parts of a whole (only offered for a few non-negative values)."""
    label_title, value_title = _titles(label, value)
    # The slice gap is white here; CSS sets it to the page background of the current theme.
    chart = alt.Chart(data).mark_arc(innerRadius=70 if donut else 0, stroke="#FFFFFF", strokeWidth=2).encode(
        theta=alt.Theta(f"{value}:Q", stack=True),
        color=alt.Color(f"{label}:N", title=label_title, sort=alt.SortField(value, order="descending")),
        order=alt.Order(f"{value}:Q", sort="descending"),
        tooltip=[alt.Tooltip(f"{label}:N", title=label_title),
                 alt.Tooltip(f"{value}:Q", title=value_title, format=_number_format(data[value]))],
    )
    return chart.properties(height=300).configure(**chart_config())


def scatter(data: pd.DataFrame, x: str, y: str) -> alt.Chart:
    x_title, y_title = _titles(x, y)
    tooltip = [alt.Tooltip(f"{c}:N") for c in data.columns if c not in (x, y)][:2] + [
        alt.Tooltip(f"{x}:Q", title=x_title, format=_number_format(data[x])),
        alt.Tooltip(f"{y}:Q", title=y_title, format=_number_format(data[y]))]
    chart = alt.Chart(data).mark_circle(color=PRIMARY, size=70, opacity=0.8).encode(
        x=alt.X(f"{x}:Q", title=x_title, axis=alt.Axis(format="~s")),
        y=alt.Y(f"{y}:Q", title=y_title, axis=alt.Axis(format="~s")),
        tooltip=tooltip,
    )
    return chart.properties(height=300).configure(**chart_config())


def histogram(data: pd.DataFrame, value: str) -> alt.Chart:
    (value_title,) = _titles(value)
    chart = alt.Chart(data).mark_bar(color=PRIMARY).encode(
        x=alt.X(f"{value}:Q", bin=alt.Bin(maxbins=20), title=value_title),
        y=alt.Y("count():Q", title="Number of rows"),
        tooltip=[alt.Tooltip(f"{value}:Q", bin=alt.Bin(maxbins=20), title=value_title),
                 alt.Tooltip("count():Q", title="Rows")],
    )
    return chart.properties(height=280).configure(**chart_config())


def box(data: pd.DataFrame, value: str, group: str | None = None) -> alt.Chart:
    """Spread of values (median, quartiles, whiskers at 1.5 × IQR), optionally per group."""
    (value_title,) = _titles(value)
    encoding = {"y": alt.Y(f"{value}:Q", title=value_title, axis=alt.Axis(format="~s"))}
    if group:
        encoding["x"] = alt.X(f"{group}:N", title=_titles(group)[0], axis=alt.Axis(labelAngle=-40))
    chart = alt.Chart(data).mark_boxplot(color=PRIMARY, extent=1.5, size=40).encode(**encoding)
    return chart.properties(height=300).configure(**chart_config())


def build(spec, data: pd.DataFrame) -> alt.Chart | None:
    """The Altair chart for an ``analysis.Chart`` (None for KPI cards, drawn with st.metric)."""
    if spec.kind == "bar":
        return bar(data, spec.x, spec.y)
    if spec.kind == "line":
        return line(data, spec.x, spec.y)
    if spec.kind == "column":
        return column(data, spec.x, spec.y)
    if spec.kind == "area":
        return area(data, spec.x, spec.y)
    if spec.kind in ("pie", "donut"):
        return pie(data, spec.x, spec.y, donut=spec.kind == "donut")
    if spec.kind == "scatter":
        return scatter(data, spec.x, spec.y)
    if spec.kind == "histogram":
        return histogram(data, spec.x)
    if spec.kind == "box":
        return box(data, spec.y, spec.x)
    if spec.kind == "kpi":
        return None
    raise ValueError(f"Unknown chart kind: {spec.kind}")
