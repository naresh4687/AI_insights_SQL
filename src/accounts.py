"""User accounts, roles and the access rules every page and store applies.

Sign-in itself is done by the identity provider (OpenID Connect through Streamlit's
``st.login``); this module decides **who may use the app** and **what each user may do**.

Roles:

- **viewer** — reads the built-in data and anything shared with everyone; asks questions,
  views dashboards. Cannot import, connect, or create.
- **editor** — everything a viewer can, plus imports data, saves connections and builds
  dashboards. Changes only what they own.
- **admin** — everything, including every user's items, user management and the audit log.

Ownership: datasets, dashboards and connections record their owner's ``user_id``. Datasets
and dashboards can be *shared* (read-only) with every signed-in user; connections are never
shared, because they hold the owner's password or token. Items without a current owner (made
before sign-in was turned on, or by a removed account) are visible to administrators only.

``user=None`` in the access functions means the system itself (the refresh worker, tests and
library calls), which is not restricted. Pages always pass the signed-in user.
"""

import hashlib
import re
import secrets as _secrets
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from src import audit, config
from src.storage import app_db

ROLES = {"viewer": "Viewer", "editor": "Editor", "admin": "Admin"}
LOCAL_USER_ID = "local"
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_NAME_LENGTH = 120


class AccountError(Exception):
    """Sign-in or a user change was refused. ``message`` is safe to show to users."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class User:
    user_id: str
    email: str
    name: str
    role: str
    active: bool = True
    signed_in: bool = False  # has signed in at least once (an invitation not yet used is False)
    created_at: str | None = None
    last_login_at: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.active and self.role == "admin"

    @property
    def can_create(self) -> bool:
        """May import data, save connections and build dashboards."""
        return self.active and self.role in ("editor", "admin")

    @property
    def label(self) -> str:
        return self.name or self.email or self.user_id


# The one user of an app running without sign-in (INSIGHTSQL_AUTH=none): full rights.
LOCAL_USER = User(LOCAL_USER_ID, "", "Local user", "admin", signed_in=True)


# --- Access rules ---------------------------------------------------------------------

def can_view(user: User | None, owner: str | None, shared: bool = False, builtin: bool = False) -> bool:
    if user is None:
        return True
    if not user.active:
        return False
    return builtin or user.is_admin or shared or (owner is not None and owner == user.user_id)


def can_change(user: User | None, owner: str | None) -> bool:
    """May rename, edit, refresh, share or delete an item owned by ``owner``."""
    if user is None:
        return True
    return user.is_admin or (user.can_create and owner is not None and owner == user.user_id)


def owner_of(user: User | None) -> str | None:
    """The owner recorded for something ``user`` creates (None for the system)."""
    return user.user_id if user is not None else None


def normalise_email(email: str) -> str:
    return (email or "").strip().lower()


def allowed_without_invite(email: str) -> bool:
    allowed = config.get_allowed_signins()
    domain = "@" + email.rsplit("@", 1)[-1]
    return email in allowed or domain in allowed


def subject_of(claims: dict) -> str:
    """A stable, opaque key for an identity: the provider (``iss``) and its user id (``sub``)."""
    raw = f"{claims.get('iss') or ''}|{claims.get('sub') or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# --- Store -----------------------------------------------------------------------------

class UserStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        app_db.migrate(self.db_path)

    def _conn(self) -> sqlite3.Connection:
        return app_db.connect(self.db_path)

    def get(self, user_id: str) -> User | None:
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        finally:
            conn.close()
        return None if row is None else _user(row)

    def by_email(self, email: str) -> User | None:
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM users WHERE email = ?", (normalise_email(email),)).fetchone()
        finally:
            conn.close()
        return None if row is None else _user(row)

    def list(self) -> list[User]:
        conn = self._conn()
        try:
            rows = conn.execute("SELECT * FROM users ORDER BY email").fetchall()
        finally:
            conn.close()
        return [_user(r) for r in rows]

    # --- Sign-in ----------------------------------------------------------------------

    def sign_in(self, claims: dict) -> User:
        """The account for an identity the provider has confirmed, creating or linking it.

        Refused (``AccountError``, recorded in the audit log) when the provider gives no email,
        says the email is not verified, the account is disabled, or the person is neither an
        administrator, invited, nor allowed by ``INSIGHTSQL_ALLOWED_SIGNINS``. An email that is
        already linked to a different identity is refused too, so another provider account with
        the same address cannot take over an existing user.
        """
        email = normalise_email(claims.get("email") or "")
        if not claims.get("sub") or not _EMAIL.match(email):
            self._refused(email, "no email address from the sign-in provider")
            raise AccountError("Your sign-in provider did not share a verified email address, which InsightSQL "
                               "needs to identify you. Ask the administrator for help.")
        if claims.get("email_verified") is False:
            self._refused(email, "email not verified by the provider")
            raise AccountError("Your email address is not verified with your sign-in provider. Verify it there, "
                               "then sign in again.")
        subject = subject_of(claims)
        name = re.sub(r"\s+", " ", str(claims.get("name") or "")).strip()[:MAX_NAME_LENGTH]
        is_admin_email = email in config.get_admin_emails()
        now = app_db.utc_now()
        conn = self._conn()
        try:
            with conn:
                row = conn.execute("SELECT * FROM users WHERE subject = ?", (subject,)).fetchone()
                if row is None:
                    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
                    if row is not None and row["subject"] is not None:
                        refused = "email already linked to another sign-in"
                    elif row is None and not (is_admin_email or allowed_without_invite(email)):
                        refused = "not invited"
                    else:
                        refused = None
                    if refused:
                        conn.rollback()
                        self._refused(email, refused)
                        raise AccountError(
                            "This account is linked to a different sign-in. Use the one you used before, or ask the "
                            "administrator." if refused.startswith("email") else
                            "You do not have access to InsightSQL yet. Ask the administrator to invite "
                            f"{email}.")
                    if row is None:
                        user_id = "u_" + _secrets.token_hex(10)
                        role = "admin" if is_admin_email else config.get_default_role()
                        conn.execute("INSERT INTO users (user_id, email, name, role, subject, created_at, "
                                     "last_login_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                     (user_id, email, name, role, subject, now, now))
                        created = True
                    else:
                        user_id, created = row["user_id"], False
                        conn.execute("UPDATE users SET subject = ? WHERE user_id = ?", (subject, user_id))
                else:
                    user_id, created = row["user_id"], False
                current = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
                if not current["active"]:
                    conn.rollback()
                    self._refused(email, "account disabled")
                    raise AccountError("Your InsightSQL account is disabled. Ask the administrator.")
                conn.execute("UPDATE users SET email = ?, name = COALESCE(NULLIF(?, ''), name), last_login_at = ?, "
                             "role = CASE WHEN ? THEN 'admin' ELSE role END WHERE user_id = ?",
                             (email, name, now, int(is_admin_email), user_id))
        except sqlite3.IntegrityError:  # the email moved to this identity but another row holds it
            self._refused(email, "email already used by another account")
            raise AccountError("This email address belongs to another InsightSQL account. Ask the "
                               "administrator.") from None
        finally:
            conn.close()
        user = self.get(user_id)
        audit.record(user, "user.created" if created else "user.signed_in", "user", user_id,
                     f"role {user.role}" if created else "")
        return user

    def _refused(self, email: str, reason: str) -> None:
        audit.record(None, "user.sign_in_refused", "user", "", f"{email or 'no email'}: {reason}", email=email)

    # --- Administration (admins only; the caller is checked here too) -------------------

    def invite(self, actor: User, email: str, role: str, name: str = "") -> User:
        _require_admin(actor)
        email = normalise_email(email)
        if not _EMAIL.match(email):
            raise AccountError("Enter a valid email address.")
        if role not in ROLES:
            raise AccountError("Choose a role.")
        user_id = "u_" + _secrets.token_hex(10)
        conn = self._conn()
        try:
            with conn:
                conn.execute("INSERT INTO users (user_id, email, name, role, invited_by, created_at) "
                             "VALUES (?, ?, ?, ?, ?, ?)",
                             (user_id, email, name.strip()[:MAX_NAME_LENGTH], role, actor.user_id, app_db.utc_now()))
        except sqlite3.IntegrityError:
            raise AccountError(f"{email} already has an account.") from None
        finally:
            conn.close()
        audit.record(actor, "user.invited", "user", user_id, f"{email} as {role}")
        return self.get(user_id)

    def set_role(self, actor: User, user_id: str, role: str) -> User:
        _require_admin(actor)
        if role not in ROLES:
            raise AccountError("Choose a role.")
        target = self._require(user_id)
        if target.role == role:
            return target
        if target.role == "admin" and target.email in config.get_admin_emails():
            raise AccountError(f"{target.email} is an administrator through INSIGHTSQL_ADMIN_EMAILS. Remove it "
                               "there first.")
        if target.is_admin:
            self._keep_an_admin(target)
        self._update(user_id, "role", role)
        audit.record(actor, "user.role_changed", "user", user_id, f"{target.email}: {target.role} → {role}")
        return self.get(user_id)

    def set_active(self, actor: User, user_id: str, active: bool) -> User:
        _require_admin(actor)
        target = self._require(user_id)
        if target.active == active:
            return target
        if not active:
            if target.user_id == actor.user_id:
                raise AccountError("You cannot disable your own account.")
            if target.is_admin:
                self._keep_an_admin(target)
        self._update(user_id, "active", int(active))
        audit.record(actor, "user.enabled" if active else "user.disabled", "user", user_id, target.email)
        return self.get(user_id)

    def unowned_counts(self) -> dict[str, int]:
        """Items no current account owns (made before sign-in was on, or by a removed account)."""
        conn = self._conn()
        try:
            return {table: conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {_UNOWNED[table]}").fetchone()[0]
                    for table in _UNOWNED}
        finally:
            conn.close()

    def assign_unowned(self, actor: User, user_id: str) -> dict[str, int]:
        """Give every unowned dataset, dashboard and connection to ``user_id`` (one transaction)."""
        _require_admin(actor)
        target = self._require(user_id)
        conn = self._conn()
        try:
            with conn:
                moved = {table: conn.execute(f"UPDATE {table} SET owner = ? WHERE {_UNOWNED[table]}",
                                             (user_id,)).rowcount for table in _UNOWNED}
        finally:
            conn.close()
        audit.record(actor, "items.assigned", "user", user_id,
                     f"{target.email}: " + ", ".join(f"{n} {t}" for t, n in moved.items()))
        return moved

    def _keep_an_admin(self, leaving: User) -> None:
        others = [u for u in self.list() if u.is_admin and u.user_id != leaving.user_id]
        if not others:
            raise AccountError("InsightSQL needs at least one active administrator.")

    def _require(self, user_id: str) -> User:
        user = self.get(user_id)
        if user is None:
            raise AccountError("This user no longer exists.")
        return user

    def _update(self, user_id: str, column: str, value) -> None:
        conn = self._conn()
        try:
            with conn:
                conn.execute(f"UPDATE users SET {column} = ? WHERE user_id = ?", (value, user_id))
        finally:
            conn.close()


# Built-in datasets belong to everyone; any other owner that is not a current account is unowned.
_NOT_A_USER = "(owner IS NULL OR owner NOT IN (SELECT user_id FROM users))"
_UNOWNED = {"datasets": f"builtin = 0 AND {_NOT_A_USER}", "dashboards": _NOT_A_USER, "connections": _NOT_A_USER}


def _require_admin(actor: User | None) -> None:
    if actor is None or not actor.is_admin:
        raise AccountError("Only administrators can manage users.")


def _user(row: sqlite3.Row) -> User:
    return User(user_id=row["user_id"], email=row["email"], name=row["name"], role=row["role"],
                active=bool(row["active"]), signed_in=row["subject"] is not None, created_at=row["created_at"],
                last_login_at=row["last_login_at"])


def store() -> UserStore:
    return UserStore(config.get_app_db_path())
