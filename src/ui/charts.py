"""Altair charts in the InsightSQL theme. Every chart is built from a query result DataFrame;
nothing is computed or invented here."""

import altair as alt
import pandas as pd
import streamlit as st

from src import insights
from src.ui.theme import COLORS, chart_config


def _number_format(series: pd.Series) -> str:
    return ",.2f" if pd.api.types.is_float_dtype(series) else ",d"


def bar(data: pd.DataFrame, label: str, value: str, title: str | None = None, color: str | None = None) -> alt.Chart:
    """Horizontal bars sorted largest first (labels stay readable at any width)."""
    label_title, value_title = insights.humanize(label).capitalize(), insights.humanize(value).capitalize()
    chart = alt.Chart(data, title=title or alt.Undefined).mark_bar(
        color=color or COLORS["violet"], cornerRadiusEnd=4, height={"band": 0.7}
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
        color=COLORS["cyan"], strokeWidth=2.5,
        point=alt.OverlayMarkDef(color=COLORS["cyan"], size=55, filled=True),
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
