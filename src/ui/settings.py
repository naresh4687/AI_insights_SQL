"""Settings & About: real configuration and status. Secrets are never displayed."""

from datetime import datetime

import streamlit as st

from src import __version__, ai_providers, analytics, config, database
from src.ui import components, session, theme


def render() -> None:
    db_path = session.db_path()
    theme.page_header("Settings & About", "Configuration and status",
                      "What InsightSQL is using right now. API keys are never shown.")

    left, right = st.columns(2)
    with left, st.container(border=True, key="card_ai"):
        _ai_section()
    with right, st.container(border=True, key="card_database"):
        _database_section(db_path)

    with st.container(border=True, key="card_setup"):
        st.markdown("**Configure Gemini (AI Mode)**")
        st.markdown(
            "1. Create a key at https://aistudio.google.com/apikey.\n"
            "2. In the project folder, add `GEMINI_API_KEY=your-key` to the `.env` file "
            "(git-ignored; never commit it). Optionally set `GEMINI_MODEL`.\n"
            "3. Restart the app, choose **AI Mode** in the sidebar, and use **Test connection** above.\n\n"
            "Demo Mode needs no key and no internet."
        )
    with st.container(border=True, key="card_security"):
        st.markdown("**How queries are kept safe**")
        st.markdown(
            "- Only one read-only `SELECT` on the `products` and `sales` tables is accepted.\n"
            "- A database-level authorizer blocks writes, other tables and unsafe functions.\n"
            "- Queries run on a read-only connection with a 3-second limit and at most 1,000 rows.\n"
            "- AI-written SQL, SQL from history and SQL typed in the SQL Explorer all go through these checks."
        )
    st.caption(f"InsightSQL version {__version__}")


def _ai_section() -> None:
    st.markdown("**AI Mode**")
    mode = session.DEMO_MODE if session.current_source() == "demo" else session.ai_mode_label()
    try:
        provider = ai_providers.current()
        provider_text, model = provider.DISPLAY_NAME, provider.model_name()
    except Exception as exc:  # invalid AI_PROVIDER
        provider_text, model = f"Invalid setting ({exc})", "—"
    try:
        provider_name = config.get_ai_provider()
    except ValueError:
        provider_name = None
    key_getter = {"gemini": config.get_gemini_api_key, "huggingface": config.get_hf_token}.get(provider_name)
    key_set = key_getter is not None and key_getter() is not None
    st.markdown(
        f"- Current mode: **{components.md_escape(mode)}**\n"
        f"- AI provider: **{components.md_escape(provider_text)}**\n"
        f"- Model: `{model}`\n"
        f"- API key: **{'configured' if key_set else 'not configured'}** (value never shown)"
    )

    if st.button("Test connection", key="test_connection", icon=":material/network_check:"):
        with st.spinner("Checking…"):
            st.session_state["connection_result"] = (*ai_providers.check_status(), datetime.now())
    result = st.session_state.get("connection_result")
    if result is None:
        st.caption("Connection not checked yet. A key being set does not mean it works; "
                   "the check asks the provider to confirm the key and model.")
        return
    ok, message, checked_at = result
    st.html(f'{theme.badge("success" if ok else "error", "Connected" if ok else "Not available")} '
            f'<span class="isql-meta">&nbsp;checked {checked_at:%H:%M:%S}</span>')
    (st.success if ok else st.warning)(components.md_escape(message))


def _database_section(db_path) -> None:
    st.markdown("**Database**")
    try:
        kpis = analytics.kpis(db_path)
        history = database.history_count(db_path)
    except Exception as exc:  # report any failure safely, without details
        st.html(theme.badge("error", "Unavailable"))
        st.caption(f"The database could not be read ({type(exc).__name__}).")
        return
    st.html(theme.badge("success", "Available · read-only queries"))
    try:
        shown_path = db_path.relative_to(config.PROJECT_ROOT)
    except ValueError:
        shown_path = db_path.name
    st.markdown(
        f"- File: `{shown_path}`\n"
        f"- Products: **{kpis.products:,}** · Sales: **{kpis.sales:,}**\n"
        f"- Query history entries: **{history:,}**"
    )
