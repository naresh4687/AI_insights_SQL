"""Dashboard Studio: build dashboards from saved answers, filter them, arrange them, export them.

Each chart runs its validated SQL again for its own dataset whenever the page is shown
(``src.dashboards.run``), so the data is current and limited to what the dataset allows.

Access: the list holds the user's own dashboards and those shared with everyone. Only the owner
(and administrators) see the editing controls; a chart runs only if the viewer may read its dataset.
"""

import calendar
import functools
from datetime import date, datetime

import streamlit as st

from src import accounts, analysis, dashboards, export, insights
from src.sync import refresh as sync
from src.ui import charts, components, session, theme


def render() -> None:
    theme.page_header("Analyze", "Dashboard Studio",
                      "Your own dashboards, built from AI Analyst answers. Every chart re-runs its validated, "
                      "read-only query on its dataset when the page loads.")
    notice = st.session_state.pop("studio_notice", None)
    if notice:
        st.success(components.md_escape(notice), icon=":material/check_circle:")
    store = dashboards.store()
    user = session.current_user()
    saved = store.list(user)
    if not saved:
        if user.can_create:
            theme.empty_state("No dashboards yet", "Ask a question in the AI Analyst, then use “Add to dashboard” "
                                                   "under the answer. Or create an empty dashboard here.")
            _create(store)
        else:
            theme.empty_state("No dashboards shared with you yet",
                              "Dashboards that others share with everyone appear here.")
        return

    names = {d.dashboard_id: d.name for d in saved}
    if st.session_state.get("studio_dash_next") in names:
        st.session_state["studio_dash"] = st.session_state.pop("studio_dash_next")
    if st.session_state.get("studio_dash") not in names:
        st.session_state["studio_dash"] = next(iter(names))
    chosen = st.selectbox("Dashboard", list(names), format_func=names.get, key="studio_dash")
    dashboard = store.get(chosen)
    demo_db = session.db_path()
    mine = session.can_change(dashboard.owner)
    _ownership(dashboard, mine)

    filters = list(dashboard.filters)
    unfiltered = [dashboards.run(w, demo_db, user=user) for w in dashboard.widgets]
    values = _filter_bar(filters, unfiltered)
    results = [dashboards.run(w, demo_db, values, user=user) for w in dashboard.widgets] if any(
        _is_set(v) for _, v in values) else unfiltered

    editing = _toolbar(store, dashboard, results, mine)
    if not dashboard.widgets:
        theme.empty_state("This dashboard is empty", "Use “Add to dashboard” under an AI Analyst answer.")
    for row in dashboards.layout(dashboard.widgets):
        units = [dashboards.WIDTH_UNITS[w.width] for w in row]
        spare = 6 - sum(units)
        columns = st.columns(units + ([spare] if spare else []))
        for column, widget in zip(columns, row):
            with column:
                _widget(store, next(r for r in results if r.widget.widget_id == widget.widget_id), editing)
    st.caption(f"Data as of {datetime.now().strftime('%H:%M:%S')}. Charts query the latest stored data of their "
               "datasets; use “Refresh source data” to fetch new data from connections first.")
    if mine:
        _manage(store, dashboard, unfiltered)
    elif user.can_create:
        with st.expander("Make your own copy", icon=":material/content_copy:"):
            _duplicate(store, dashboard)


def _ownership(dashboard, mine: bool) -> None:
    if not session.signed_in():
        return
    if dashboard.owner == session.current_user().user_id:
        text = "Yours · shared with everyone (read-only)" if dashboard.shared else "Yours · only you can see it"
    else:
        owner = _owner_label(dashboard.owner)
        text = f"Shared by {owner} · read-only" if not mine else f"Owned by {owner} · you can change it as an admin"
    st.caption(components.md_escape(text))


def _owner_label(user_id: str | None) -> str:
    owner = accounts.store().get(user_id) if user_id else None
    return owner.label if owner else "no current account"


def _create(store: dashboards.DashboardStore) -> None:
    with st.container(border=True, key="card_studio_create"):
        name = st.text_input("New dashboard name", key="studio_new_name")
        if st.button("Create dashboard", type="primary", icon=":material/add:", key="studio_create"):
            try:
                created = store.create(name, owner=accounts.owner_of(session.current_user()))
            except dashboards.DashboardError as exc:
                st.error(components.md_escape(exc.message), icon=":material/error:")
            else:
                session.record("dashboard.created", "dashboard", created.dashboard_id, created.name)
                _done(f"Created '{created.name}'.", created.dashboard_id)


