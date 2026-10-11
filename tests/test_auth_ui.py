"""Phase 08 in the app (AppTest): the sign-in gate, role-based pages, per-user data and Users & Audit.

The identity provider is replaced by ``auth.identity`` returning fixed claims: what Streamlit's
``st.user`` holds after a real OpenID Connect sign-in.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import accounts, audit, dashboards as dsh, data_access
from src.ui import auth
from tests.test_accounts import claims, make_dataset

APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")
ADMIN, ANA, VIC = "admin@example.com", "ana@example.com", "vic@example.com"
AUTH = {"redirect_uri": "http://localhost:8501/oauth2callback", "cookie_secret": "x" * 40,
        "google": {"client_id": "id", "client_secret": "secret",
                   "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration"}}


@pytest.fixture
def oidc(seeded_db, monkeypatch):
    monkeypatch.setenv("INSIGHTSQL_DB_PATH", str(seeded_db))
    monkeypatch.setenv("INSIGHTSQL_AUTH", "oidc")
    monkeypatch.setenv("INSIGHTSQL_ADMIN_EMAILS", ADMIN)
    who = {"claims": None}
    monkeypatch.setattr(auth, "identity", lambda: who["claims"])
    return who


@pytest.fixture
def team(oidc):
    """Admin, editor Ana and viewer Vic, all with accounts."""
    store = accounts.store()
    admin = store.sign_in(claims(ADMIN))
    store.invite(admin, ANA, "editor")
    store.invite(admin, VIC, "viewer")
    return {email: store.sign_in(claims(email)) for email in (ADMIN, ANA, VIC)}


def app(who, email=None, secrets=AUTH):
    who["claims"] = claims(email) if email else None
    at = AppTest.from_file(APP_PATH, default_timeout=60)
    if secrets is not None:
        at.secrets["auth"] = secrets
    return ok(at.run())


def ok(at):
    assert not at.exception, [e.value for e in at.exception]
    return at


def text(at) -> str:
    parts = [h.proto.body for h in at.get("html")] + [m.value for m in at.markdown] + [e.value for e in at.error]
    return "\n".join(parts + [i.value for i in at.info] + [c.value for c in at.caption])


def page_titles(at) -> set[str]:
    """The pages st.navigation offered in the last run (AppTest records them as it runs)."""
    return {info["page_name"] for info in at._registered_pages.values()}


# --- The gate --------------------------------------------------------------------------

def test_without_sign_in_settings_the_app_stays_closed(oidc):
    at = app(oidc, ADMIN, secrets=None)
    assert "Sign-in is not set up yet" in text(at)
    assert "There is no [auth] section" in text(at)
    assert not at.selectbox  # no sidebar, no page


@pytest.mark.parametrize("change, problem", [
    ({"cookie_secret": "short"}, "at least 32 characters"),
    ({"redirect_uri": ""}, "needs redirect_uri"),
    ({"google": {"client_id": "id", "client_secret": "s", "server_metadata_url": "http://x/"}}, "https://"),
    ({"google": {"client_id": "id"}}, "needs client_secret"),
])
def test_incomplete_settings_are_named_without_values(oidc, change, problem):
    at = app(oidc, ADMIN, secrets={**AUTH, **change})
    assert problem in text(at)
    assert "secret\n" not in text(at) and "x" * 40 not in text(at)


def test_visitor_sees_only_the_sign_in_screen(oidc):
    at = app(oidc)
    assert "Sign in to InsightSQL" in text(at)
    assert [b.label for b in at.button] == ["Sign in with Google"]
    assert not at.selectbox and not at.chat_input


def test_uninvited_person_gets_no_access(oidc):
    at = app(oidc, "stranger@example.com")
    assert "do not have access" in text(at) and not at.selectbox
    assert audit.recent()[0].action == "user.sign_in_refused"


def test_disabled_user_is_stopped_on_the_next_click(team, oidc):
    at = app(oidc, ANA)
    assert "Dataset" in [s.label for s in at.selectbox]
    store = accounts.store()
    store.set_active(team[ADMIN], team[ANA].user_id, False)
    ok(at.run())
    assert "disabled" in text(at) and "Dataset" not in [s.label for s in at.selectbox]


def test_sidebar_shows_who_is_signed_in(team, oidc):
    at = app(oidc, ANA)
    assert ANA in text(at) and "Editor" in text(at)
    assert any(b.key == "sign_out" for b in at.button)


def test_without_sign_in_nothing_changes(seeded_db, monkeypatch):
    monkeypatch.setenv("INSIGHTSQL_DB_PATH", str(seeded_db))
    at = ok(AppTest.from_file(APP_PATH, default_timeout=60).run())
    assert not any(b.key == "sign_out" for b in at.button)
    assert {"Import Data", "Connections"} <= page_titles(at) and "Users & Audit" not in page_titles(at)


# --- Roles -----------------------------------------------------------------------------

def test_pages_follow_the_role(team, oidc):
    viewer, editor, admin = (page_titles(app(oidc, e)) for e in (VIC, ANA, ADMIN))
    assert not {"Import Data", "Connections", "Users & Audit"} & viewer and "Dashboard Studio" in viewer
    assert {"Import Data", "Connections"} <= editor and "Users & Audit" not in editor
    assert {"Import Data", "Connections", "Users & Audit"} <= admin


def test_viewer_cannot_add_answers_to_dashboards(team, oidc):
    at = app(oidc, VIC)
    ok(at.switch_page("views/analyst.py").run())
    ok(at.button(key="example_0").click().run())
    assert at.get("dataframe") and not any(p.label == "Add to dashboard" for p in at.get("popover"))


# --- Per-user data ---------------------------------------------------------------------

def test_dataset_selector_holds_only_what_the_user_may_read(team, oidc):
    make_dataset("ana_private", team[ANA].user_id)
    make_dataset("ana_shared", team[ANA].user_id, shared=True)
    options = lambda at: set(at.selectbox(key="dataset").options)  # noqa: E731
    assert options(app(oidc, ANA)) == {"Demo sales", "Ana_Private", "Ana_Shared"}
    assert options(app(oidc, VIC)) == {"Demo sales", "Ana_Shared"}
    assert options(app(oidc, ADMIN)) == {"Demo sales", "Ana_Private", "Ana_Shared"}


def test_history_is_per_user(team, oidc):
    at = app(oidc, ANA)
    ok(at.switch_page("views/analyst.py").run())
    ok(at.button(key="example_0").click().run())
    ok(at.switch_page("views/history.py").run())
    assert any(c.key.startswith("hist_") for c in at.get("flex_container") if c.key) or "#1" in text(at)
    other = app(oidc, VIC)
    ok(other.switch_page("views/history.py").run())
    assert "No history yet" in text(other)


def test_shared_dashboard_is_read_only_for_others(team, oidc):
    make_dataset("ana_sales", team[ANA].user_id, shared=True)
    store = dsh.store()
    board = store.create("Ana board", owner=team[ANA].user_id)
    store.add_widget(board.dashboard_id, "Regions", "", "ana_sales",
                     "SELECT region, SUM(amount) AS total FROM ana_sales GROUP BY region", "bar",
                     user=team[ANA])
    at = app(oidc, VIC)
    ok(at.switch_page("views/studio.py").run())
    assert "No dashboards shared with you yet" in text(at)

    store.set_shared(board.dashboard_id, True)
    ok(at.run())
    assert "Shared by" in text(at) and at.get("vega_lite_chart")
    assert at.toggle(key="studio_edit").proto.disabled
    assert not any(e.label == "Manage this dashboard" for e in at.expander)


def test_owner_shares_a_dashboard_and_it_is_audited(team, oidc):
    dsh.store().create("Mine", owner=team[ANA].user_id)
    at = app(oidc, ANA)
    ok(at.switch_page("views/studio.py").run())
    assert "only you can see it" in text(at)
    ok(at.toggle(key="studio_share_mine").set_value(True).run())
    assert dsh.store().get("mine").shared
    assert [(e.action, e.user_email) for e in audit.recent(action_prefix="dashboard.")] == [
        ("dashboard.shared", ANA)]


def test_owner_shares_a_dataset(team, oidc):
    make_dataset("ana_sales", team[ANA].user_id)
    at = app(oidc, ANA)
    ok(at.switch_page("views/datasets.py").run())
    ok(at.selectbox(key="ds_selected").set_value("ana_sales").run())
    assert "Owner: you" in text(at)
    ok(at.toggle(key="ds_share_ana_sales").set_value(True).run())
    assert data_access.catalog().get("ana_sales").shared
    assert audit.recent(action_prefix="dataset.")[0].action == "dataset.shared"


def test_viewer_cannot_share_someone_elses_dataset(team, oidc):
    make_dataset("ana_sales", team[ANA].user_id, shared=True)
    at = app(oidc, VIC)
    ok(at.switch_page("views/datasets.py").run())
    ok(at.selectbox(key="ds_selected").set_value("ana_sales").run())
    assert not any(t.key == "ds_share_ana_sales" for t in at.toggle)


# --- Users & Audit ---------------------------------------------------------------------

def test_admin_invites_and_changes_roles(team, oidc):
    at = app(oidc, ADMIN)
    ok(at.switch_page("views/users.py").run())
    at.text_input(key="users_invite_email").set_value("new@example.com")
    ok(at.selectbox(key="users_invite_role").set_value("editor").run())
    ok(at.button(key="users_invite").click().run())
    assert "Invited new@example.com as editor" in [s.value for s in at.success][0]
    new = accounts.store().by_email("new@example.com")
    ok(at.selectbox(key="users_selected").set_value(new.user_id).run())
    ok(at.selectbox(key=f"users_role_{new.user_id}").set_value("viewer").run())
    ok(at.button(key="users_save_role").click().run())
    assert accounts.store().get(new.user_id).role == "viewer"
    log = text(at)
    assert "user.role_changed" in str([e.action for e in audit.recent()]) and "Audit log" in log


def test_admin_cannot_disable_themselves(team, oidc):
    at = app(oidc, ADMIN)
    ok(at.switch_page("views/users.py").run())
    ok(at.selectbox(key="users_selected").set_value(team[ADMIN].user_id).run())
    ok(at.button(key="users_toggle_active").click().run())
    assert "cannot disable your own account" in text(at)
    assert accounts.store().get(team[ADMIN].user_id).active


def test_unowned_items_are_offered_to_an_account(team, oidc):
    make_dataset("legacy", None)
    at = app(oidc, ADMIN)
    ok(at.switch_page("views/users.py").run())
    assert "Items without an owner" in text(at)
    ok(at.selectbox(key="users_assign_to").set_value(team[ANA].user_id).run())
    ok(at.button(key="users_assign").click().run())
    assert data_access.catalog().get("legacy").owner == team[ANA].user_id
