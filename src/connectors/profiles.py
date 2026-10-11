"""Saved connection profiles: where to connect and how to log in.

Settings (host, port, database, user name, API address…) are stored as JSON; the one secret
(password, token or API key) is stored only encrypted (``core.secrets``). Profiles never hold
data; datasets imported from a connection are snapshots registered in the dataset catalog.

A profile belongs to the account that saved it and is never shared: only its owner (and
administrators) can see, use, change or delete it (``accounts``).
"""

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from src import accounts, config
from src.core import secrets
from src.core.models import IDENTIFIER
from src.storage import app_db

KINDS = {"postgres": "PostgreSQL", "mysql": "MySQL", "rest": "REST API"}
DEFAULT_PORTS = {"postgres": 5432, "mysql": 3306}
SSL_MODES = {"postgres": ("prefer", "require", "verify-full", "disable"), "mysql": ("disable", "require")}
REST_AUTH = {"none": "No authentication", "bearer": "Bearer token", "header": "API key in a header",
             "basic": "User name and password"}
MAX_NAME_LENGTH = 80
_HEADER_NAME = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_FORBIDDEN_HEADERS = {"host", "content-length", "transfer-encoding", "connection", "cookie"}


class ConnectorError(Exception):
    """A connection problem. ``message`` is safe to show to users (never contains secrets).
    ``retryable`` marks temporary problems (timeouts, unreachable server, rate limits, server
    errors) that a scheduled refresh may try again."""

    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class Profile:
    connection_id: str
    name: str
    kind: str
    settings: dict
    has_secret: bool
    created_at: str | None = None
    updated_at: str | None = None
    last_tested_at: str | None = None
    last_test_ok: bool | None = None
    owner: str | None = None

    @property
    def kind_label(self) -> str:
        return KINDS[self.kind]

    @property
    def summary(self) -> str:
        s = self.settings
        if self.kind == "rest":
            return s["base_url"]
        return f"{s['username']}@{s['host']}:{s['port']}/{s['database']}"


def validate_settings(kind: str, settings: dict) -> dict:
    """Checked and normalised settings (non-secret only). Raises ``ConnectorError``."""
    if kind not in KINDS:
        raise ConnectorError("Choose PostgreSQL, MySQL or REST API.")
    if kind == "rest":
        return _validate_rest(settings)
    host = str(settings.get("host") or "").strip()
    if not host or "://" in host or any(c in host for c in "/@?# "):
        raise ConnectorError("Enter the server's host name or IP address only (no http://, slashes or spaces).")
    try:
        given = settings.get("port")
        port = DEFAULT_PORTS[kind] if given is None or str(given).strip() == "" else int(given)
    except (TypeError, ValueError):
        raise ConnectorError("The port must be a number.") from None
    if not 0 < port < 65536:
        raise ConnectorError("The port must be between 1 and 65535.")
    database = str(settings.get("database") or "").strip()
    username = str(settings.get("username") or "").strip()
    if not database or len(database) > 128 or "\x00" in database:
        raise ConnectorError("Enter the database name.")
    if not username or len(username) > 128 or "\x00" in username:
        raise ConnectorError("Enter the user name (a read-only account is recommended).")
    ssl = settings.get("ssl") or SSL_MODES[kind][0]
    if ssl not in SSL_MODES[kind]:
        raise ConnectorError(f"Choose an encryption mode: {', '.join(SSL_MODES[kind])}.")
    return {"host": host.lower(), "port": port, "database": database, "username": username, "ssl": ssl}


def _validate_rest(settings: dict) -> dict:
    base_url = str(settings.get("base_url") or "").strip().rstrip("/")
    parts = urlsplit(base_url)
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise ConnectorError("Enter the API's base address, e.g. https://api.example.com/v1")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ConnectorError("The base address must not contain a user name, password, '?' or '#'. "
                             "Put the token in the authentication settings.")
    if parts.scheme == "http" and not _listed(parts.hostname, parts.port or 80):
        raise ConnectorError("Use https:// so the token and data are encrypted in transit. (Plain http:// is "
                             "allowed only for hosts listed in INSIGHTSQL_ALLOWED_PRIVATE_HOSTS.)")
    auth = settings.get("auth") or "none"
    if auth not in REST_AUTH:
        raise ConnectorError("Choose an authentication method.")
    clean = {"base_url": base_url, "auth": auth}
    if auth == "header":
        header = str(settings.get("auth_header") or "").strip()
        if not _HEADER_NAME.match(header) or header.lower() in _FORBIDDEN_HEADERS:
            raise ConnectorError("Enter a valid header name for the API key, e.g. X-API-Key.")
        clean["auth_header"] = header
    if auth == "basic":
        username = str(settings.get("username") or "").strip()
        if not username or ":" in username:
            raise ConnectorError("Enter the API user name (without ':').")
        clean["username"] = username
    return clean


def _listed(host: str, port: int) -> bool:
    allowed = config.get_allowed_private_hosts()
    return host.lower() in allowed or f"{host.lower()}:{port}" in allowed