def _done(message: str, select: str | None = None) -> None:
    st.session_state["studio_notice"] = message
    if select:
        st.session_state["studio_dash_next"] = select
    st.rerun()


def _is_set(value) -> bool:
    return bool(value) and (not isinstance(value, tuple) or all(v is not None for v in value))


# --- Filters ---------------------------------------------------------------------------

def _filter_bar(filters, results) -> list:
    if not filters:
        return []
    values = []
    with st.container(border=True, key="card_studio_filters"):
        st.markdown("**Filters**")
        columns = st.columns(min(len(filters), 3))
        for i, flt in enumerate(filters):
            with columns[i % len(columns)]:
                values.append((flt, _filter_widget(flt, dashboards.choices(flt, results))))
    return values


def _filter_widget(flt, options):
    key = f"studio_filter_{flt.filter_id}"
    if options is None:
        st.caption(f"{flt.label}: no chart on this dashboard has a matching column.")
        return None
    if flt.kind == "category":
        return st.multiselect(flt.label, options, key=key, placeholder="All")
    if flt.kind == "number":
        low, high = options
        if low == high:
            st.caption(f"{flt.label}: every value is {insights.format_value(low)}.")
            return None
        chosen = st.slider(flt.label, low, high, (low, high), key=key)
        return chosen if chosen != (low, high) else None
    first, last = _day(options[0], end=False), _day(options[1], end=True)
    chosen = st.date_input(flt.label, (first, last), min_value=first, max_value=last, key=key)
    if isinstance(chosen, tuple) and len(chosen) == 2 and chosen != (first, last):
        return chosen[0].isoformat(), chosen[1].isoformat()
    return None


def _day(text: str, end: bool) -> date:
    """A day from YYYY, YYYY-MM or YYYY-MM-DD (the first or last day of the period)."""
    parts = [int(p) for p in text[:10].split("-")]
    year = parts[0]
    month = parts[1] if len(parts) > 1 else (12 if end else 1)
    day = parts[2] if len(parts) > 2 else (calendar.monthrange(year, month)[1] if end else 1)
    return date(year, month, day)


# --- Toolbar and management ------------------------------------------------------------

def _toolbar(store, dashboard, results, mine: bool) -> bool:
    left, middle, right, last = st.columns([1, 1, 1, 1], vertical_alignment="center")
    if left.button("Refresh data", icon=":material/refresh:", key="studio_rerun", width="stretch"):
        st.rerun()
    # Only datasets this user may refresh (their own, or any for an admin).
    sources = sorted({w.dataset_id for w in dashboard.widgets
                      if (d := session.dataset(w.dataset_id)) is not None and sync.source_of(d)
                      and session.can_change(d.owner)})
    if middle.button("Refresh source data", icon=":material/sync:", key="studio_sync", width="stretch",
                     disabled=not sources, help="Fetch new data from the connections these charts use."):
        with st.spinner("Refreshing the source datasets…"):
            outcomes = [(d, sync.refresh(d)) for d in sources]
        for d, r in outcomes:
            session.record("dataset.refreshed", "dataset", d, r.status)
        failed = [f"{d}: {r.message}" for d, r in outcomes if r.status == "failed"]
        message = f"Refreshed {sum(r.status == 'success' for _, r in outcomes)} of {len(outcomes)} source datasets."
        if failed:
            st.session_state["studio_sync_errors"] = failed
        _done(message)
    for error in st.session_state.pop("studio_sync_errors", []):
        st.error(components.md_escape(error), icon=":material/error:")
    editing = right.toggle("Edit layout", key="studio_edit", disabled=not mine,
                           help=None if mine else "Only the owner can change this dashboard.") and mine
    last.download_button("Export (JSON)", data=functools.partial(dashboards.export_json, dashboard.dashboard_id),
                         file_name=f"dashboard_{dashboard.dashboard_id}.json", mime="application/json",
                         icon=":material/data_object:", key="studio_export", on_click="ignore", width="stretch",
                         help="The dashboard's definition (charts, SQL, filters), without data.")
    return editing


