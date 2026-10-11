"""Connections: save PostgreSQL, MySQL and REST API connections, test them, browse their
tables or endpoints, and import a snapshot as a dataset.

Imported data goes through the same review steps as an uploaded file (``import_data``):
quality checks, cleaning options, confirmation and an all-or-nothing save. AI-written SQL never
runs on the connected server; questions use the imported snapshot.

Each connection belongs to the account that saved it and is listed only for its owner (and
administrators): it holds the owner's password or token.
"""

import hashlib
from urllib.parse import urlsplit

import pandas as pd
import streamlit as st

from src import accounts, config
from src.connectors import databases, network, profiles, rest, snapshot
from src.connectors.profiles import KINDS, REST_AUTH, SSL_MODES, ConnectorError
from src.core import secrets
from src.ui import components, import_data, session, theme

NEW = "__new__"


def _store() -> profiles.ConnectionStore:
    return profiles.store()


def _fail(exc: Exception) -> None:
    message = getattr(exc, "message", "Something went wrong. Please try again.")
    st.error(components.md_escape(message), icon=":material/error:")


def render() -> None:
    theme.page_header("Data", "Connections",
                      "Connect to a PostgreSQL or MySQL database or a REST API, then import a snapshot of the data "
                      "you choose as a dataset. Connections are read-only; questions never run on your server.")
    if not session.current_user().can_create:  # the page is not listed for viewers; checked here too
        st.info("Your role (viewer) can read data but not add it. Ask an administrator for editor access.",
                icon=":material/lock:")
        return
    import_data.show_saved_message()
    if not secrets.available():
        st.warning("Saving passwords and tokens is not set up. " + components.md_escape(secrets.KEY_HELP),
                   icon=":material/key:")
    store = _store()
    saved = store.list(session.current_user())
    _saved_list(saved)
    _editor(store, saved)
    if saved:
        _importer(store, saved)


# --- Saved connections ------------------------------------------------------------------

def _saved_list(saved: list[profiles.Profile]) -> None:
    with st.container(border=True, key="card_conn_list"):
        st.markdown("**Saved connections**")
        if not saved:
            theme.empty_state("No connections yet", "Add one below. A read-only database account is recommended.")
            return
        st.dataframe(pd.DataFrame([{
            "Name": p.name, "Type": p.kind_label, "Address": p.summary,
            "Last test": ("—" if p.last_test_ok is None else ("OK" if p.last_test_ok else "Failed")) +
                         (f" · {components.format_time(p.last_tested_at)}" if p.last_tested_at else ""),
        } for p in saved]), hide_index=True, width="stretch")


def _editor(store: profiles.ConnectionStore, saved: list[profiles.Profile]) -> None:
    with st.container(border=True, key="card_conn_edit"):
        st.markdown("**Add or change a connection**")
        names = {p.connection_id: p.name for p in saved}
        if "conn_edit_id_next" in st.session_state:  # set before the selector is drawn
            st.session_state["conn_edit_id"] = st.session_state.pop("conn_edit_id_next")
        if st.session_state.get("conn_edit_id") not in (NEW, *names):
            st.session_state["conn_edit_id"] = NEW
        chosen = st.selectbox("Connection", [NEW, *names], key="conn_edit_id",
                              format_func=lambda c: "New connection" if c == NEW else names[c])
        current = store.get(chosen) if chosen != NEW else None
        suffix = chosen  # widget keys per connection, so switching shows that connection's values
        kinds = list(KINDS)
        kind = st.selectbox("Type", kinds, index=kinds.index(current.kind) if current else 0, format_func=KINDS.get,
                            key=f"conn_kind_{suffix}")
        values = current.settings if current and current.kind == kind else {}
        name = st.text_input("Name", value=current.name if current else "", key=f"conn_name_{suffix}",
                             max_chars=profiles.MAX_NAME_LENGTH)
        settings = _db_fields(kind, values, suffix) if kind != "rest" else _rest_fields(values, suffix)
        secret_label = {"postgres": "Password", "mysql": "Password"}.get(kind, "Token, API key or password")
        secret = ""
        if profiles.needs_secret(kind, settings):
            secret = st.text_input(secret_label, type="password", key=f"conn_secret_{suffix}",
                                   placeholder="Leave empty to keep the saved one" if current and current.has_secret
                                   else "", help="Stored encrypted. It is never shown again.")
        save, test, delete = st.columns(3)
        if save.button("Save connection", type="primary", icon=":material/save:", key="conn_save", width="stretch"):
            try:
                profile = store.save(name, kind, settings, secret or None, connection_id=current.connection_id
                                     if current else None, owner=accounts.owner_of(session.current_user()))
            except (ConnectorError, secrets.SecretError) as exc:
                _fail(exc)
            else:
                session.record("connection.changed" if current else "connection.created", "connection",
                               profile.connection_id, f"{profile.name} ({profile.kind_label})")
                st.session_state["conn_notice"] = f"Saved connection '{profile.name}'."
                st.session_state["conn_edit_id_next"] = profile.connection_id
                st.rerun()
        if current and test.button("Test connection", icon=":material/network_check:", key="conn_test",
                                   width="stretch"):
            _test(store, current)
        if current:
            confirm = delete.checkbox("Confirm delete", key=f"conn_delete_ok_{suffix}")
            if delete.button("Delete", icon=":material/delete:", key="conn_delete", width="stretch", disabled=not confirm):
                store.delete(current.connection_id)
                session.record("connection.deleted", "connection", current.connection_id, current.name)
                st.session_state["conn_notice"] = (f"Deleted connection '{current.name}'. Datasets imported from it "
                                                   "keep their data.")
                st.session_state["conn_edit_id_next"] = NEW
                st.rerun()
        notice = st.session_state.pop("conn_notice", None)
        if notice:
            st.success(components.md_escape(notice), icon=":material/check_circle:")


