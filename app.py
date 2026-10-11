"""InsightSQL Streamlit app: page setup, sidebar and navigation.

Pages live in ``views/`` (thin files) and ``src/ui/`` (their code). The UI only collects
input and renders output: every query runs through ``src.query_service.answer_question``
or ``run_query`` (validation, read-only execution, history).
"""

import html
from pathlib import Path

import streamlit as st

from src import __version__
from src.ui import session, theme

ROOT = Path(__file__).resolve().parent

st.set_page_config(page_title="InsightSQL", page_icon=str(ROOT / "assets" / "icon.svg"), layout="wide",
                   initial_sidebar_state="auto")  # open on desktop, collapsed on phones
theme.inject_css()
st.logo(str(ROOT / "assets" / "logo.svg"), size="large", icon_image=str(ROOT / "assets" / "icon.svg"))

pages = st.navigation(
    {
        "Analyze": [
            st.Page(session.PAGES["dashboard"], title="Dashboard", icon=":material/space_dashboard:",
                    url_path="dashboard", default=True),
            st.Page(session.PAGES["analyst"], title="AI Analyst", icon=":material/forum:", url_path="analyst"),
        ],
        "Inspect": [
            st.Page(session.PAGES["history"], title="Query History", icon=":material/history:", url_path="history"),
            st.Page(session.PAGES["explorer"], title="SQL Explorer", icon=":material/terminal:", url_path="explorer"),
        ],
        "App": [
            st.Page(session.PAGES["settings"], title="Settings & About", icon=":material/tune:",
                    url_path="settings"),
        ],
    },
    position="sidebar",
)


def sidebar_status() -> None:
    """Mode selector and the real status of the selected mode."""
    st.radio("Mode", session.mode_options(), key="mode",
             help="Demo Mode uses predefined SQL and works offline. AI Mode asks the configured AI service.")
    if session.current_source() == "demo":
        body = (f"{theme.badge('success', 'Ready')}<br><b>Demo Mode</b> · predefined SQL for the "
                "suggested questions. No AI requests, works offline.")
    else:
        ok, message = session.ai_status()
        body = (f"{theme.badge('success' if ok else 'warning', 'Connected' if ok else 'Needs attention')}"
                f"<br>{html.escape(message)}")
    st.html(f'<div class="isql-status" role="status">{body}</div>'
            f'<div class="isql-version">InsightSQL v{html.escape(__version__)}</div>')


with st.sidebar:
    sidebar_status()

pages.run()