def _widget(store, result: dashboards.WidgetResult, editing: bool) -> None:
    widget = result.widget
    with st.container(border=True, key=f"card_dw_{widget.widget_id}"):
        st.markdown(f"**{components.md_escape(widget.title)}**")
        dataset = session.dataset(widget.dataset_id)
        meta = [f"Dataset: {dataset.name if dataset else widget.dataset_id}"]
        if result.applied:
            meta.append("Filtered by " + ", ".join(result.applied))
        st.caption(components.md_escape(" · ".join(meta)))
        if result.error:
            st.error(components.md_escape(result.error), icon=":material/error:")
        elif result.data.empty:
            st.caption("No rows for the current filters.")
        elif result.chart is None:
            st.dataframe(result.data, hide_index=True, width="stretch")
        elif result.chart.kind == "kpi":
            numbers = analysis.numeric_columns(result.data)
            for column, name in zip(st.columns(len(numbers)), numbers):
                column.metric(insights.humanize(name).capitalize(), insights.format_value(result.data[name].iloc[0]))
        else:
            charts.show(charts.build(result.chart, result.data), f"{result.chart.label} chart: {widget.title}",
                        key=f"dwchart_{widget.widget_id}")
        if result.note:
            st.caption(components.md_escape(result.note))
        if result.truncated:
            st.caption("Only the first 1,000 rows are shown.")
        if result.data is not None and not result.data.empty:
            with st.expander("Data and SQL"):
                st.dataframe(result.data, hide_index=True, width="stretch")
                st.code(widget.sql, language="sql", wrap_lines=True)
                st.download_button("Download CSV", data=functools.partial(export.to_csv, result.data),
                                   file_name=export.file_name(widget.title), mime="text/csv", on_click="ignore",
                                   key=f"dwcsv_{widget.widget_id}", icon=":material/download:")
        if editing:
            _edit_widget(store, result)


def _edit_widget(store, result) -> None:
    widget = result.widget
    wid = widget.widget_id
    title = st.text_input("Title", value=widget.title, key=f"dwtitle_{wid}")
    left, right = st.columns(2)
    width = left.selectbox("Width", list(dashboards.WIDTHS), format_func=dashboards.WIDTHS.get,
                           index=list(dashboards.WIDTHS).index(widget.width), key=f"dwwidth_{wid}")
    options = analysis.chart_options(result.data) if result.data is not None else []
    kinds = list(dict.fromkeys(o.kind for o in options)) or [widget.chart_kind]
    kind = right.selectbox("Chart type", kinds, format_func=analysis.CHART_LABELS.get,
                           index=kinds.index(widget.chart_kind) if widget.chart_kind in kinds else 0,
                           key=f"dwkind_{wid}")
    up, down, save, remove = st.columns(4)
    if up.button("", icon=":material/arrow_upward:", key=f"dwup_{wid}", help="Move earlier", width="stretch"):
        store.move_widget(wid, -1)
        st.rerun()
    if down.button("", icon=":material/arrow_downward:", key=f"dwdown_{wid}", help="Move later", width="stretch"):
        store.move_widget(wid, 1)
        st.rerun()
    if save.button("", icon=":material/save:", key=f"dwsave_{wid}", help="Save title, width and chart type",
                   width="stretch"):
        try:
            store.update_widget(wid, title=title, width=width, chart_kind=kind)
        except dashboards.DashboardError as exc:
            st.error(components.md_escape(exc.message), icon=":material/error:")
        else:
            session.record("dashboard.chart_changed", "dashboard", widget.dashboard_id, title)
            _done(f"Saved '{title}'.")
    if remove.button("", icon=":material/delete:", key=f"dwremove_{wid}", help="Remove from the dashboard",
                     width="stretch"):
        store.remove_widget(wid)
        session.record("dashboard.chart_removed", "dashboard", widget.dashboard_id, widget.title)
        _done(f"Removed '{widget.title}'.")


