"""Application configuration loaded from environment variables (.env supported)."""

import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_ROOT / ".env")

AI_PROVIDERS = ("gemini", "huggingface")
DEFAULT_AI_PROVIDER = "gemini"
# Verified against https://ai.google.dev/gemini-api/docs/models (2026-10-10): stable, and
# described as the fastest, most cost-effective 3.5 model; free tier available.
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"
DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com"
DEFAULT_GEMINI_TIMEOUT_SECONDS = 30.0
DEFAULT_HF_BASE_URL = "https://router.huggingface.co/v1"
DEFAULT_HF_MODEL = "Qwen/Qwen2.5-Coder-32B-Instruct"
DEFAULT_HF_TIMEOUT_SECONDS = 30.0
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _project_path(name: str, default: str) -> Path:
    """A file path from the environment, resolved relative to the project root."""
    path = Path(os.getenv(name) or default)
    return path if path.is_absolute() else PROJECT_ROOT / path


def get_db_path() -> Path:
    """Return the SQLite database path, resolved relative to the project root."""
    return _project_path("INSIGHTSQL_DB_PATH", "data/insightsql.db")


def get_app_db_path() -> Path:
    """App metadata store (dataset catalog and, later, connections, dashboards, jobs).
    Kept apart from the demo database, which reseeding deletes."""
    return _project_path("INSIGHTSQL_APP_DB_PATH", "data/app.db")


def get_datasets_db_path() -> Path:
    """Store for imported and synchronised datasets (used from Phase 02)."""
    return _project_path("INSIGHTSQL_DATASETS_DB_PATH", "data/datasets.db")


def get_uploads_dir() -> Path:
    """Folder for original uploaded files, kept unchanged (one sub-folder per dataset)."""
    return _project_path("INSIGHTSQL_UPLOADS_DIR", "data/uploads")


def _positive_int(name: str, default: int) -> int:
    """A positive whole number from the environment; the default if unset or invalid."""
    try:
        value = int(os.getenv(name, default))
    except ValueError:
        return default
    return value if value > 0 else default


def get_import_max_mb() -> int:
    """Largest file accepted for import, in MB. Keep [server] maxUploadSize in
    .streamlit/config.toml at least this large (Streamlit enforces its own limit first)."""
    return _positive_int("INSIGHTSQL_IMPORT_MAX_MB", 25)


def get_import_max_rows() -> int:
    return _positive_int("INSIGHTSQL_IMPORT_MAX_ROWS", 200_000)


def get_import_max_columns() -> int:
    return _positive_int("INSIGHTSQL_IMPORT_MAX_COLUMNS", 200)


def get_secret_key() -> str | None:
    """Key that encrypts saved connection passwords and tokens (Fernet). Never log or display it."""
    key = (os.getenv("INSIGHTSQL_SECRET_KEY") or "").strip()
    return key or None


def get_allowed_private_hosts() -> frozenset[str]:
    """Hosts on private, loopback or link-local networks that connections may reach, written as
    ``host`` or ``host:port`` (comma-separated). Empty by default: only public addresses."""
    raw = os.getenv("INSIGHTSQL_ALLOWED_PRIVATE_HOSTS") or ""
    return frozenset(item.strip().lower() for item in raw.split(",") if item.strip())


def get_connector_timeout() -> float:
    """Seconds to wait when connecting to, or reading from, a database server or API."""
    return _timeout("INSIGHTSQL_CONNECTOR_TIMEOUT_SECONDS", 15.0)


def get_refresh_max_attempts() -> int:
    """Attempts per refresh when the source fails temporarily (network, timeouts)."""
    return _positive_int("INSIGHTSQL_REFRESH_MAX_ATTEMPTS", 3)


def get_refresh_retry_seconds() -> float:
    """Wait before retrying a failed refresh (doubles each attempt). 0 = no wait (tests)."""
    try:
        value = float(os.getenv("INSIGHTSQL_REFRESH_RETRY_SECONDS", 30))
    except ValueError:
        return 30.0
    return max(0.0, value)


AUTH_MODES = ("none", "oidc")
ROLES = ("viewer", "editor", "admin")


