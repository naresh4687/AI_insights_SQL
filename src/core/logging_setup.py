"""Logging for the app's own modules, with secrets redacted from every log record.

``configure_logging()`` installs a log-record factory, so redaction applies to every logger
and handler (including Streamlit's and test capture), and to exception tracebacks.
Redaction removes:
- the current values of the secret settings in ``SECRET_SETTINGS``;
- anything that looks like a known credential format (Google, GitHub, Hugging Face keys,
  bearer tokens, and ``password=``/``token=``-style pairs, e.g. inside connection URLs).
"""

import logging
import os
import re
import sys

from src import config

REDACTED = "[REDACTED]"
SECRET_SETTINGS = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "HF_TOKEN", "INSIGHTSQL_SECRET_KEY")
MIN_SECRET_LENGTH = 6  # shorter values would redact ordinary words

_PATTERNS = (
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),  # Google API keys
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),  # GitHub tokens
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bhf_[A-Za-z0-9]{20,}"),  # Hugging Face tokens
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=\-]{8,}"),
    # user:password@ in URLs such as postgresql://user:secret@host/db
    re.compile(r"(?<=://)([^:/@\s]+):[^@\s]+(?=@)"),
    # password=..., token: ..., api_key="...", and JSON such as "api_key": "..."
    re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key)([\"']?\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;&\"']+)"),
)

_HANDLER_NAME = "insightsql"
_original_factory = None


def redact(text: str) -> str:
    """Return ``text`` with secrets replaced by ``[REDACTED]``."""
    if not text:
        return text
    for name in SECRET_SETTINGS:
        value = (os.getenv(name) or "").strip()
        if len(value) >= MIN_SECRET_LENGTH:
            text = text.replace(value, REDACTED)
    for pattern in _PATTERNS:
        text = pattern.sub(_replacement, text)
    return text


def _replacement(match: re.Match) -> str:
    if match.re.pattern.startswith("(?<=://)"):
        return f"{match.group(1)}:{REDACTED}"
    if match.lastindex and match.lastindex >= 3:
        return f"{match.group(1)}{match.group(2)}{REDACTED}"
    return REDACTED


def _redacting_factory(*args, **kwargs) -> logging.LogRecord:
    record = _original_factory(*args, **kwargs)
    try:
        message = record.getMessage()
    except Exception:  # a bad format string must not lose the record
        message = f"{record.msg} {record.args}"
    record.msg, record.args = redact(message), None
    if record.exc_info and not record.exc_text:
        record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
    if record.stack_info:
        record.stack_info = redact(record.stack_info)
    return record


def install_redaction() -> None:
    """Redact secrets from every log record created from now on (idempotent)."""
    global _original_factory
    if _original_factory is None:
        _original_factory = logging.getLogRecordFactory()
        logging.setLogRecordFactory(_redacting_factory)


def uninstall_redaction() -> None:
    """Restore the previous record factory (used by tests)."""
    global _original_factory
    if _original_factory is not None:
        logging.setLogRecordFactory(_original_factory)
        _original_factory = None


def configure_logging() -> logging.Logger:
    """Set up the ``src`` logger: redaction, level from INSIGHTSQL_LOG_LEVEL, one stderr
    handler. Safe to call on every Streamlit rerun."""
    install_redaction()
    logger = logging.getLogger("src")
    logger.setLevel(config.get_log_level())
    if not any(h.get_name() == _HANDLER_NAME for h in logger.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.set_name(_HANDLER_NAME)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
    return logger