def _manage(store, dashboard, results) -> None:
    with st.expander("Manage this dashboard", icon=":material/settings:"):
        st.markdown("**Filters**")
        columns = sorted({c for r in results if r.unfiltered is not None for c in r.unfiltered.columns})
        left, middle, right = st.columns([2, 2, 1], vertical_alignment="bottom")
        kind = left.selectbox("Filter type", list(dashboards.FILTER_KINDS), format_func=dashboards.FILTER_KINDS.get,
                              key="studio_filter_kind")
        column = middle.selectbox("Column", columns or ["—"], key="studio_filter_column", disabled=not columns)
        if right.button("Add filter", key="studio_add_filter", disabled=not columns, width="stretch"):
            try:
                store.add_filter(dashboard.dashboard_id, kind, column)
            except dashboards.DashboardError as exc:
                st.error(components.md_escape(exc.message), icon=":material/error:")
            else:
                session.record("dashboard.filter_added", "dashboard", dashboard.dashboard_id, f"{kind} on {column}")
                _done(f"Added a {dashboards.FILTER_KINDS[kind].lower()} filter on {column}.")
        for flt in dashboard.filters:
            label, remove = st.columns([4, 1], vertical_alignment="center")
            label.markdown(f"- {components.md_escape(flt.label)} ({dashboards.FILTER_KINDS[flt.kind].lower()})")
            if remove.button("Remove", key=f"studio_rmfilter_{flt.filter_id}", width="stretch"):
                store.remove_filter(flt.filter_id)
                session.record("dashboard.filter_removed", "dashboard", dashboard.dashboard_id, flt.label)
                _done(f"Removed the filter '{flt.label}'.")

        if session.signed_in():
            _share(store, dashboard)
        st.markdown("**Rename, duplicate or delete**")
        name = st.text_input("Name", value=dashboard.name, key=f"studio_rename_{dashboard.dashboard_id}")
        rename, copy, delete = st.columns(3)
        if rename.button("Rename", key="studio_rename", width="stretch"):
            try:
                store.rename(dashboard.dashboard_id, name)
            except dashboards.DashboardError as exc:
                st.error(components.md_escape(exc.message), icon=":material/error:")
            else:
                session.record("dashboard.renamed", "dashboard", dashboard.dashboard_id, f"{dashboard.name} → {name}")
                _done(f"Renamed to '{name}'.")
        with copy:
            _duplicate(store, dashboard)
        confirm = delete.checkbox("Confirm delete", key=f"studio_delete_ok_{dashboard.dashboard_id}")
        if delete.button("Delete", key="studio_delete", disabled=not confirm, width="stretch"):
            store.delete(dashboard.dashboard_id)
            session.record("dashboard.deleted", "dashboard", dashboard.dashboard_id, dashboard.name)
            _done(f"Deleted '{dashboard.name}'.")
        if session.current_user().can_create:
            st.markdown("**New dashboard**")
            _create(store)


def _duplicate(store, dashboard) -> None:
    if st.button("Duplicate", key="studio_duplicate", width="stretch",
                 disabled=not session.current_user().can_create):
        try:
            created = store.duplicate(dashboard.dashboard_id, store.free_name(f"{dashboard.name} (copy)"),
                                      owner=accounts.owner_of(session.current_user()))
        except dashboards.DashboardError as exc:
            st.error(components.md_escape(exc.message), icon=":material/error:")
        else:
            session.record("dashboard.duplicated", "dashboard", created.dashboard_id,
                           f"from {dashboard.dashboard_id}")
            _done(f"Created '{created.name}'.", created.dashboard_id)


def _share(store, dashboard) -> None:
    st.markdown("**Sharing**")
    shared = st.toggle("Share with everyone who signs in (read-only)", value=dashboard.shared,
                       key=f"studio_share_{dashboard.dashboard_id}")
    if shared != dashboard.shared:
        store.set_shared(dashboard.dashboard_id, shared)
        session.record("dashboard.shared" if shared else "dashboard.unshared", "dashboard", dashboard.dashboard_id,
                       dashboard.name)
        _done("Shared with everyone." if shared else "No longer shared.")
    private = sorted({d.name for w in dashboard.widgets if (d := session.dataset(w.dataset_id)) is not None
                      and not (d.shared or d.builtin)})
    if dashboard.shared and private:
        st.caption(components.md_escape(
            "Others see these charts only after their datasets are shared too (Datasets page): " + ", ".join(private)))
