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


def get_db_path() -> Path:
    """Return the SQLite database path, resolved relative to the project root."""
    path = Path(os.getenv("INSIGHTSQL_DB_PATH", "data/insightsql.db"))
    return path if path.is_absolute() else PROJECT_ROOT / path


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
