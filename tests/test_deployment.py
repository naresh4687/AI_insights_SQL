"""Deployment (Phase 09): backups and restore, the daily backup schedule, the start-up checks, and
the Docker / Compose / Caddy files. The containers themselves are tested in
tests/test_deployment_docker.py (marked docker)."""

import re
import sqlite3
import tomllib
from datetime import datetime, time
from pathlib import Path

import pytest

from scripts import backup as backup_cli
from scripts import refresh_worker
from src import backup, config, database, preflight

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _own_demo_database(tmp_path, monkeypatch):
    """conftest isolates the app and dataset stores; backups and restores also touch the demo
    database, so every test here gets its own copy too (never data/insightsql.db)."""
    monkeypatch.setenv("INSIGHTSQL_DB_PATH", str(tmp_path / "insightsql.db"))
    assert config.get_db_path().parent == tmp_path


# --- Backups --------------------------------------------------------------------------------

@pytest.fixture
def live(tmp_path):
    """The live data in the test folder (conftest points the config there): demo database with
    one history entry, app database, and an uploaded file."""
    database.ensure_database(config.get_db_path())
    database.add_history(config.get_db_path(), "before backup", "SELECT 1", "success")
    with sqlite3.connect(config.get_app_db_path()) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS notes (text TEXT)")
        conn.execute("INSERT INTO notes VALUES ('kept')")
    uploads = config.get_uploads_dir() / "ds1"
    uploads.mkdir(parents=True)
    (uploads / "original.csv").write_text("a,b\n1,2\n")
    return backup.live_targets()


def history(path: Path | None = None) -> int:
    return database.history_count(path or config.get_db_path())


def test_backup_contains_checked_copies_and_a_manifest(tmp_path, live):
    folder = backup.create_backup(tmp_path / "backups", now=datetime(2026, 10, 12, 2, 0))
    assert folder.name == "20261012-020000"
    assert sorted(p.name for p in folder.iterdir()) == ["app.db", "insightsql.db", "manifest.json", "uploads"]
    for name in ("app.db", "insightsql.db"):
        backup.check_database(folder / name)
    assert history(folder / "insightsql.db") == 1
    assert (folder / "uploads" / "ds1" / "original.csv").read_text() == "a,b\n1,2\n"
    manifest = (folder / "manifest.json").read_text()
    assert '"query_history": 1' in manifest and '"sales": 600' in manifest and '"uploads_files": 1' in manifest


def test_backup_is_consistent_while_a_write_is_in_progress(tmp_path, live):
    writer = sqlite3.connect(config.get_db_path())
    writer.execute("BEGIN IMMEDIATE")
    writer.execute("INSERT INTO query_history (question, generated_sql, status, created_at) "
                   "VALUES ('uncommitted', 'SELECT 1', 'success', '2026-10-12T02:00:00+00:00')")
    try:
        folder = backup.create_backup(tmp_path / "backups")
    finally:
        writer.rollback()
        writer.close()
    assert history(folder / "insightsql.db") == 1  # the committed state, not half a write


def test_only_the_newest_backups_are_kept(tmp_path, live):
    root = tmp_path / "backups"
    for day in range(1, 6):
        backup.create_backup(root, keep=3, now=datetime(2026, 10, day, 2, 0))
    assert [p.name for p in backup.list_backups(root)] == ["20261003-020000", "20261004-020000", "20261005-020000"]
    assert backup.prune(root, 0) and len(backup.list_backups(root)) == 1  # at least one is always kept


def test_a_failed_backup_leaves_nothing_behind(tmp_path, live):
    config.get_app_db_path().write_bytes(b"not a database")
    root = tmp_path / "backups"
    with pytest.raises(Exception):
        backup.create_backup(root)
    assert list(root.iterdir()) == []


def test_two_backups_in_the_same_second_are_refused(tmp_path, live):
    now = datetime(2026, 10, 12, 2, 0)
    backup.create_backup(tmp_path / "b", now=now)
    with pytest.raises(backup.BackupError, match="already exists"):
        backup.create_backup(tmp_path / "b", now=now)


def test_restore_brings_back_the_data_and_the_uploads(tmp_path, live):
    folder = backup.create_backup(tmp_path / "backups")
    database.add_history(config.get_db_path(), "after backup", "SELECT 1", "success")
    (config.get_uploads_dir() / "ds1" / "original.csv").write_text("changed")
    (config.get_uploads_dir() / "ds2").mkdir()
    assert history() == 2

    assert backup.restore_backup(folder) == ["insightsql.db", "app.db", "uploads"]
    assert history() == 1
    with sqlite3.connect(config.get_app_db_path()) as conn:
        assert conn.execute("SELECT text FROM notes").fetchall() == [("kept",)]
    assert sorted(p.name for p in config.get_uploads_dir().iterdir()) == ["ds1"]
    assert (config.get_uploads_dir() / "ds1" / "original.csv").read_text() == "a,b\n1,2\n"


