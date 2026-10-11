"""Users & Audit (administrators only): invite people, set roles, disable accounts, give items
made before sign-in to an account, and read the audit log.

Every change is checked again in ``accounts.UserStore`` (only administrators; at least one active
administrator always remains) and recorded in the audit log.
"""

import pandas as pd
import streamlit as st

from src import accounts, audit
from src.ui import components, session, theme

AUDIT_KINDS = {"": "Everything", "user.": "Sign-ins and users", "dataset.": "Datasets",
               "connection.": "Connections", "dashboard.": "Dashboards", "items.": "Ownership changes"}


def render() -> None:
    theme.page_header("App", "Users & Audit",
                      "Who can use InsightSQL, with which role, and a record of every change. Sign-in itself is done "
                      "by your sign-in provider; no passwords are stored here.")
    user = session.current_user()
    if not user.is_admin:  # the page is listed for administrators only; checked here too
        st.info("Only administrators can manage users.", icon=":material/lock:")
        return
    notice = st.session_state.pop("users_notice", None)
    if notice:
        st.success(components.md_escape(notice), icon=":material/check_circle:")
    store = accounts.store()
    people = store.list()
    _people(people)
    _invite(store, user)
    _change(store, user, people)
    _unowned(store, user, people)
    _audit(people)


def _done(message: str) -> None:
    st.session_state["users_notice"] = message
    st.rerun()


def _people(people: list[accounts.User]) -> None:
    with st.container(border=True, key="card_users_list"):
        st.markdown("**People**")
        st.dataframe(pd.DataFrame([{
            "Email": u.email, "Name": u.name, "Role": accounts.ROLES[u.role],
            "Status": ("Active" if u.active else "Disabled") + ("" if u.signed_in else " · invited, not signed in yet"),
            "Last sign-in": components.format_time(u.last_login_at) if u.last_login_at else "—",
        } for u in people]), hide_index=True, width="stretch")
        st.caption("Viewer: reads built-in and shared data, asks questions, views dashboards. Editor: also imports "
                   "data, saves connections and builds dashboards, changing only their own. Admin: everything.")


def _invite(store: accounts.UserStore, actor: accounts.User) -> None:
    with st.container(border=True, key="card_users_invite"):
        st.markdown("**Invite someone**")
        left, right = st.columns([3, 1], vertical_alignment="bottom")
        email = left.text_input("Email address", key="users_invite_email", placeholder="name@example.com")
        role = right.selectbox("Role", list(accounts.ROLES), format_func=accounts.ROLES.get, key="users_invite_role")
        if st.button("Invite", type="primary", icon=":material/person_add:", key="users_invite"):
            try:
                invited = store.invite(actor, email, role)
            except accounts.AccountError as exc:
                st.error(components.md_escape(exc.message), icon=":material/error:")
            else:
                _done(f"Invited {invited.email} as {accounts.ROLES[invited.role].lower()}. They can now sign in "
                      "with that email address.")


def _change(store: accounts.UserStore, actor: accounts.User, people: list[accounts.User]) -> None:
    with st.container(border=True, key="card_users_change"):
        st.markdown("**Change a role or access**")
        ids = {u.user_id: u for u in people}
        chosen = st.selectbox("Person", list(ids), format_func=lambda i: ids[i].email, key="users_selected")
        target = ids[chosen]
        roles = list(accounts.ROLES)
        left, middle, right = st.columns([2, 1, 1], vertical_alignment="bottom")
        role = left.selectbox("Role", roles, index=roles.index(target.role), format_func=accounts.ROLES.get,
                              key=f"users_role_{chosen}")
        if middle.button("Save role", key="users_save_role", width="stretch", disabled=role == target.role):
            _apply(lambda: store.set_role(actor, chosen, role), f"{target.email} is now {accounts.ROLES[role].lower()}.")
        label = "Disable" if target.active else "Enable"
        if right.button(label, key="users_toggle_active", width="stretch",
                        icon=":material/block:" if target.active else ":material/check:"):
            _apply(lambda: store.set_active(actor, chosen, not target.active),
                   f"{target.email} is {'disabled' if target.active else 'enabled'}.")
        st.caption("Disabling takes effect on the person's next click. Their datasets, dashboards and connections are "
                   "kept; give them to someone else below if needed.")


def _apply(change, message: str) -> None:
    try:
        change()
    except accounts.AccountError as exc:
        st.error(components.md_escape(exc.message), icon=":material/error:")
    else:
        _done(message)


def _unowned(store: accounts.UserStore, actor: accounts.User, people: list[accounts.User]) -> None:
    counts = store.unowned_counts()
    if not any(counts.values()):
        return
    with st.container(border=True, key="card_users_unowned"):
        st.markdown("**Items without an owner**")
        st.caption(f"{counts['datasets']} datasets, {counts['dashboards']} dashboards and {counts['connections']} "
                   "connections were made before sign-in was turned on (or by a removed account). Only administrators "
                   "can see them until you give them to someone.")
        active = {u.user_id: u for u in people if u.active and u.role in ("editor", "admin")}
        if not active:
            return
        left, right = st.columns([3, 1], vertical_alignment="bottom")
        chosen = left.selectbox("Give them to", list(active), format_func=lambda i: active[i].email,
                                key="users_assign_to")
        if right.button("Give", key="users_assign", width="stretch"):
            moved = store.assign_unowned(actor, chosen)
            _done(f"Gave {sum(moved.values())} items to {active[chosen].email}.")


def _audit(people: list[accounts.User]) -> None:
    with st.container(border=True, key="card_users_audit"):
        st.markdown("**Audit log**")
        left, right = st.columns(2)
        kind = left.selectbox("Show", list(AUDIT_KINDS), format_func=AUDIT_KINDS.get, key="users_audit_kind")
        ids = {"": None, **{u.user_id: u for u in people}}
        who = right.selectbox("By", list(ids), format_func=lambda i: "Everyone" if not i else ids[i].email,
                              key="users_audit_user")
        events = audit.recent(limit=500, user_id=who or None, action_prefix=kind)
        if not events:
            theme.empty_state("Nothing recorded yet", "Sign-ins and changes appear here.")
            return
        st.dataframe(pd.DataFrame([{
            "When": components.format_time(e.at), "Who": e.user_email or e.user_id or "system", "Action": e.action,
            "Item": f"{e.object_type} {e.object_id}".strip(), "Detail": e.detail,
        } for e in events]), hide_index=True, width="stretch")
        st.caption(f"The newest {len(events)} entries. The log cannot be edited or deleted from the app.")
