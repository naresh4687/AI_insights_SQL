"""Phase 08: accounts, sign-in rules, roles, ownership, sharing, per-user history and the audit log."""

import sqlite3

import pytest

from src import accounts, audit, config, dashboards as dsh, data_access, database, demo_queries
from src.accounts import AccountError, User, can_change, can_view
from src.catalog import DatasetCatalog
from src.connectors import profiles
from src.core.models import DEMO_DATASET_ID, ColumnInfo, Dataset, SourceType, Storage, TableInfo
from src.query_service import answer_question
from src.storage import app_db

ADMIN, ANA, BEN = "admin@example.com", "ana@example.com", "ben@other.org"


def claims(email, sub=None, iss="https://accounts.google.com", **extra):
    return {"email": email, "sub": sub or f"sub-{email}", "iss": iss, "name": email.split("@")[0].title(), **extra}


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setenv("INSIGHTSQL_ADMIN_EMAILS", ADMIN)
    return accounts.store()


@pytest.fixture
def people(store):
    """An admin, and two editors (Ana, Ben) invited by the admin."""
    admin = store.sign_in(claims(ADMIN))
    ana = store.invite(admin, ANA, "editor")
    ben = store.invite(admin, BEN, "editor")
    return admin, store.sign_in(claims(ANA)), store.sign_in(claims(BEN))


def events(action=""):
    return [(e.action, e.user_email, e.detail) for e in audit.recent(action_prefix=action)]


def make_dataset(dataset_id: str, owner: str | None, shared: bool = False) -> Dataset:
    db = config.get_datasets_db_path()
    conn = sqlite3.connect(db)
    with conn:
        conn.execute(f"CREATE TABLE {dataset_id} (region TEXT, amount REAL)")
        conn.executemany(f"INSERT INTO {dataset_id} VALUES (?, ?)", [("North", 1.0), ("South", 2.0)])
    conn.close()
    return data_access.catalog().register(Dataset(
        dataset_id=dataset_id, name=dataset_id.title(), source_type=SourceType.CSV, storage=Storage.DATASETS,
        tables=(TableInfo(dataset_id, (ColumnInfo("region", "TEXT"), ColumnInfo("amount", "REAL")), 2),),
        owner=owner, shared=shared))


# --- Migration -------------------------------------------------------------------------

def test_migration_adds_owner_and_sharing_to_existing_data(tmp_path):
    db = tmp_path / "old.db"
    app_db.migrate(db, app_db.MIGRATIONS[:4])
    conn = app_db.connect(db)
    with conn:
        conn.execute("INSERT INTO dashboards VALUES ('d', 'Old', '', 'now', 'now')")
    conn.close()
    assert app_db.migrate(db) == 5
    conn = app_db.connect(db)
    row = conn.execute("SELECT owner, shared FROM dashboards").fetchone()
    conn.close()
    assert tuple(row) == (None, 0)  # unowned and private: administrators only


def test_audit_log_cannot_be_changed():
    audit.record(None, "test.event", "x", "1", "detail")
    conn = app_db.connect(config.get_app_db_path())
    for statement in ("UPDATE audit_log SET detail = 'changed'", "DELETE FROM audit_log"):
        with pytest.raises(sqlite3.IntegrityError, match="cannot be changed"):
            conn.execute(statement)
    conn.close()
    assert events() == [("test.event", "", "detail")]


def test_audit_filters_treat_wildcards_literally():
    audit.record(None, "user_x.thing")
    audit.record(None, "userAx.thing")
    assert [e.action for e in audit.recent(action_prefix="user_")] == ["user_x.thing"]