def test_a_damaged_backup_is_refused_before_anything_changes(tmp_path, live):
    folder = backup.create_backup(tmp_path / "backups")
    (folder / "app.db").write_bytes(b"damaged")
    database.add_history(config.get_db_path(), "after backup", "SELECT 1", "success")
    with pytest.raises(backup.BackupError, match="app.db"):
        backup.restore_backup(folder)
    assert history() == 2  # untouched


def test_an_incomplete_folder_is_not_a_backup(tmp_path, live):
    (tmp_path / "20261012-020000").mkdir()
    with pytest.raises(backup.BackupError, match="not a complete backup"):
        backup.restore_backup(tmp_path / "20261012-020000")
    assert backup.list_backups(tmp_path) == []


@pytest.mark.parametrize("now, last, due", [
    (datetime(2026, 10, 12, 1, 59), None, False),                      # before the time
    (datetime(2026, 10, 12, 2, 0), None, True),                        # at the time
    (datetime(2026, 10, 12, 9, 0), datetime(2026, 10, 11, 2, 0), True),   # started late: at once
    (datetime(2026, 10, 12, 9, 0), datetime(2026, 10, 12, 1, 0), True),   # a manual one earlier does not count
    (datetime(2026, 10, 12, 9, 0), datetime(2026, 10, 12, 2, 0, 5), False),  # already done today
])
def test_daily_backup_schedule(now, last, due):
    assert backup.backup_due(now, time(2, 0), last) is due


def test_the_worker_backs_up_once_when_due(tmp_path, live, capsys):
    root = tmp_path / "backups"
    refresh_worker.backup_if_due(root, time(0, 0), keep=7)
    refresh_worker.backup_if_due(root, time(0, 0), keep=7)
    assert len(backup.list_backups(root)) == 1
    assert capsys.readouterr().out.count("Backup created") == 1


def test_a_failed_scheduled_backup_is_reported_not_raised(tmp_path, live, capsys):
    blocked = tmp_path / "file-not-folder"
    blocked.write_text("")
    refresh_worker.backup_if_due(blocked, time(0, 0), keep=7)
    assert "Backup failed" in capsys.readouterr().err


def test_backup_time_must_be_hh_mm():
    with pytest.raises(SystemExit):
        refresh_worker.main(["--loop", "--backup-at", "2am"])


def test_backup_command_line(tmp_path, live, capsys):
    root = tmp_path / "backups"
    assert backup_cli.main(["--dir", str(root), "create"]) == 0
    name = backup.list_backups(root)[0].name
    assert backup_cli.main(["--dir", str(root), "list"]) == 0
    assert name in capsys.readouterr().out
    database.add_history(config.get_db_path(), "after", "SELECT 1", "success")
    assert backup_cli.main(["--dir", str(root), "restore", name]) == 1  # needs --yes
    assert history() == 2
    assert backup_cli.main(["--dir", str(root), "restore", name, "--yes"]) == 0
    assert history() == 1
    assert backup_cli.main(["--dir", str(root), "restore", "20000101-000000", "--yes"]) == 1


# --- Start-up checks ------------------------------------------------------------------------

GOOD_SECRETS = """
[auth]
redirect_uri = "https://insights.example.com/oauth2callback"
cookie_secret = "a-random-value-that-is-long-enough-1234567890"
[auth.google]
client_id = "id"
client_secret = "very-secret-client-value"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
"""


def test_sign_in_off_starts_with_a_warning(monkeypatch):
    monkeypatch.setenv("INSIGHTSQL_AUTH", "none")
    errors, warnings = preflight.check()
    assert errors == []
    assert any("Sign-in is OFF" in w for w in warnings)


def test_invalid_settings_stop_the_start(monkeypatch):
    monkeypatch.setenv("INSIGHTSQL_AUTH", "password")
    monkeypatch.setenv("AI_PROVIDER", "someone-else")
    errors, _ = preflight.check()
    assert any("INSIGHTSQL_AUTH" in e for e in errors) and any("AI_PROVIDER" in e for e in errors)


def test_sign_in_on_without_its_settings_stops_the_start(tmp_path, monkeypatch):
    monkeypatch.setenv("INSIGHTSQL_AUTH", "oidc")
    errors, _ = preflight.check(tmp_path / "missing.toml")
    assert any("secrets.toml is missing" in e for e in errors)
    incomplete = tmp_path / "secrets.toml"
    incomplete.write_text('[auth]\nredirect_uri = "https://x.example.com/oauth2callback"\n')
    errors, _ = preflight.check(incomplete)
    assert any("cookie_secret" in e for e in errors)