def _db_fields(kind: str, values: dict, suffix: str) -> dict:
    left, right = st.columns([3, 1])
    host = left.text_input("Host", value=values.get("host", ""), key=f"conn_host_{suffix}",
                           placeholder="db.example.com")
    port = right.number_input("Port", min_value=1, max_value=65535, value=int(values.get("port") or
                              profiles.DEFAULT_PORTS[kind]), key=f"conn_port_{suffix}")
    left, middle, right = st.columns(3)
    database = left.text_input("Database", value=values.get("database", ""), key=f"conn_db_{suffix}")
    username = middle.text_input("User name", value=values.get("username", ""), key=f"conn_user_{suffix}",
                                 help="A read-only account is recommended.")
    modes = SSL_MODES[kind]
    ssl = right.selectbox("Encryption (SSL/TLS)", modes, index=modes.index(values["ssl"]) if values.get("ssl") in modes
                          else 0, key=f"conn_ssl_{suffix}")
    return {"host": host, "port": int(port), "database": database, "username": username, "ssl": ssl}


def _rest_fields(values: dict, suffix: str) -> dict:
    base_url = st.text_input("Base address", value=values.get("base_url", ""), key=f"conn_url_{suffix}",
                             placeholder="https://api.example.com/v1")
    methods = list(REST_AUTH)
    auth = st.selectbox("Authentication", methods, index=methods.index(values.get("auth", "none")),
                        format_func=REST_AUTH.get, key=f"conn_auth_{suffix}")
    settings = {"base_url": base_url, "auth": auth}
    if auth == "header":
        settings["auth_header"] = st.text_input("Header name", value=values.get("auth_header", "X-API-Key"),
                                                key=f"conn_header_{suffix}")
    if auth == "basic":
        settings["username"] = st.text_input("User name", value=values.get("username", ""), key=f"conn_apiuser_{suffix}")
    return settings


def _secret(store: profiles.ConnectionStore, profile: profiles.Profile) -> str | None:
    return store.secret(profile.connection_id)


def _test(store: profiles.ConnectionStore, profile: profiles.Profile) -> None:
    try:
        with st.spinner("Testing the connection…"):
            secret = _secret(store, profile)
            if profile.kind == "rest":
                network.check(*_api_host(profile))  # the address is allowed; endpoints are tried with Preview
                message = "The API address is allowed. Use Preview below to try an endpoint."
            else:
                message = f"Connected (read-only): {databases.test(profile, secret)}"
    except (ConnectorError, secrets.SecretError, network.DestinationError) as exc:
        store.record_test(profile.connection_id, False)
        _fail(exc)
    else:
        store.record_test(profile.connection_id, True)
        st.success(components.md_escape(message), icon=":material/check_circle:")


def _api_host(profile: profiles.Profile) -> tuple[str, int]:
    parts = urlsplit(profile.settings["base_url"])
    return parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)


# --- Import -----------------------------------------------------------------------------

def _importer(store: profiles.ConnectionStore, saved: list[profiles.Profile]) -> None:
    with st.container(border=True, key="card_conn_import"):
        st.markdown("**1. Choose data to import**")
        names = {p.connection_id: p for p in saved}
        chosen = st.selectbox("From connection", list(names), format_func=lambda c: names[c].name,
                              key="conn_import_id")
        profile = names[chosen]
        try:
            if profile.kind == "rest":
                _api_source(store, profile)
            else:
                _table_source(store, profile)
        except (ConnectorError, secrets.SecretError) as exc:
            _fail(exc)
    snap = st.session_state.get("import_snapshot")
    if snap is not None and snap.source.get("connection_id") == chosen:
        st.caption(f"Snapshot of {components.md_escape(snapshot.source_label(snap.source))} from "
                   f"{components.md_escape(profile.name)}. Times are kept to the second and converted to UTC.")
        import_data.review_table(snap.raw, snap.content, key=hashlib.sha256(snap.content).hexdigest(),
                                 source=snap.source, presets=snap.type_presets)


