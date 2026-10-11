"""Sign-in gate, run by ``app.py`` before any page.

With ``INSIGHTSQL_AUTH=none`` (the default) there is no sign-in: one local user with full
rights, for an app only this computer can reach. With ``INSIGHTSQL_AUTH=oidc`` every visitor
must sign in through the OpenID Connect provider(s) in ``.streamlit/secrets.toml`` (Streamlit's
``st.login``), and then be allowed by ``accounts.UserStore.sign_in``. The gate fails closed:
missing or invalid sign-in settings stop the app with a setup message instead of letting
anyone in.

The account is looked up again on every run, so a disabled account or a changed role takes
effect on the user's next click.
"""

import html
import logging
from collections.abc import Mapping

import streamlit as st

from src import accounts, config
from src.ui import components, theme

logger = logging.getLogger(__name__)

_REQUIRED = ("redirect_uri", "cookie_secret")
_PROVIDER_KEYS = ("client_id", "client_secret", "server_metadata_url")
PROVIDER_LABELS = {"google": "Google", "microsoft": "Microsoft", "okta": "Okta", "auth0": "Auth0"}


def identity() -> dict | None:
    """The claims of the identity the provider confirmed, or None when not signed in."""
    if not st.user.is_logged_in:
        return None
    return st.user.to_dict()


def auth_settings() -> Mapping | None:
    try:
        return st.secrets.get("auth")
    except Exception:  # no secrets.toml, or it cannot be parsed
        return None


def providers(settings: Mapping) -> list[str | None]:
    """Named providers ([auth.google], [auth.microsoft] …); [None] for one unnamed provider."""
    named = [name for name, value in settings.items() if isinstance(value, Mapping)]
    return named or ([None] if "client_id" in settings else [])


def setup_problems(settings: Mapping | None) -> list[str]:
    """What is missing from the sign-in settings (names only, never values)."""
    if not settings:
        return ["There is no [auth] section in .streamlit/secrets.toml."]
    problems = [f"[auth] needs {key}." for key in _REQUIRED if not settings.get(key)]
    if len(str(settings.get("cookie_secret") or "")) < 32:
        problems.append("[auth] cookie_secret must be a random value of at least 32 characters.")
    names = providers(settings)
    if not names:
        problems.append("Add a provider: [auth.google] or [auth.microsoft] with client_id, client_secret and "
                        "server_metadata_url.")
    for name in names:
        section = settings[name] if name else settings
        label = f"[auth.{name}]" if name else "[auth]"
        problems += [f"{label} needs {key}." for key in _PROVIDER_KEYS if not section.get(key)]
        if section.get("server_metadata_url") and not str(section["server_metadata_url"]).startswith("https://"):
            problems.append(f"{label} server_metadata_url must be an https:// address.")
    return problems


def require_user() -> accounts.User:
    """The account for this visitor; stops the page (after showing why) if there is none."""
    try:
        mode = config.get_auth_mode()
    except ValueError as exc:
        _stop("Sign-in is not set up correctly", str(exc))
    if mode == "none":
        st.session_state["user"] = accounts.LOCAL_USER
        return accounts.LOCAL_USER

    settings = auth_settings()
    problems = setup_problems(settings)
    if problems:
        logger.error("Sign-in settings are incomplete: %s", " ".join(problems))
        _stop("Sign-in is not set up yet",
              "INSIGHTSQL_AUTH is set to oidc, so everyone must sign in, but the sign-in settings are "
              "incomplete. The administrator needs to fix .streamlit/secrets.toml (see README → User accounts):\n\n"
              + "\n".join(f"- {p}" for p in problems))

    claims = identity()
    if claims is None:
        st.session_state.pop("user", None)
        _sign_in_page(providers(settings))
        st.stop()

    store = accounts.store()
    subject = accounts.subject_of(claims)
    user = None
    if st.session_state.get("user_subject") == subject and st.session_state.get("user"):
        user = store.get(st.session_state["user"].user_id)
    if user is None:
        try:
            user = store.sign_in(claims)
        except accounts.AccountError as exc:
            st.session_state.pop("user", None)
            _refused(exc.message)
    if not user.active:
        st.session_state.pop("user", None)
        _refused("Your InsightSQL account is disabled. Ask the administrator.")
    st.session_state["user"], st.session_state["user_subject"] = user, subject
    return user


def sign_out() -> None:
    for key in list(st.session_state):
        del st.session_state[key]
    st.logout()


def sidebar_account(user: accounts.User) -> None:
    """Who is signed in, their role, and Sign out (nothing when sign-in is off)."""
    if user.user_id == accounts.LOCAL_USER_ID:
        return
    st.html(f'<div class="isql-account" role="status"><b>{html.escape(user.label)}</b><br>'
            f'{theme.badge("info", accounts.ROLES[user.role])} '
            f'<span class="isql-account-email">{html.escape(user.email)}</span></div>')
    if st.button("Sign out", icon=":material/logout:", key="sign_out", width="stretch"):
        sign_out()


def _sign_in_page(names: list[str | None]) -> None:
    theme.page_header("Welcome", "Sign in to InsightSQL",
                      "Sign in with your work account. You only see your own data and what others share with you.")
    with st.container(border=True, key="card_sign_in"):
        for name in names:
            label = "Sign in" if name is None else f"Sign in with {PROVIDER_LABELS.get(name, name.title())}"
            if st.button(label, type="primary", icon=":material/login:", key=f"sign_in_{name or 'default'}",
                         width="stretch"):
                st.login(name) if name else st.login()
        st.caption("No password is stored by InsightSQL: your sign-in provider confirms who you are.")


def _refused(message: str) -> None:
    theme.page_header("Welcome", "No access", "")
    st.error(components.md_escape(message), icon=":material/block:")
    if st.button("Sign out", icon=":material/logout:", key="sign_out_refused"):
        sign_out()
    st.stop()


def _stop(title: str, message: str) -> None:
    theme.page_header("Setup", title, "")
    st.error(message, icon=":material/settings:")
    st.stop()
