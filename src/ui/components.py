"""Reusable pieces shared by the pages."""

import re
from datetime import datetime

import streamlit as st

from src import insights
from src.ui import charts, session, theme

# Characters that start Markdown formatting (links, emphasis, code, HTML, tables, maths).
_MARKDOWN_SPECIAL = re.compile(r"([\\`*_\[\]<>#|~$])")


def md_escape(text: str) -> str:
    """Show database text literally in Markdown (product names cannot inject formatting)."""
    return _MARKDOWN_SPECIAL.sub(r"\\\1", text)


def format_time(iso_timestamp: str) -> str:
    """'2026-10-10T10:24:19+00:00' -> '2026-10-10 10:24 UTC' (history is stored in UTC)."""
    try:
        return datetime.fromisoformat(iso_timestamp).strftime("%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError):
        return str(iso_timestamp)


def status_line(turn: session.Turn) -> None:
    """Badge plus measured facts about the run."""
    if turn.error:
        kind = "rejected" if turn.error[0] == "rejected" else "error"
        st.html(theme.badge(kind))
        return
    answer = turn.answer
    rows = f"{len(answer.data):,} row{'s' if len(answer.data) != 1 else ''}"
    st.html(f'{theme.badge("success")} <span class="isql-meta">&nbsp;{rows} · {turn.seconds:.2f} s</span>')


def error_message(turn: session.Turn) -> None:
    status, message = turn.error
    prefix = "Request rejected" if status == "rejected" else "Query failed"
    st.error(f"**{prefix}:** {md_escape(message)}", icon=":material/error:" if status != "rejected" else ":material/block:")


def answer_body(turn: session.Turn, key: str) -> None:
    """Answer, results, visualization and SQL for a successful turn; a safe message otherwise."""
    status_line(turn)
    if turn.error:
        error_message(turn)
        return

    answer = turn.answer
    st.markdown(md_escape(insights.explain(answer.data, answer.truncated)))
    st.caption(f"SQL source: {session.source_label(answer.source)}")

    results, visual, sql = st.tabs([":material/table_chart: Results", ":material/bar_chart: Visualization",
                                    ":material/code: SQL"])
    with results:
        if answer.data.empty:
            st.caption("The query returned no rows.")
        else:
            st.dataframe(answer.data, hide_index=True, width="stretch",
                         alt=f"Query result with {len(answer.data)} rows")
    with visual:
        chart = charts.result_chart(answer.data)
        if chart is None:
            st.caption("No chart: this result is not suited to a simple chart.")
        else:
            charts.show(chart, f"Chart of {insights.humanize(answer.data.columns[1])} "
                               f"by {insights.humanize(answer.data.columns[0])}", key=f"{key}_chart")
    with sql:
        st.caption("Validated SQL that was run (read-only). Use the copy button to reuse it.")
        st.code(answer.sql, language="sql", wrap_lines=True)
