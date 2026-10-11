"""SQL Explorer: inspect and run read-only SQL through the same safety pipeline.

Typed SQL is just another SQL source for ``answer_question()``: it is parsed and validated,
checked by the SQLite authorizer, run on a read-only connection with a timeout and row cap,
and recorded in history. There is no other execution path.
"""

import streamlit as st

from src.ui import components, session, theme

EXAMPLE_SQL = (
    "SELECT p.category, ROUND(SUM(s.quantity * s.unit_price), 2) AS revenue\n"
    "FROM sales s JOIN products p ON p.product_id = s.product_id\n"
    "GROUP BY p.category\nORDER BY revenue DESC"
)


def render() -> None:
    db_path = session.db_path()
    target = session.current_target(db_path)
    tables = " and ".join(sorted(target.scope))
    theme.page_header("SQL Explorer", "Inspect and run read-only SQL",
                      f"Only a single SELECT on the {tables} table{'s' if len(target.scope) > 1 else ''} of "
                      "the selected dataset is allowed. Every query is validated, run read-only with a time "
                      "limit, and recorded in history.",
                      theme.badge("muted", f"Dataset: {target.dataset.name}"))

    preset = st.session_state.pop("explorer_preset", None)
    if preset is not None:
        st.session_state["custom_sql"] = preset

    last_ai_sql = next((t.answer.sql for t in reversed(session.chat())
                        if t.answer and t.source == "ai" and t.answer.dataset_id == target.dataset_id), None)
    example = EXAMPLE_SQL if target.is_demo else f"SELECT *\nFROM {target.dataset.tables[0].name}\nLIMIT 10"
    with st.container(border=True, key="card_editor"):
        with st.form("sql_form", border=False):
            st.text_area("SQL query", key="custom_sql", height=150, placeholder=example)
            run, _ = st.columns([1, 3])
            submitted = run.form_submit_button("Run SQL", type="primary", icon=":material/play_arrow:",
                                               width="stretch")
        if last_ai_sql and st.button("Load the last AI-generated SQL", key="load_ai_sql", icon=":material/download:"):
            st.session_state["explorer_preset"] = last_ai_sql
            st.rerun()

    if submitted:
        sql = st.session_state.get("custom_sql") or ""
        if not sql.strip():
            st.session_state["explorer_turn"] = session.Turn("", "sql", None, ("rejected", "Enter a SQL query to run."), 0.0)
        else:
            with st.spinner("Validating and running…"):
                st.session_state["explorer_turn"] = session.run(db_path, sql, "sql")

    turn = st.session_state.get("explorer_turn")
    if turn is None:
        theme.empty_state("No query run yet", "Write a SELECT query above, or open SQL from Query History.")
        return
    kind = "answer" if turn.error is None else "error"
    with st.container(border=True, key=f"card_{kind}_explorer"):
        components.answer_body(turn, key="explorer")