def test_audit_failure_never_breaks_the_action(monkeypatch, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("")
    monkeypatch.setenv("INSIGHTSQL_APP_DB_PATH", str(blocker / "app.db"))  # a folder that cannot exist
    audit.record(None, "anything")  # no exception


# --- Settings --------------------------------------------------------------------------

def test_auth_mode_and_lists(monkeypatch):
    assert config.get_auth_mode() == "none"
    monkeypatch.setenv("INSIGHTSQL_AUTH", " OIDC ")
    assert config.get_auth_mode() == "oidc"
    monkeypatch.setenv("INSIGHTSQL_AUTH", "password")
    with pytest.raises(ValueError):
        config.get_auth_mode()
    monkeypatch.setenv("INSIGHTSQL_ALLOWED_SIGNINS", " Ana@Example.com, @Corp.io ,")
    assert config.get_allowed_signins() == {"ana@example.com", "@corp.io"}


@pytest.mark.parametrize("value, expected", [(None, "viewer"), ("editor", "editor"), ("admin", "viewer"),
                                             ("bogus", "viewer")])
def test_default_role_is_never_admin(monkeypatch, value, expected):
    if value:
        monkeypatch.setenv("INSIGHTSQL_DEFAULT_ROLE", value)
    assert config.get_default_role() == expected


# --- Sign-in ---------------------------------------------------------------------------

def test_admin_email_becomes_admin(store):
    user = store.sign_in(claims(ADMIN))
    assert user.is_admin and user.signed_in and user.last_login_at
    assert events("user.") == [("user.created", ADMIN, "role admin")]


def test_uninvited_person_is_refused_and_recorded(store):
    with pytest.raises(AccountError, match="do not have access"):
        store.sign_in(claims(ANA))
    assert store.list() == []
    assert events() == [("user.sign_in_refused", ANA, f"{ANA}: not invited")]


def test_allowed_domain_signs_in_with_default_role(store, monkeypatch):
    monkeypatch.setenv("INSIGHTSQL_ALLOWED_SIGNINS", "@example.com")
    monkeypatch.setenv("INSIGHTSQL_DEFAULT_ROLE", "editor")
    assert store.sign_in(claims(ANA)).role == "editor"
    with pytest.raises(AccountError):
        store.sign_in(claims(BEN))  # other domain
    with pytest.raises(AccountError):
        store.sign_in(claims("eve@example.com.evil.io"))  # a look-alike domain is not the domain


def test_allowed_email_must_match_exactly(store, monkeypatch):
    monkeypatch.setenv("INSIGHTSQL_ALLOWED_SIGNINS", ANA)
    with pytest.raises(AccountError):
        store.sign_in(claims("bana@example.com"))  # ends with the allowed address, but is not it
    assert store.sign_in(claims(ANA)).role == "viewer"


def test_invited_person_is_linked_on_first_sign_in(store):
    admin = store.sign_in(claims(ADMIN))
    invited = store.invite(admin, " ANA@Example.com ", "viewer")
    assert invited.email == ANA and not invited.signed_in
    user = store.sign_in(claims(ANA))
    assert user.user_id == invited.user_id and user.signed_in and user.role == "viewer"
    assert store.sign_in(claims(ANA)).user_id == invited.user_id  # same identity next time


def test_same_email_from_another_identity_is_refused(people, store):
    with pytest.raises(AccountError, match="different sign-in"):
        store.sign_in(claims(ANA, sub="someone-else"))
    with pytest.raises(AccountError, match="different sign-in"):
        store.sign_in(claims(ANA, iss="https://login.microsoftonline.com/x/v2.0"))
    assert events("user.sign_in_refused")[0][2].endswith("email already linked to another sign-in")


def test_email_change_to_a_taken_address_is_refused(people, store):
    with pytest.raises(AccountError, match="belongs to another"):
        store.sign_in(claims(BEN, sub=f"sub-{ANA}"))  # Ana's identity now reports Ben's email


@pytest.mark.parametrize("bad", [{"email": ""}, {"email": "not-an-email"}, {"sub": ""}])
def test_identity_without_usable_email_is_refused(store, bad):
    with pytest.raises(AccountError, match="email"):
        store.sign_in({**claims(ADMIN), **bad})


def test_unverified_email_is_refused(store):
    with pytest.raises(AccountError, match="not verified"):
        store.sign_in(claims(ADMIN, email_verified=False))
    assert store.sign_in(claims(ADMIN, email_verified=True)).is_admin


def test_disabled_account_is_refused(people, store):
    admin, ana, _ = people
    store.set_active(admin, ana.user_id, False)
    with pytest.raises(AccountError, match="disabled"):
        store.sign_in(claims(ANA))
    store.set_active(admin, ana.user_id, True)
    assert store.sign_in(claims(ANA)).active


def test_admin_email_is_admin_again_at_each_sign_in(people, store, monkeypatch):
    admin, ana, _ = people
    monkeypatch.setenv("INSIGHTSQL_ADMIN_EMAILS", f"{ADMIN},{ANA}")
    assert store.sign_in(claims(ANA)).is_admin
    with pytest.raises(AccountError, match="INSIGHTSQL_ADMIN_EMAILS"):
        store.set_role(admin, ana.user_id, "viewer")


# --- Administration --------------------------------------------------------------------

def test_only_admins_manage_users(people, store):
    _, ana, ben = people
    for change in (lambda: store.invite(ana, "x@example.com", "admin"), lambda: store.set_role(ana, ben.user_id,
                   "admin"), lambda: store.set_active(ana, ben.user_id, False), lambda: store.assign_unowned(ana,
                   ana.user_id)):
        with pytest.raises(AccountError, match="Only administrators"):
            change()
    assert store.get(ben.user_id).role == "editor"


def test_at_least_one_admin_remains(store, monkeypatch):
    admin = store.sign_in(claims(ADMIN))
    monkeypatch.delenv("INSIGHTSQL_ADMIN_EMAILS")
    with pytest.raises(AccountError, match="your own account"):
        store.set_active(admin, admin.user_id, False)
    with pytest.raises(AccountError, match="at least one"):
        store.set_role(admin, admin.user_id, "editor")
    second = store.invite(admin, ANA, "admin")
    store.set_role(admin, admin.user_id, "editor")  # allowed now: Ana is an admin
    assert store.get(admin.user_id).role == "editor" and store.get(second.user_id).is_admin


def test_role_changes_and_invites_are_audited(people, store):
    admin, ana, _ = people
    store.set_role(admin, ana.user_id, "viewer")
    with pytest.raises(AccountError, match="already has"):
        store.invite(admin, ANA, "viewer")
    with pytest.raises(AccountError, match="valid email"):
        store.invite(admin, "nobody", "viewer")
    assert ("user.role_changed", ADMIN, f"{ANA}: editor → viewer") in events()
    assert [e[0] for e in events("user.invited")] == ["user.invited", "user.invited"]


def test_unowned_items_can_be_given_to_a_user(people, store):
    admin, ana, _ = people
    make_dataset("legacy", None)
    make_dataset("local_made", accounts.LOCAL_USER_ID)  # made without sign-in
    dsh.store().create("Old board")
    profiles.store().save("Old API", "rest", {"base_url": "https://api.example.com", "auth": "none"}, None)
    assert store.unowned_counts() == {"datasets": 2, "dashboards": 1, "connections": 1}
    assert store.assign_unowned(admin, ana.user_id) == {"datasets": 2, "dashboards": 1, "connections": 1}
    assert store.unowned_counts() == {"datasets": 0, "dashboards": 0, "connections": 0}
    assert data_access.catalog().get(DEMO_DATASET_ID).owner is None  # the built-in data stays everyone's
    assert {d.dataset_id for d in data_access.datasets(ana)} == {DEMO_DATASET_ID, "legacy", "local_made"}


# --- Access rules ----------------------------------------------------------------------

VIEWER = User("v", "v@x.io", "", "viewer")
EDITOR = User("e", "e@x.io", "", "editor")
ADMIN_USER = User("a", "a@x.io", "", "admin")
DISABLED_ADMIN = User("d", "d@x.io", "", "admin", active=False)


@pytest.mark.parametrize("user, owner, shared, builtin, view, change", [
    (None, "x", False, False, True, True),  # the system
    (VIEWER, "x", False, False, False, False),
    (VIEWER, "x", True, False, True, False),
    (VIEWER, None, False, True, True, False),
    (VIEWER, "v", False, False, True, False),  # a viewer cannot change even their own (e.g. after a demotion)
    (EDITOR, "e", False, False, True, True),
    (EDITOR, "x", True, False, True, False),
    (EDITOR, None, False, False, False, False),  # unowned: administrators only
    (ADMIN_USER, "x", False, False, True, True),
    (ADMIN_USER, None, False, False, True, True),
    (DISABLED_ADMIN, "x", True, False, False, False),
])
def test_access_matrix(user, owner, shared, builtin, view, change):
    assert can_view(user, owner, shared, builtin) is view
    assert can_change(user, owner) is change


def test_private_datasets_are_invisible_to_others(people, seeded_db):
    admin, ana, ben = people
    make_dataset("ana_private", ana.user_id)
    make_dataset("ana_shared", ana.user_id, shared=True)
    assert {d.dataset_id for d in data_access.datasets(ben)} == {DEMO_DATASET_ID, "ana_shared"}
    assert {d.dataset_id for d in data_access.datasets(admin)} == {DEMO_DATASET_ID, "ana_private", "ana_shared"}
    with pytest.raises(data_access.UnknownDatasetError):  # same error as a dataset that does not exist
        data_access.target("ana_private", seeded_db, ben)
    assert data_access.target("ana_private", seeded_db, ana).scope == {"ana_private"}
    assert data_access.target("ana_shared", seeded_db, ben).scope == {"ana_shared"}


def test_sharing_a_dataset_can_be_undone(people, seeded_db):
    _, ana, ben = people
    make_dataset("sales_eu", ana.user_id)
    catalog = data_access.catalog()
    assert catalog.set_shared("sales_eu", True).shared
    assert "sales_eu" in {d.dataset_id for d in data_access.datasets(ben)}
    catalog.set_shared("sales_eu", False)
    assert "sales_eu" not in {d.dataset_id for d in data_access.datasets(ben)}
    with pytest.raises(Exception, match="always available"):
        catalog.set_shared(DEMO_DATASET_ID, False)


def test_dashboards_are_private_until_shared(people, seeded_db):
    _, ana, ben = people
    store = dsh.store()
    board = store.create("Ana's board", owner=ana.user_id)
    assert [d.name for d in store.list(ana)] == ["Ana's board"] and store.list(ben) == []
    store.set_shared(board.dashboard_id, True)
    assert [d.name for d in store.list(ben)] == ["Ana's board"]
    copy = store.duplicate(board.dashboard_id, "Ben's copy", owner=ben.user_id)
    assert copy.owner == ben.user_id and not copy.shared


def test_shared_dashboard_does_not_reveal_a_private_dataset(people, seeded_db):
    _, ana, ben = people
    make_dataset("ana_private", ana.user_id)
    store = dsh.store()
    board = store.set_shared(store.create("Board", owner=ana.user_id).dashboard_id, True)
    widget = store.add_widget(board.dashboard_id, "By region", "", "ana_private",
                              "SELECT region, SUM(amount) AS total FROM ana_private GROUP BY region", "bar",
                              demo_db=seeded_db, user=ana)
    assert dsh.run(widget, seeded_db, user=ana).error is None
    result = dsh.run(widget, seeded_db, user=ben)
    assert result.data is None and "not shared with you" in result.error
    data_access.catalog().set_shared("ana_private", True)
    assert dsh.run(widget, seeded_db, user=ben).error is None


def test_charts_cannot_be_added_from_a_dataset_the_user_cannot_read(people, seeded_db):
    _, ana, ben = people
    make_dataset("ana_private", ana.user_id)
    board = dsh.store().create("Ben's", owner=ben.user_id)
    with pytest.raises(dsh.DashboardError, match="not available"):
        dsh.store().add_widget(board.dashboard_id, "Peek", "", "ana_private", "SELECT * FROM ana_private", "bar",
                               demo_db=seeded_db, user=ben)


def test_connections_are_listed_for_their_owner_only(people, monkeypatch):
    admin, ana, ben = people
    store = profiles.store()
    store.save("Ana API", "rest", {"base_url": "https://api.example.com", "auth": "none"}, None, owner=ana.user_id)
    assert [p.name for p in store.list(ana)] == ["Ana API"]
    assert store.list(ben) == []
    assert [p.name for p in store.list(admin)] == ["Ana API"]
    updated = store.save("Ana API v2", "rest", {"base_url": "https://api.example.com", "auth": "none"}, None,
                         connection_id="ana_api", owner=admin.user_id)
    assert updated.owner == ana.user_id  # an update keeps the owner


def test_imports_record_their_owner(people, seeded_db):
    _, ana, _ = people
    from tests.test_ingest_store import prepare  # the import tests' helper
    from src.ingest import store as ingest_store
    catalog = DatasetCatalog(config.get_app_db_path())
    dataset = ingest_store.save_import(
        name="Sales", description="", confirmed_destructive=True, catalog=catalog,
        datasets_db=config.get_datasets_db_path(), uploads_dir=config.get_uploads_dir(), owner=ana.user_id,
        **prepare())
    assert data_access.catalog().get(dataset.dataset_id).owner == ana.user_id


# --- History ---------------------------------------------------------------------------

def test_history_is_kept_per_user(seeded_db):
    question, other = demo_queries.demo_questions()[:2]
    answer_question(seeded_db, question, user_id="u_ana")
    answer_question(seeded_db, other, user_id="u_ben")
    answer_question(seeded_db, question)  # without sign-in
    assert [r["question"] for r in database.recent_history(seeded_db, user_id="u_ana")] == [question]
    assert len(database.recent_history(seeded_db, user_id="u_ben")) == 1
    assert len(database.recent_history(seeded_db)) == 3
    assert database.recent_history(seeded_db, user_id="u_nobody") == []
