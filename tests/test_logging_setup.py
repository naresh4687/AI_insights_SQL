"""Logging setup: secrets never reach log output."""

import logging

import pytest

from src import config
from src.core import logging_setup
from src.core.logging_setup import REDACTED, configure_logging, redact

FAKE_KEY = "AIzaSyFAKE_key_for_tests_0123456789abcd"
FAKE_GITHUB = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
FAKE_HF = "hf_" + "abcdefghijklmnopqrstuvwxyz0123"


@pytest.mark.parametrize("text, secret", [
    (f"calling with key {FAKE_KEY}", FAKE_KEY),
    (f"token {FAKE_GITHUB} rejected", FAKE_GITHUB),
    (f"hf token {FAKE_HF}", FAKE_HF),
    ("Authorization: Bearer abc.DEF-123_xyz", "abc.DEF-123_xyz"),
    ("postgresql://report_user:S3cr3t!pass@db.example.com:5432/sales", "S3cr3t!pass"),
    ("mysql://u:p4ssw0rd@host/db", "p4ssw0rd"),
    ("connect failed: password=hunter2xyz host=db", "hunter2xyz"),
    ('config {"api_key": "k-123456789"}', "k-123456789"),
    ("api-key: zz_998877665544", "zz_998877665544"),
    ("token='quoted secret value'", "quoted secret value"),
])
def test_known_secret_formats_are_redacted(text, secret):
    out = redact(text)
    assert secret not in out
    assert REDACTED in out


def test_configured_secret_values_are_redacted(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "plainvalue-without-known-prefix")
    monkeypatch.setenv("INSIGHTSQL_SECRET_KEY", "fernet-key-material-123")
    out = redact("key=plainvalue-without-known-prefix; other fernet-key-material-123")
    assert "plainvalue-without-known-prefix" not in out and "fernet-key-material-123" not in out


def test_short_configured_values_do_not_redact_ordinary_words(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "a")
    assert redact("a sales table") == "a sales table"


@pytest.mark.parametrize("text", [
    "SELECT region, SUM(quantity) FROM sales GROUP BY region",
    "max_output_tokens=2048 temperature=0",
    "Query failed: no such column: revenue",
    "https://generativelanguage.googleapis.com/v1beta/models/x",
])
def test_ordinary_messages_are_unchanged(text):
    assert redact(text) == text


def test_redaction_applies_to_every_logger_and_handler(caplog, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "plain-secret-value-42")
    configure_logging()
    caplog.set_level(logging.DEBUG)
    logging.getLogger("src.anything").warning("using %s and %s", "plain-secret-value-42", FAKE_KEY)
    logging.getLogger("streamlit.other").error("url postgresql://u:pw123456@h/db")
    assert "plain-secret-value-42" not in caplog.text
    assert FAKE_KEY not in caplog.text and "pw123456" not in caplog.text
    assert caplog.text.count(REDACTED) == 3


def test_redaction_applies_to_tracebacks(caplog):
    configure_logging()
    try:
        raise RuntimeError(f"bad key {FAKE_KEY}")
    except RuntimeError:
        logging.getLogger("src.x").exception("failed")
    assert FAKE_KEY not in caplog.text
    assert "RuntimeError" in caplog.text


def test_bad_format_arguments_do_not_lose_the_record(caplog):
    configure_logging()
    logging.getLogger("src.x").warning("two %s %s", "only-one")
    assert "two" in caplog.text


def test_configure_logging_is_idempotent_and_sets_level(monkeypatch):
    monkeypatch.setenv("INSIGHTSQL_LOG_LEVEL", "info")
    logger = configure_logging()
    configure_logging()
    assert logger.level == logging.INFO
    assert sum(h.get_name() == "insightsql" for h in logger.handlers) == 1


@pytest.mark.parametrize("value, expected", [(None, "WARNING"), ("debug", "DEBUG"), ("nonsense", "WARNING"),
                                             ("", "WARNING")])
def test_log_level_setting(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("INSIGHTSQL_LOG_LEVEL", raising=False)
    else:
        monkeypatch.setenv("INSIGHTSQL_LOG_LEVEL", value)
    assert config.get_log_level() == expected


def test_uninstall_restores_the_original_factory():
    original = logging.getLogRecordFactory()
    logging_setup.install_redaction()
    assert logging.getLogRecordFactory() is not original
    logging_setup.uninstall_redaction()
    assert logging.getLogRecordFactory() is original
