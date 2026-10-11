"""Datasets: every queryable dataset, where it came from, its columns, and how it is refreshed.

Refreshing (now or on a schedule) is done by ``src.sync.refresh``; scheduled refreshes run when
``scripts/refresh_worker.py`` runs. A failed refresh never replaces the last good data.

Access: the list holds the built-in data, the user's own datasets and those shared with everyone.
Only the owner (and administrators) can share, refresh or change refresh settings.
"""

import pandas as pd
import streamlit as st

from src import accounts, data_access
from src.core.models import Storage
from src.sync import refresh as sync
from src.sync.state import MODES, RefreshSettings
from src.ui import components, session, theme

SCHEDULES = {None: "Manual only", 15: "Every 15 minutes", 60: "Every hour", 360: "Every 6 hours",
             1440: "Every day", 10080: "Every week"}
STATUS_BADGES = {"success": "success", "failed": "error", "skipped": "muted", "running": "info"}


def render() -> None:
    theme.page_header("Data", "Datasets",
                      "Every dataset you can ask about, where it came from, and how it is kept up to date. A failed "
                      "refresh never replaces the last good data.")
    datasets = session.visible_datasets()
    state = sync.state()
    with st.container(border=True, key="card_ds_list"):
        st.markdown("**All datasets**")
        st.dataframe(pd.DataFrame([{
            "Name": d.name, "Dataset id": d.dataset_id, "Source": d.source_type.value.upper(),
            "Rows": d.tables[0].row_count, "Quality": d.quality_status.value,
            "Last refresh": components.format_time(d.last_refresh_at) if d.last_refresh_at else "—",
            "Refresh": d.refresh_status.value,
            "Schedule": _schedule_label(state.settings(d.dataset_id)) if sync.source_of(d) else "—",
        } for d in datasets]), hide_index=True, width="stretch")

    names = {d.dataset_id: d for d in datasets}
    chosen = st.selectbox("Dataset", list(names), format_func=lambda i: names[i].name, key="ds_selected")
    dataset = names[chosen]
    _details(dataset)
    mine = not dataset.builtin and session.can_change(dataset.owner)
    if mine and session.signed_in():
        _share(dataset)
    if sync.source_of(dataset):
        if mine:
            _refresh_card(dataset, state)
        else:
            st.caption("Only the owner of this dataset can refresh it or change its schedule.")
        _history(dataset, state)
    elif dataset.storage == Storage.DATASETS:
        st.caption("Imported from a file. To update it, import the new file as a dataset.")


def _share(dataset) -> None:
    with st.container(border=True, key="card_ds_share"):
        st.markdown("**Sharing**")
        shared = st.toggle("Share with everyone who signs in (read-only: they can ask questions about it and see "
                           "charts that use it)", value=dataset.shared, key=f"ds_share_{dataset.dataset_id}")
        if shared != dataset.shared:
            data_access.catalog().set_shared(dataset.dataset_id, shared)
            session.record("dataset.shared" if shared else "dataset.unshared", "dataset", dataset.dataset_id,
                           dataset.name)
            st.rerun()
        st.caption("Shared datasets stay read-only for others; connections and their passwords are never shared.")


def _owner_line(dataset) -> str:
    if dataset.builtin:
        return "everyone (built-in)"
    if dataset.owner == session.current_user().user_id:
        return "you" + (" · shared with everyone" if dataset.shared else "")
    owner = accounts.store().get(dataset.owner) if dataset.owner else None
    return (owner.label if owner else "no current account") + (" · shared with everyone" if dataset.shared else "")


def _schedule_label(settings: RefreshSettings) -> str:
    if not settings.enabled or not settings.interval_minutes:
        return "Manual"
    return SCHEDULES.get(settings.interval_minutes, f"Every {settings.interval_minutes} minutes")


def _details(dataset) -> None:
    with st.container(border=True, key="card_ds_details"):
        st.markdown(f"**{components.md_escape(dataset.name)}** · `{dataset.dataset_id}`")
        if dataset.description:
            st.caption(components.md_escape(dataset.description))
        source = sync.source_of(dataset)
        if source and source["kind"] == "rest":
            where = f"API endpoint {source['endpoint']['path']} (connection `{source['connection_id']}`)"
        elif source:
            where = f"table {source['schema']}.{source['table']} (connection `{source['connection_id']}`)"
        elif dataset.storage == Storage.DEMO:
            where = "built-in demo data"
        else:
            where = f"file {dataset.extra.get('original_file', '')}"
        owner = f"\n- Owner: {components.md_escape(_owner_line(dataset))}" if session.signed_in() else ""
        st.markdown(f"- Source: {components.md_escape(where)}\n"
                    f"- Imported: {components.format_time(dataset.created_at) if dataset.created_at else '—'}{owner}")
        for table in dataset.tables:
            st.dataframe(pd.DataFrame([{"Column": c.name, "Type": c.data_type, "Empty allowed": c.nullable}
                                       for c in table.columns]), hide_index=True, width="stretch")