def get_auth_mode() -> str:
    """'none' (default): no sign-in, one local user with full rights — only for an app reachable
    from this computer alone. 'oidc': sign-in with Google, Microsoft or another OpenID Connect
    provider configured in ``.streamlit/secrets.toml``. Any other value is refused."""
    mode = (os.getenv("INSIGHTSQL_AUTH") or "none").strip().lower()
    if mode not in AUTH_MODES:
        raise ValueError(f"INSIGHTSQL_AUTH must be one of: {', '.join(AUTH_MODES)}.")
    return mode


def _email_list(name: str) -> frozenset[str]:
    raw = os.getenv(name) or ""
    return frozenset(item.strip().lower() for item in raw.split(",") if item.strip())


def get_admin_emails() -> frozenset[str]:
    """Accounts that are always administrators when they sign in (comma-separated emails)."""
    return _email_list("INSIGHTSQL_ADMIN_EMAILS")


def get_allowed_signins() -> frozenset[str]:
    """Who may sign in without an invitation: emails (``ana@example.com``) and whole domains
    (``@example.com``), comma-separated. Empty (default): only administrators and invited users."""
    return _email_list("INSIGHTSQL_ALLOWED_SIGNINS")


def get_default_role() -> str:
    """Role given to people who sign in through ``INSIGHTSQL_ALLOWED_SIGNINS``; 'viewer' if unset
    or invalid (never 'admin': administrators are named in ``INSIGHTSQL_ADMIN_EMAILS``)."""
    role = (os.getenv("INSIGHTSQL_DEFAULT_ROLE") or "viewer").strip().lower()
    return role if role in ("viewer", "editor") else "viewer"


LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def get_log_level() -> str:
    """Level for the app's own loggers; WARNING if unset or invalid."""
    level = (os.getenv("INSIGHTSQL_LOG_LEVEL") or "WARNING").strip().upper()
    return level if level in LOG_LEVELS else "WARNING"


def get_ai_provider() -> str:
    """Which AI service AI Mode uses: 'gemini' (default) or 'huggingface'."""
    provider = (os.getenv("AI_PROVIDER") or DEFAULT_AI_PROVIDER).strip().lower()
    if provider not in AI_PROVIDERS:
        raise ValueError(f"AI_PROVIDER must be one of: {', '.join(AI_PROVIDERS)}.")
    return provider


def _secure_url(name: str, default: str) -> str:
    """HTTPS is required because a secret is sent with every request; plain HTTP is
    accepted only for a server on this machine, as used by the tests."""
    url = (os.getenv(name) or default).strip().rstrip("/")
    parsed = urlparse(url)
    if not parsed.netloc or not (
        parsed.scheme == "https" or (parsed.scheme == "http" and parsed.hostname in _LOCAL_HOSTS)
    ):
        raise ValueError(f"{name} must be an https:// URL.")
    return url


def _timeout(name: str, default: float) -> float:
    """Seconds to wait. Falls back to the default if unset or invalid."""
    try:
        timeout = float(os.getenv(name, default))
    except ValueError:
        return default
    return timeout if timeout > 0 else default


def get_gemini_api_key() -> str | None:
    """Gemini API key, or None if unset. Never log or display it."""
    key = (os.getenv("GEMINI_API_KEY") or "").strip()
    return key or None


def get_gemini_model() -> str:
    return (os.getenv("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL).strip()


def get_gemini_base_url() -> str:
    return _secure_url("GEMINI_BASE_URL", DEFAULT_GEMINI_BASE_URL)


def get_gemini_timeout() -> float:
    return _timeout("GEMINI_TIMEOUT_SECONDS", DEFAULT_GEMINI_TIMEOUT_SECONDS)


def get_hf_token() -> str | None:
    """Hugging Face access token, or None if unset. Never log or display it."""
    token = (os.getenv("HF_TOKEN") or "").strip()
    return token or None


def get_hf_base_url() -> str:
    """Inference API URL (https only; the token is sent with every request)."""
    return _secure_url("HF_BASE_URL", DEFAULT_HF_BASE_URL)


def get_hf_model() -> str:
    return (os.getenv("HF_MODEL") or DEFAULT_HF_MODEL).strip()


def get_hf_timeout() -> float:
    return _timeout("HF_TIMEOUT_SECONDS", DEFAULT_HF_TIMEOUT_SECONDS)
