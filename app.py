"""InsightSQL Streamlit app: page setup, sidebar and navigation.

Pages live in ``views/`` (thin files) and ``src/ui/`` (their code). The UI only collects
input and renders output: every query runs through ``src.query_service.answer_question``
or ``run_query`` (validation, read-only execution, history).

``auth.require_user()`` runs before anything else: with sign-in on, nothing below it runs for a
visitor who is not signed in and allowed. Pages a role may not use are not listed at all.
"""

import html
from pathlib import Path

import streamlit as st

from src import __version__
from src.core.models import DEMO_DATASET_ID
from src.core.logging_setup import configure_logging
from src.ui import auth, session, theme

configure_logging()  # before anything logs; redacts secrets from all log output

ROOT = Path(__file__).resolve().parent

st.set_page_config(page_title="InsightSQL", page_icon=str(ROOT / "assets" / "icon.svg"), layout="wide",
                   initial_sidebar_state="auto")  # open on desktop, collapsed on phones
theme.inject_css()
st.logo(str(ROOT / "assets" / "logo.svg"), size="large", icon_image=str(ROOT / "assets" / "icon.svg"))

user = auth.require_user()
data_pages = [
    st.Page(session.PAGES["import"], title="Import Data", icon=":material/upload_file:", url_path="import"),
    st.Page(session.PAGES["connections"], title="Connections", icon=":material/cable:", url_path="connections"),
] if user.can_create else []
admin_pages = [
    st.Page(session.PAGES["users"], title="Users & Audit", icon=":material/admin_panel_settings:", url_path="users"),
] if user.is_admin and session.signed_in() else []

pages = st.navigation(
    {
        "Analyze": [
            st.Page(session.PAGES["dashboard"], title="Dashboard", icon=":material/space_dashboard:",
                    url_path="dashboard", default=True),
            st.Page(session.PAGES["analyst"], title="AI Analyst", icon=":material/forum:", url_path="analyst"),
            st.Page(session.PAGES["studio"], title="Dashboard Studio", icon=":material/dashboard_customize:",
                    url_path="studio"),
        ],
        "Data": [
            *data_pages,
            st.Page(session.PAGES["datasets"], title="Datasets", icon=":material/dataset:", url_path="datasets"),
        ],
        "Inspect": [
            st.Page(session.PAGES["history"], title="Query History", icon=":material/history:", url_path="history"),
            st.Page(session.PAGES["explorer"], title="SQL Explorer", icon=":material/terminal:", url_path="explorer"),
        ],
        "App": [
            st.Page(session.PAGES["settings"], title="Settings & About", icon=":material/tune:",
                    url_path="settings"),
            *admin_pages,
        ],
    },
    position="sidebar",
)


def sidebar_status() -> None:
    """Mode and dataset selectors and the real status of the selected mode."""
    st.radio("Mode", session.mode_options(), key="mode",
             help="Demo Mode uses predefined SQL and works offline. AI Mode asks the configured AI service.")
    session.apply_pending_dataset()
    names = session.dataset_names()
    if st.session_state.get("dataset") not in names:  # first run, or the dataset was removed
        st.session_state["dataset"] = DEMO_DATASET_ID
    st.selectbox("Dataset", list(names), key="dataset", format_func=names.get,
                 help="The data the AI Analyst and SQL Explorer use. The dashboard always shows the demo sales data.")
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
    auth.sidebar_account(user)
    sidebar_status()

pages.run()
