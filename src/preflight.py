"""Start-up checks for a deployed app (run by the Docker image before Streamlit starts).

Errors stop the start with a clear message, instead of an app that fails later or, worse,
runs open: invalid settings, sign-in switched on but not set up, a data folder the app cannot
write to. Warnings are printed and the app starts: sign-in switched off, no encryption key for
saved connection passwords, a redirect address that is not https.

Messages name settings only, never their values.
"""

import os
import tomllib
from pathlib import Path

from src import config, database
from src.ui.auth import setup_problems


def _writable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".write-test"
        probe.write_text("ok")
        probe.unlink()
        return True
    except OSError:
        return False


def _secrets(path: Path) -> dict | None:
    try:
        return tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return None


def check(secrets_path: Path | None = None) -> tuple[list[str], list[str]]:
    """(errors, warnings) for the current environment."""
    errors, warnings = [], []
    try:
        auth = config.get_auth_mode()
    except ValueError as exc:
        errors.append(str(exc))
        auth = None
    try:
        config.get_ai_provider()
    except ValueError as exc:
        errors.append(str(exc))

    if auth == "oidc":
        secrets = _secrets(secrets_path or config.PROJECT_ROOT / ".streamlit" / "secrets.toml")
        if secrets is None:
            errors.append("INSIGHTSQL_AUTH=oidc, but .streamlit/secrets.toml is missing or cannot be read.")
        else:
            settings = secrets.get("auth")
            errors += setup_problems(settings)
            redirect = str((settings or {}).get("redirect_uri") or "")
            if redirect and not redirect.startswith("https://") and "://localhost" not in redirect:
                warnings.append("[auth] redirect_uri is not https://: sign-in providers refuse it for a "
                                "public address.")
        if not config.get_admin_emails():
            warnings.append("INSIGHTSQL_ADMIN_EMAILS is empty: nobody can manage users.")
    elif auth == "none":
        warnings.append("Sign-in is OFF (INSIGHTSQL_AUTH=none): anyone who can open this app has full "
                        "rights. Use this only on a private network; set INSIGHTSQL_AUTH=oidc for a "
                        "public server.")

    if not config.get_secret_key():
        warnings.append("INSIGHTSQL_SECRET_KEY is not set: connections to databases and APIs cannot save "
                        "passwords or tokens.")

    folders = {config.get_db_path().parent, config.get_app_db_path().parent,
               config.get_datasets_db_path().parent, config.get_uploads_dir()}
    errors += [f"The data folder {folder} is not writable by this user." for folder in sorted(folders)
               if not _writable(folder)]
    return errors, warnings


def main() -> int:
    errors, warnings = check(Path(os.environ["INSIGHTSQL_SECRETS_FILE"])
                             if os.getenv("INSIGHTSQL_SECRETS_FILE") else None)
    for message in warnings:
        print(f"WARNING: {message}", flush=True)
    for message in errors:
        print(f"ERROR: {message}", flush=True)
    if errors:
        print("InsightSQL did not start. Fix the settings above (see DEPLOYMENT.md).", flush=True)
        return 1
    # A new install is complete from the start (not only after the first visit): the worker and
    # the first backup find the demo database. An existing one only gains missing tables.
    database.ensure_database(config.get_db_path())
    return 0
