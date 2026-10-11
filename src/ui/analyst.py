"""AI Analyst: a chat-style conversation over the shared query pipeline.

A question runs exactly once: ``st.chat_input`` returns it only on the run after it is
submitted, and suggestions or history reruns are queued and taken (popped) once.
Finished turns live in session state, so reruns and page changes keep the conversation.
"""

import streamlit as st

from src import demo_queries
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
    turns = session.chat()

    head, reset = st.columns([4, 1], vertical_alignment="bottom")
    with head:
        mode = session.DEMO_MODE if source == "demo" else session.ai_mode_label()
        theme.page_header("AI Analyst", "Ask your data a question",
                          "Answers come from real query results, with the SQL shown for every answer.",
                          theme.badge("info", mode))
    if reset.button("New chat", key="new_chat", icon=":material/add_comment:", width="stretch",
                    disabled=not turns):
        session.reset_chat()
        st.rerun()

    if not turns:
        with st.chat_message("assistant", avatar=":material/insights:"):
            st.markdown(WELCOME_DEMO if source == "demo" else WELCOME_AI)
        _suggestions(source)

    for index, turn in enumerate(turns):
        _render_turn(turn, index)

    if turns:
        with st.expander("Suggested questions", icon=":material/lightbulb:"):
            _suggestions(source)

    placeholder = ("Ask one of the suggested questions…" if source == "demo"
                   else "Ask a question about products, sales, regions or revenue…")
    typed = st.chat_input(placeholder, key="chat_question", max_chars=500)
    request = (typed, source) if typed is not None else session.take_pending_question()
    if request is not None:
        _answer_now(db_path, *request, index=len(turns))


def _suggestions(source: str) -> None:
    with st.container(key="suggestions", horizontal=True, wrap=True, gap="small"):
        for i, question in enumerate(demo_queries.demo_questions()):
            st.button(question, key=f"example_{i}", icon=":material/arrow_outward:", wrap=True,
                      on_click=session.queue_question, args=(question, source))


def _render_turn(turn: session.Turn, index: int) -> None:
    with st.container(key=f"turn_{index}"):
        with st.chat_message("user", avatar=":material/person:"):
            st.markdown(components.md_escape(turn.question) or "*(empty question)*")
        with st.chat_message("assistant", avatar=":material/insights:"):
            kind = "answer" if turn.error is None else "error"
            with st.container(key=f"{kind}_{index}"):
                components.answer_body(turn, key=f"turn_{index}")


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
