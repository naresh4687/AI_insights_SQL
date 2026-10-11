"""Reusable pieces shared by the pages."""

import functools
import re
from datetime import datetime

import streamlit as st

from src import analysis, export, insights, sql_explain
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
    hint = sql_explain.explain_error(message, session.dataset(turn.dataset_id))
    if hint:
        st.caption(f":material/lightbulb: {md_escape(hint)}")


def answer_body(turn: session.Turn, key: str, follow_ups: list[str] | None = None) -> None:
    """Answer, results, visualization, SQL and insights for a successful turn; a safe message
    otherwise. ``follow_ups`` are offered as buttons that ask through the normal pipeline.

    New widget keys put ``key`` last (e.g. ``download_turn_0``): keys starting with ``turn_``
    or ``chart_`` are matched by page CSS and tests."""
    status_line(turn)
    if turn.error:
        error_message(turn)
        return

    answer = turn.answer
    st.markdown(md_escape(insights.explain(answer.data, answer.truncated)))
    st.caption(f"Dataset: {md_escape(turn.dataset_name)} · SQL source: {session.source_label(answer.source)}")

    results, visual, sql, more = st.tabs([":material/table_chart: Results", ":material/bar_chart: Visualization",
                                          ":material/code: SQL", ":material/insights: Insights"])
    with results:
        if answer.data.empty:
            st.caption("The query returned no rows.")
        else:
            st.dataframe(answer.data, hide_index=True, width="stretch",
                         alt=f"Query result with {len(answer.data)} rows")
            st.download_button(
                # A callable: the file is made when clicked, so no stale file is left to 404 after reruns.
                "Download CSV", data=functools.partial(export.to_csv, answer.data),
                file_name=export.file_name(turn.dataset_name),
                mime="text/csv", key=f"download_{key}", icon=":material/download:", on_click="ignore",
                help="The rows shown above. Text a spreadsheet could run as a formula is made safe.")
    with visual:
        _visualization(answer.data, key)
    with sql:
        st.caption("Validated SQL that was run (read-only). Use the copy button to reuse it.")
        st.code(answer.sql, language="sql", wrap_lines=True)
        st.markdown("**What this query does**")
        st.markdown("\n".join(f"- {md_escape(step)}" for step in sql_explain.explain_sql(answer.sql)))
    with more:
        _insights(answer.data, answer.truncated)
    if not answer.data.empty:
        _add_to_dashboard(turn, key)

    if follow_ups:
        st.caption("Follow-up questions (each is answered and validated like any question)")
        with st.container(key=f"followups_{key}", horizontal=True, wrap=True, gap="small"):
            for i, question in enumerate(follow_ups):
                st.button(question, key=f"followup_{key}_{i}", icon=":material/subdirectory_arrow_right:",
                          on_click=session.queue_question, args=(question, turn.source))


def _add_to_dashboard(turn: session.Turn, key: str) -> None:
    """Save this answer's validated SQL, dataset and chosen chart type to a dashboard."""
    from src import accounts, dashboards  # imported here: only needed on demand
    user = session.current_user()
    if not user.can_create:
        return  # viewers cannot build dashboards
    with st.popover("Add to dashboard", icon=":material/dashboard_customize:", key=f"adddash_{key}"):
        saved = [d for d in dashboards.store().list(user) if accounts.can_change(user, d.owner)]
        names = {d.dashboard_id: d.name for d in saved}
        chosen = st.selectbox("Dashboard", ["__new__", *names], key=f"adddash_target_{key}",
                              format_func=lambda d: "New dashboard…" if d == "__new__" else names[d])
        new_name = st.text_input("New dashboard name", key=f"adddash_name_{key}") if chosen == "__new__" else None
        title = st.text_input("Chart title", value=turn.question[:dashboards.MAX_TITLE_LENGTH],
                              key=f"adddash_title_{key}")
        width = st.selectbox("Width", list(dashboards.WIDTHS), format_func=dashboards.WIDTHS.get, index=1,
                             key=f"adddash_width_{key}")
        if st.button("Add", type="primary", key=f"adddash_add_{key}"):
            options = analysis.chart_options(turn.answer.data)
            index = st.session_state.get(f"charttype_{key}") or 0
            kind = options[index].kind if index < len(options) else (options[0].kind if options else "bar")
            try:
                store = dashboards.store()
                if chosen == "__new__":
                    dashboard = store.create(new_name or "", owner=accounts.owner_of(user))
                    session.record("dashboard.created", "dashboard", dashboard.dashboard_id, dashboard.name)
                else:
                    dashboard = store.get(chosen)
                    if dashboard is None or not accounts.can_change(user, dashboard.owner):
                        raise dashboards.DashboardError("This dashboard is not available.")
                store.add_widget(dashboard.dashboard_id, title, turn.question, turn.dataset_id, turn.answer.sql,
                                 kind, width, demo_db=session.db_path(), user=user)
            except dashboards.DashboardError as exc:
                st.error(md_escape(exc.message), icon=":material/error:")
            else:
                session.record("dashboard.chart_added", "dashboard", dashboard.dashboard_id, title)
                st.success(f"Added to '{md_escape(dashboard.name)}'. Open it in Dashboard Studio.",
                           icon=":material/check_circle:")


def _visualization(data, key: str) -> None:
    options = analysis.chart_options(data)
    if not options:
        st.caption("No chart: this result is not suited to a simple chart.")
        return
    choice = options[0]
    if len(options) > 1:
        picked = st.segmented_control("Chart type", list(range(len(options))), default=0, required=True,
                                      format_func=lambda i: options[i].label, key=f"charttype_{key}")
        choice = options[picked if picked is not None else 0]
    if choice.kind == "kpi":
        st.caption("Shown as figures: a single row is not suited to a simple chart.")
        numbers = analysis.numeric_columns(data)
        for column, name in zip(st.columns(len(numbers)), numbers):
            column.metric(insights.humanize(name).capitalize(), insights.format_value(data[name].iloc[0]))
        return
    chart = charts.build(choice, data)
    parts = [insights.humanize(c) for c in (choice.y, choice.x) if c]
    charts.show(chart, f"{choice.label} chart of {' by '.join(parts)}", key=f"{key}_chart")


def _insights(data, truncated: bool) -> None:
    found = analysis.facts(data, truncated)
    if found:
        st.markdown("\n".join(f"- {md_escape(fact)}" for fact in found))
    else:
        st.caption("No further facts to report for this result.")
    stats = analysis.statistics(data)
    if stats:
        st.caption("Statistics of the numeric columns (computed from the rows shown)")
        header = "| Column | Values | Empty | Total | Average | Median | Min | Max | Std. dev. |\n|---|---:|---:|---:|---:|---:|---:|---:|---:|"
        rows = [f"| {md_escape(s.column)} | {s.count:,} | {s.missing:,} | {s.total:,.2f} | {s.mean:,.2f} | "
                f"{s.median:,.2f} | {s.minimum:,.2f} | {s.maximum:,.2f} | "
                f"{'—' if s.std is None else f'{s.std:,.2f}'} |" for s in stats]
        st.markdown("\n".join([header, *rows]))