def _refresh_card(dataset, state) -> None:
    current = state.settings(dataset.dataset_id)
    is_db = sync.source_of(dataset)["kind"] in sync.DATABASE_KINDS
    key = dataset.dataset_id
    with st.container(border=True, key="card_ds_refresh"):
        st.markdown("**Refresh**")
        modes = list(MODES) if is_db else ["full"]
        mode = st.radio("How to refresh", modes, index=modes.index(current.mode) if current.mode in modes else 0,
                        format_func=MODES.get, key=f"ds_mode_{key}", horizontal=True)
        key_column = cursor_column = None
        if mode == "incremental":
            columns = [c.name for c in dataset.tables[0].columns]
            left, right = st.columns(2)
            key_column = left.selectbox("Key column (unique for each row)", columns,
                                        index=columns.index(current.key_column) if current.key_column in columns else 0,
                                        key=f"ds_key_{key}")
            cursor_column = right.selectbox(
                "Cursor column (grows for new or changed rows)", columns,
                index=columns.index(current.cursor_column) if current.cursor_column in columns else 0,
                key=f"ds_cursor_{key}", help="For example an id that only increases, or an 'updated at' time.")
            st.caption("Incremental refresh adds new rows and replaces changed ones. Rows deleted at the source are "
                       "not removed; run a full refresh for that.")
        elif not is_db:
            st.caption("API datasets are refreshed in full.")
        options = list(SCHEDULES)
        interval = st.selectbox("Schedule", options, format_func=SCHEDULES.get, key=f"ds_schedule_{key}",
                                index=options.index(current.interval_minutes)
                                if current.enabled and current.interval_minutes in options else 0)
        save, now = st.columns(2)
        if save.button("Save refresh settings", icon=":material/save:", key="ds_save", width="stretch"):
            try:
                saved = sync.save_settings(dataset, RefreshSettings(
                    key, mode, key_column, cursor_column, interval, enabled=interval is not None,
                    last_cursor=current.last_cursor))
            except sync.RefreshError as exc:
                st.error(components.md_escape(exc.message), icon=":material/error:")
            else:  # redraw so the list at the top shows the new schedule too
                session.record("dataset.refresh_settings", "dataset", key,
                               f"{mode}, {SCHEDULES.get(interval, f'every {interval} minutes')}")
                st.session_state["ds_result"] = (key, "success", "Refresh settings saved." + (
                    f" Next run: {components.format_time(saved.next_run_at)}." if saved.next_run_at else ""))
                st.rerun()
        if now.button("Refresh now", type="primary", icon=":material/refresh:", key="ds_refresh_now", width="stretch"):
            with st.spinner("Refreshing…"):
                result = sync.refresh(key)
            session.record("dataset.refreshed", "dataset", key, result.status)
            st.session_state["ds_result"] = (key, result.status, result.message)
            st.rerun()
        stored = st.session_state.pop("ds_result", None)
        if stored and stored[0] == key:
            _, status, message = stored
            show = {"success": st.success, "failed": st.error}.get(status, st.info)
            show(components.md_escape(message))
        if current.enabled and current.next_run_at:
            st.caption(f"Next scheduled run: {components.format_time(current.next_run_at)}. Scheduled refreshes run "
                       "when scripts/refresh_worker.py runs (for example every 5 minutes from cron); this is periodic "
                       "polling, not real-time streaming.")


def _history(dataset, state) -> None:
    runs = state.runs(dataset.dataset_id)
    with st.container(border=True, key="card_ds_history"):
        st.markdown("**Refresh history**")
        if not runs:
            st.caption("No refresh yet.")
            return
        st.dataframe(pd.DataFrame([{
            "Started": components.format_time(r.started_at), "Trigger": r.trigger, "Mode": r.mode, "Status": r.status,
            "Attempts": r.attempts, "Fetched": r.rows_fetched, "New": r.rows_inserted, "Changed": r.rows_updated,
            "Total": r.rows_total, "Message": r.message,
        } for r in runs]), hide_index=True, width="stretch")