def needs_secret(kind: str, settings: dict) -> bool:
    return kind != "rest" or settings.get("auth", "none") != "none"


class ConnectionStore:
    """Repository for connection profiles in the app database."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        app_db.migrate(self.db_path)

    def save(self, name: str, kind: str, settings: dict, secret: str | None,
             connection_id: str | None = None, owner: str | None = None) -> Profile:
        """Create (``connection_id`` None) or update a profile. ``secret`` None keeps the saved one
        when updating; a new profile that needs a secret must get one. ``owner`` is recorded for a
        new profile; an update keeps the existing owner."""
        name = re.sub(r"\s+", " ", name or "").strip()
        if not name or len(name) > MAX_NAME_LENGTH:
            raise ConnectorError(f"Enter a connection name (at most {MAX_NAME_LENGTH} characters).")
        clean = validate_settings(kind, settings)
        existing = self.get(connection_id) if connection_id else None
        if connection_id and existing is None:
            raise ConnectorError("This connection no longer exists.")
        token = None
        if secret:
            token = secrets.encrypt(secret)  # raises SecretError without a valid key
        elif existing is not None and existing.kind == kind:
            token = self._token(existing.connection_id)
        if needs_secret(kind, clean) and token is None:
            raise ConnectorError("Enter the password, token or API key.")
        if not needs_secret(kind, clean):
            token = None
        now = app_db.utc_now()
        conn = app_db.connect(self.db_path)
        try:
            with conn:
                if existing is None:
                    connection_id = self._new_id(conn, name)
                    conn.execute("INSERT INTO connections (connection_id, name, kind, settings_json, secret, created_at, "
                                 "updated_at, owner) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                 (connection_id, name, kind, json.dumps(clean, sort_keys=True), token, now, now, owner))
                else:
                    conn.execute("UPDATE connections SET name = ?, kind = ?, settings_json = ?, secret = ?, updated_at = ?, "
                                 "last_tested_at = NULL, last_test_ok = NULL WHERE connection_id = ?",
                                 (name, kind, json.dumps(clean, sort_keys=True), token, now, connection_id))
        except sqlite3.IntegrityError:
            raise ConnectorError(f"A connection named '{name}' already exists.") from None
        finally:
            conn.close()
        return self.get(connection_id)

    @staticmethod
    def _new_id(conn: sqlite3.Connection, name: str) -> str:
        base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40] or "connection"
        if not IDENTIFIER.match(base):
            base = f"c_{base}"[:40]
        taken = {row[0] for row in conn.execute("SELECT connection_id FROM connections")}
        candidate, n = base, 2
        while candidate in taken:
            candidate, n = f"{base}_{n}", n + 1
        return candidate

    def get(self, connection_id: str) -> Profile | None:
        conn = app_db.connect(self.db_path)
        try:
            row = conn.execute("SELECT * FROM connections WHERE connection_id = ?", (connection_id,)).fetchone()
        finally:
            conn.close()
        return None if row is None else _profile(row)

    def list(self, user: "accounts.User | None" = None) -> list[Profile]:
        """The profiles ``user`` may use: their own (every profile for administrators and the system)."""
        conn = app_db.connect(self.db_path)
        try:
            rows = conn.execute("SELECT * FROM connections ORDER BY name COLLATE NOCASE").fetchall()
        finally:
            conn.close()
        return [p for p in map(_profile, rows) if accounts.can_view(user, p.owner)]

    def delete(self, connection_id: str) -> None:
        conn = app_db.connect(self.db_path)
        try:
            with conn:
                conn.execute("DELETE FROM connections WHERE connection_id = ?", (connection_id,))
        finally:
            conn.close()

    def secret(self, connection_id: str) -> str | None:
        """The decrypted secret, for immediate use only (never store or display it)."""
        token = self._token(connection_id)
        return None if token is None else secrets.decrypt(token)

    def _token(self, connection_id: str) -> bytes | None:
        conn = app_db.connect(self.db_path)
        try:
            row = conn.execute("SELECT secret FROM connections WHERE connection_id = ?", (connection_id,)).fetchone()
        finally:
            conn.close()
        return None if row is None else row[0]

    def record_test(self, connection_id: str, ok: bool) -> None:
        conn = app_db.connect(self.db_path)
        try:
            with conn:
                conn.execute("UPDATE connections SET last_tested_at = ?, last_test_ok = ? WHERE connection_id = ?",
                             (app_db.utc_now(), int(ok), connection_id))
        finally:
            conn.close()


def _profile(row: sqlite3.Row) -> Profile:
    return Profile(
        connection_id=row["connection_id"], name=row["name"], kind=row["kind"],
        settings=json.loads(row["settings_json"]), has_secret=row["secret"] is not None,
        created_at=row["created_at"], updated_at=row["updated_at"], last_tested_at=row["last_tested_at"],
        last_test_ok=None if row["last_test_ok"] is None else bool(row["last_test_ok"]), owner=row["owner"],
    )


def store() -> ConnectionStore:
    return ConnectionStore(config.get_app_db_path())
