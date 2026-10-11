"""AI Analyst: a chat-style conversation over the shared query pipeline.

A question runs exactly once: ``st.chat_input`` returns it only on the run after it is
submitted, and suggestions or history reruns are queued and taken (popped) once.
Finished turns live in session state, so reruns and page changes keep the conversation.
"""

import streamlit as st

from src import analysis, demo_queries
from src.ui import components, session, theme

WELCOME_DEMO = (
    "Hi! I answer questions about the sales data with validated, read-only SQL. "
    "**Demo Mode** answers the suggested questions below using predefined SQL, with no AI "
    "and no internet needed. Switch to AI Mode in the sidebar to ask anything else."
)
WELCOME_AI = (
    "Hi! Ask me anything about the products and sales data. The AI writes a SQL query, "
    "which is validated and run read-only before you see any result. Only your question "
    "and the table structure are sent to the AI service, never the data."
)


def render() -> None:
    db_path = session.db_path()
    source = session.current_source()
    target = session.current_target(db_path)
    turns = session.chat()

    head, reset = st.columns([4, 1], vertical_alignment="bottom")
    with head:
        mode = session.DEMO_MODE if source == "demo" else session.ai_mode_label()
        theme.page_header("AI Analyst", "Ask your data a question",
                          "Answers come from real query results, with the SQL shown for every answer.",
                          theme.badge("info", mode) + " " + theme.badge("muted", f"Dataset: {target.dataset.name}"))
    if reset.button("New chat", key="new_chat", icon=":material/add_comment:", width="stretch",
                    disabled=not turns):
        session.reset_chat()
        st.rerun()

    blocked = source == "demo" and not target.is_demo  # demo SQL exists only for the demo data
    if not turns:
        with st.chat_message("assistant", avatar=":material/insights:"):
            st.markdown(_welcome(source, target))
        if target.is_demo:
            _suggestions(source)
    if blocked:
        st.info(f"Demo Mode only answers the example questions about the demo sales data. To ask about "
                f"**{components.md_escape(target.dataset.name)}**, choose AI Mode in the sidebar, or run your "
                "own SQL in the SQL Explorer.", icon=":material/info:")

    for index, turn in enumerate(turns):
        last = index == len(turns) - 1
        _render_turn(turn, index, follow_ups=_follow_ups(turns) if last and not blocked else None)

    if turns and target.is_demo:
        with st.expander("Suggested questions", icon=":material/lightbulb:"):
            _suggestions(source)
    if not target.is_demo:
        _columns(target)

    if blocked:
        placeholder = "Choose AI Mode to ask about this dataset"
    elif source == "demo":
        placeholder = "Ask one of the suggested questions…"
    elif target.is_demo:
        placeholder = "Ask a question about products, sales, regions or revenue…"
    else:
        placeholder = f"Ask a question about {target.dataset.name}…"
    typed = st.chat_input(placeholder, key="chat_question", max_chars=500, disabled=blocked)
    request = (typed, source) if typed is not None else session.take_pending_question()
    if request is not None:
        _answer_now(db_path, *request, index=len(turns))


def _welcome(source: str, target) -> str:
    if target.is_demo:
        return WELCOME_DEMO if source == "demo" else WELCOME_AI
    return (f"Hi! Ask me anything about **{components.md_escape(target.dataset.name)}**. The AI writes a SQL "
            "query that may read only this dataset; it is validated and run read-only before you see any "
            "result. Only your question and the column names and types are sent to the AI service, never the data.")


def _columns(target) -> None:
    """What the selected dataset contains, so users know what they can ask about."""
    with st.expander("Columns in this dataset", icon=":material/table_chart:"):
        for table in target.dataset.tables:
            rows = f" · {table.row_count:,} rows" if table.row_count is not None else ""
            st.caption(f"Table `{table.name}`{rows}")
            st.markdown(", ".join(f"`{c.name}` ({c.data_type.lower()})" for c in table.columns))


def _suggestions(source: str) -> None:
    with st.container(key="suggestions", horizontal=True, wrap=True, gap="small"):
        for i, question in enumerate(demo_queries.demo_questions()):
            st.button(question, key=f"example_{i}", icon=":material/arrow_outward:", wrap=True,
                      on_click=session.queue_question, args=(question, source))


def _follow_ups(turns: list[session.Turn]) -> list[str]:
    turn = turns[-1]
    if turn.answer is None:
        return []
    return analysis.follow_ups(turn.answer.data, turn.source, asked=[t.question for t in turns])


def _render_turn(turn: session.Turn, index: int, follow_ups: list[str] | None = None) -> None:
    with st.container(key=f"turn_{index}"):
        with st.chat_message("user", avatar=":material/person:"):
            st.markdown(components.md_escape(turn.question) or "*(empty question)*")
        with st.chat_message("assistant", avatar=":material/insights:"):
            kind = "answer" if turn.error is None else "error"
            with st.container(key=f"{kind}_{index}"):
                components.answer_body(turn, key=f"turn_{index}", follow_ups=follow_ups)


def _answer_now(db_path, text: str, source: str, index: int) -> None:
    """Run the request (showing progress only while it actually runs), store it, show it."""
    with st.chat_message("user", avatar=":material/person:"):
        st.markdown(components.md_escape(text.strip()) or "*(empty question)*")
    with st.chat_message("assistant", avatar=":material/insights:"):
        message = ("Asking the AI model and running the query…" if source == "ai"
                   else "Running the query…")
        with st.spinner(message, show_time=True):
            turn = session.run(db_path, text, source)
    session.chat().append(turn)
    st.rerun()  # redraw from session state so the new turn renders like the others