def test_sign_in_on_and_set_up_starts(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("INSIGHTSQL_AUTH", "oidc")
    monkeypatch.setenv("INSIGHTSQL_ADMIN_EMAILS", "admin@example.com")
    monkeypatch.setenv("INSIGHTSQL_SECRET_KEY", "x" * 44)
    secrets = tmp_path / "secrets.toml"
    secrets.write_text(GOOD_SECRETS)
    assert preflight.check(secrets) == ([], [])
    monkeypatch.setenv("INSIGHTSQL_SECRETS_FILE", str(secrets))
    assert not config.get_db_path().exists()
    assert preflight.main() == 0
    assert database.history_count(config.get_db_path()) == 0  # created on start
    out = capsys.readouterr().out
    assert "very-secret-client-value" not in out and "x" * 44 not in out


def test_http_redirect_address_is_flagged(tmp_path, monkeypatch):
    monkeypatch.setenv("INSIGHTSQL_AUTH", "oidc")
    secrets = tmp_path / "secrets.toml"
    secrets.write_text(GOOD_SECRETS.replace("https://insights", "http://insights"))
    _, warnings = preflight.check(secrets)
    assert any("redirect_uri is not https" in w for w in warnings)


def test_missing_encryption_key_is_a_warning(monkeypatch):
    monkeypatch.delenv("INSIGHTSQL_SECRET_KEY", raising=False)
    errors, warnings = preflight.check()
    assert errors == [] and any("INSIGHTSQL_SECRET_KEY" in w for w in warnings)


def test_unwritable_data_folder_stops_the_start(tmp_path, monkeypatch, capsys):
    blocked = tmp_path / "file-not-folder"
    blocked.write_text("")
    monkeypatch.setenv("INSIGHTSQL_UPLOADS_DIR", str(blocked / "uploads"))
    errors, _ = preflight.check()
    assert any("not writable" in e for e in errors)
    assert preflight.main() == 1
    assert "did not start" in capsys.readouterr().out


# --- Docker, Compose and Caddy files ---------------------------------------------------------

def text(name: str) -> str:
    return (ROOT / name).read_text()


def test_image_never_contains_secrets_or_data():
    ignored = text(".dockerignore").splitlines()
    for entry in (".env", ".streamlit/secrets.toml", "data/", "backups/", "*.db", ".git/", "tests/"):
        assert entry in ignored, entry


def test_image_runs_as_a_normal_user_and_checks_settings_first():
    dockerfile = text("Dockerfile")
    assert re.search(r"^USER insightsql$", dockerfile, re.M)
    assert "HEALTHCHECK" in dockerfile and "/_stcore/health" in dockerfile
    assert 'CMD ["sh", "-c", "python scripts/preflight.py && exec streamlit run app.py"]' in dockerfile
    # Same Python as development; dependencies from the pinned requirements file.
    assert dockerfile.startswith("# ") and "FROM python:3.12-slim" in dockerfile
    assert "pip install -r requirements.txt" in dockerfile


def test_compose_keeps_data_on_a_volume_and_the_app_behind_the_proxy():
    compose = text("compose.yaml")
    for path in ("INSIGHTSQL_DB_PATH: /data/insightsql.db", "INSIGHTSQL_APP_DB_PATH: /data/app.db",
                 "INSIGHTSQL_DATASETS_DB_PATH: /data/datasets.db", "INSIGHTSQL_UPLOADS_DIR: /data/uploads"):
        assert path in compose
    app = compose.split("\n  app:\n")[1].split("\n  worker:\n")[0]
    assert "ports:" not in app and "data:/data" in app  # only the proxy is published
    worker = compose.split("\n  worker:\n")[1].split("\n  proxy:\n")[0]
    assert "refresh_worker.py --loop" in worker and "--backup-at" in worker and "data:/data" in worker
    assert "condition: service_healthy" in worker
    assert "caddy_data:/data" in compose  # certificates survive restarts


def test_sign_in_settings_are_mounted_read_only():
    assert "./.streamlit/secrets.toml:/app/.streamlit/secrets.toml:ro" in text("compose.signin.yaml")


def test_proxy_allows_the_upload_limit_and_forwards_to_the_app():
    caddy = text("deploy/Caddyfile")
    upload_mb = tomllib.loads(text(".streamlit/config.toml"))["server"]["maxUploadSize"]
    assert int(re.search(r"max_size (\d+)MB", caddy).group(1)) > upload_mb
    assert "reverse_proxy app:8501" in caddy
    assert "{$SITE_ADDRESS:http://localhost}" in caddy


def test_backups_are_not_committed():
    assert "backups/" in text(".gitignore").splitlines()
