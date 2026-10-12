"""The Docker deployment for real (Phase 09): image, the three services, the proxy, the daily
backup and data surviving a restart. Builds the image, so it is slow the first time.

Runs only where `docker compose` works; skipped with the reason shown otherwise. Uses its own
Compose project, settings file, ports, backup folder and data volume (all removed afterwards);
never the project's .env, ./backups or a real deployment.
"""

import os
import shutil
import subprocess
import time
import urllib.request
import uuid

from pathlib import Path

import pytest

from tests.conftest import unused_port

pytestmark = pytest.mark.docker
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Stack:
    def __init__(self, tmp):
        self.name = f"insightsql-test-{uuid.uuid4().hex[:8]}"
        self.http_port = unused_port()
        # Inside the project: Docker Desktop can only mount folders it shares, which may exclude /tmp.
        self.backups = Path(PROJECT_ROOT) / "test-results" / self.name / "backups"
        self.backups.mkdir(parents=True)
        self.backups.chmod(0o777)  # the container's user (uid 1000) may differ from this one
        env_file = tmp / "test.env"
        env_file.write_text("INSIGHTSQL_AUTH=none\nINSIGHTSQL_LOG_LEVEL=WARNING\n")
        self.env = {**os.environ, "INSIGHTSQL_ENV_FILE": str(env_file), "BACKUP_DIR": str(self.backups),
                    "HTTP_PORT": str(self.http_port), "HTTPS_PORT": str(unused_port()),
                    "INSIGHTSQL_BACKUP_AT": "00:00"}  # always in the past: the worker backs up at once

    def compose(self, *args, check=True, timeout=600):
        return subprocess.run(["docker", "compose", "-p", self.name, *args], cwd=PROJECT_ROOT, env=self.env,
                              capture_output=True, text=True, check=check, timeout=timeout)

    def python(self, service, code):
        return self.compose("exec", "-T", service, "python", "-c", code).stdout.strip()

    def history(self):
        return int(self.python("app", "from src import database, config; "
                                      "print(database.history_count(config.get_db_path()))"))

    @property
    def url(self):
        return f"http://localhost:{self.http_port}"


def _compose_available() -> str | None:
    try:
        subprocess.run(["docker", "compose", "version"], check=True, capture_output=True, timeout=20)
        subprocess.run(["docker", "compose", "ls"], check=True, capture_output=True, timeout=20)
    except (subprocess.SubprocessError, OSError):
        return "docker compose is not available"
    return None


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    reason = _compose_available()
    if reason:
        pytest.skip(reason)
    s = Stack(tmp_path_factory.mktemp("deploy"))
    try:
        s.compose("up", "-d", "--build", "--wait", "--wait-timeout", "300", timeout=900)
        yield s
    finally:
        s.compose("down", "-v", "--remove-orphans", check=False, timeout=300)
        shutil.rmtree(s.backups.parent, ignore_errors=True)


def _get(url, attempts=30):
    for _ in range(attempts):
        try:
            return urllib.request.urlopen(url, timeout=5)
        except OSError:
            time.sleep(1)
    raise AssertionError(f"{url} did not answer")


def test_image_has_no_secrets_or_data_and_runs_as_a_normal_user(stack):
    assert stack.compose("exec", "-T", "app", "id", "-u").stdout.strip() == "1000"
    found = stack.compose("exec", "-T", "app", "sh", "-c",
                          "find /app -name .env -o -name secrets.toml -o -name '*.db'").stdout.strip()
    assert found == ""


def test_app_is_reached_through_the_proxy(stack):
    health = _get(f"{stack.url}/_stcore/health")
    assert health.status == 200
    page = _get(stack.url)
    assert page.status == 200 and page.headers["X-Content-Type-Options"] == "nosniff"
    assert "Server" not in page.headers
    ps = stack.compose("ps", "--format", "{{.Service}} {{.Publishers}}").stdout
    app_line = next(line for line in ps.splitlines() if line.startswith("app "))
    assert "->" not in app_line  # the app itself is not published


def test_the_worker_makes_the_daily_backup(stack):
    for _ in range(60):
        backups = [p for p in stack.backups.iterdir() if (p / "manifest.json").exists()]
        if backups:
            break
        time.sleep(1)
    assert backups, stack.compose("logs", "worker").stdout
    assert (backups[0] / "insightsql.db").exists() and (backups[0] / "app.db").exists()


def test_data_survives_replacing_the_containers(stack):
    stack.python("app", "from src import database, config; "
                        "database.add_history(config.get_db_path(), 'kept', 'SELECT 1', 'success')")
    before = stack.history()
    stack.compose("down")  # removes the containers, keeps the volume
    stack.compose("up", "-d", "--wait", "--wait-timeout", "300", timeout=600)
    assert stack.history() == before


def test_misconfigured_sign_in_stops_the_start(stack):
    result = stack.compose("run", "--rm", "--no-deps", "-e", "INSIGHTSQL_AUTH=oidc", "app", check=False)
    assert result.returncode != 0
    assert "secrets.toml is missing" in result.stdout and "InsightSQL did not start" in result.stdout
