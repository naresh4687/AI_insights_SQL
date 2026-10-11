"""Query History: stored questions, outcomes and SQL from the query_history table.

Security: stored SQL is never executed from here. "Ask again" re-asks the question through
the current mode's normal pipeline; "Open in SQL Explorer" only places the stored SQL in
the editor, where running it goes through full validation like any typed SQL.
"""

import html

import streamlit as st

from src import database
from src.ui import components, session, theme

HISTORY_LIMIT = 200
STATUS_FILTERS = {"All": None, "Success": "success", "Rejected": "rejected", "Failed": "error"}


def render() -> None:
    db_path = session.db_path()
    theme.page_header("Query History", "Every question, with its outcome",
                      "Search past questions, inspect the SQL that ran, and ask again with the current mode.")

    rows = database.recent_history(db_path, limit=HISTORY_LIMIT)
    if not rows:
        theme.empty_state("No history yet", "Questions you ask, and SQL you run, are recorded here.")
        return

    search_col, filter_col = st.columns([3, 2], vertical_alignment="bottom")
    query = search_col.text_input("Search questions", key="history_search", placeholder="e.g. revenue",
                                  icon=":material/search:")
    status_name = filter_col.segmented_control("Status", list(STATUS_FILTERS), default="All",
                                               key="history_status", required=True)
    wanted = STATUS_FILTERS[status_name or "All"]
    needle = (query or "").strip().lower()
    shown = [r for r in rows if (wanted is None or r["status"] == wanted)
             and (not needle or needle in r["question"].lower())]

    counts = {s: sum(r["status"] == s for r in rows) for s in ("success", "rejected", "error")}
    st.caption(f"Showing {len(shown)} of {len(rows)} most recent entries · "
               f"{counts['success']} succeeded · {counts['rejected']} rejected · {counts['error']} failed")

    if not shown:
        theme.empty_state("No matching entries", "Try a different search or status filter.")
        return
    for row in shown:
        _entry(row)


def _entry(row: dict) -> None:
    entry_id = row["history_id"]
    with st.container(border=True, key=f"hist_{entry_id}"):
        st.html(f'{theme.badge(row["status"])} '
                f'<span class="isql-meta">&nbsp;{html.escape(components.format_time(row["created_at"]))} · #{entry_id}</span>')
        st.markdown(f"**{components.md_escape(row['question'])}**")
        if row["generated_sql"]:
            with st.expander("SQL that ran"):
                st.code(row["generated_sql"], language="sql", wrap_lines=True)
        else:
            st.caption("No SQL ran for this entry (it was rejected or failed before running).")

        ask, explore = st.columns(2)
        if ask.button("Ask again", key=f"rerun_{entry_id}", icon=":material/replay:", width="stretch",
                      help="Re-asks the question in the current mode; the answer is validated again."):
            session.queue_question(row["question"], session.current_source())
            st.switch_page(session.PAGES["analyst"])
        if row["generated_sql"] and explore.button(
            "Open in SQL Explorer", key=f"explore_{entry_id}", icon=":material/code:", width="stretch",
            help="Loads this SQL into the editor. It is validated again when you run it.",
        ):
            st.session_state["explorer_preset"] = row["generated_sql"]
            st.switch_page(session.PAGES["explorer"])