def _table_source(store: profiles.ConnectionStore, profile: profiles.Profile) -> None:
    cache_key = f"conn_tables_{profile.connection_id}"
    if st.button("Load tables", icon=":material/table_view:", key="conn_load_tables"):
        with st.spinner("Reading the list of tables…"):
            st.session_state[cache_key] = databases.list_tables(profile, _secret(store, profile))
    tables = st.session_state.get(cache_key)
    if tables is None:
        st.caption("Load the list of tables this user may read.")
        return
    if not tables:
        st.info("No tables are visible to this user.")
        return
    schema, table = st.selectbox("Table", tables, format_func=lambda t: f"{t[0]}.{t[1]}", key="conn_table")
    described = databases.columns(profile, _secret(store, profile), schema, table)
    importable = [c.name for c in described if c.kind != "unsupported"]
    skipped = [c.name for c in described if c.kind == "unsupported"]
    chosen = st.multiselect("Columns to import", importable, default=importable,
                            key=f"conn_columns_{profile.connection_id}_{schema}_{table}")
    if skipped:
        st.caption(f"Not importable (binary data): {', '.join(skipped)}")
    st.dataframe(pd.DataFrame([{"Column": c.name, "Server type": c.source_type,
                                "InsightSQL type": c.kind if c.kind != "unsupported" else "— (skipped)"}
                               for c in described]), hide_index=True, width="stretch")
    preview, fetch = st.columns(2)
    if preview.button("Preview", icon=":material/visibility:", key="conn_preview", disabled=not chosen):
        st.dataframe(databases.preview(profile, _secret(store, profile), schema, table, chosen), hide_index=True,
                     width="stretch")
    if fetch.button("Fetch for import", type="primary", icon=":material/download:", key="conn_fetch",
                    disabled=not chosen):
        with st.spinner("Fetching the data…"):
            st.session_state["import_snapshot"] = snapshot.from_database(
                profile, _secret(store, profile), schema, table, chosen, config.get_import_max_rows())


def _api_source(store: profiles.ConnectionStore, profile: profiles.Profile) -> None:
    path = st.text_input("Endpoint path", key="conn_api_path", placeholder="/orders",
                         help=f"Below {profile.settings['base_url']}")
    params_text = st.text_area("Query parameters (one name=value per line, no secrets)", key="conn_api_params",
                               height=70)
    records_path = st.text_input("Where the records are in the response", key="conn_api_records",
                                 placeholder="e.g. data.items (empty: the whole response is the list)")
    kinds = list(rest.PAGINATION)
    pagination = st.selectbox("Pagination", kinds, format_func=rest.PAGINATION.get, key="conn_api_pagination")
    extra = {}
    if pagination == "page":
        left, middle, right = st.columns(3)
        extra = {"page_param": left.text_input("Page parameter", "page", key="conn_api_page_param"),
                 "size_param": middle.text_input("Page size parameter", "per_page", key="conn_api_size_param"),
                 "page_size": int(right.number_input("Page size", 1, 1000, 100, key="conn_api_page_size"))}
    elif pagination == "offset":
        left, middle, right = st.columns(3)
        extra = {"offset_param": left.text_input("Offset parameter", "offset", key="conn_api_offset_param"),
                 "limit_param": middle.text_input("Limit parameter", "limit", key="conn_api_limit_param"),
                 "page_size": int(right.number_input("Page size", 1, 1000, 100, key="conn_api_offset_size"))}
    elif pagination == "next_link":
        extra = {"next_path": st.text_input("Where the next-page link is", "next", key="conn_api_next")}
    if pagination != "none":
        extra["max_pages"] = int(st.number_input("Page limit", 1, 500, rest.MAX_PAGES, key="conn_api_max_pages"))
    params = {}
    for line in (params_text or "").splitlines():
        if line.strip():
            if "=" not in line:
                raise ConnectorError(f"Write each parameter as name=value (problem: '{line.strip()}').")
            key, value = line.split("=", 1)
            params[key.strip()] = value.strip()
    endpoint = rest.Endpoint(path=path.strip(), params=params, records_path=records_path.strip(), pagination=pagination,
                             **extra)
    preview, fetch = st.columns(2)
    if preview.button("Preview", icon=":material/visibility:", key="conn_api_preview", disabled=not path.strip()):
        st.dataframe(rest.preview(profile, _secret(store, profile), endpoint), hide_index=True, width="stretch")
    if fetch.button("Fetch for import", type="primary", icon=":material/download:", key="conn_api_fetch",
                    disabled=not path.strip()):
        with st.spinner("Fetching every page…"):
            st.session_state["import_snapshot"] = snapshot.from_api(
                profile, _secret(store, profile), endpoint, config.get_import_max_rows(),
                config.get_import_max_columns())
