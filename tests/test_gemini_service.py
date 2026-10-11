"""Unit tests for the Gemini SQL-generation service.

The official google-genai SDK runs unchanged against a local fake Gemini server
(``FakeGemini`` in conftest.py). No API key, real model, or internet access is needed.
"""

import json
import logging

import pytest

from src import ai_providers, config, gemini_service, hf_service
from src.gemini_service import GeminiError, generate_sql
from tests.conftest import GEMINI_TEST_KEY, GEMINI_TEST_MODEL

QUESTION = "Which product generated the highest revenue?"
GOOD_SQL = (
    "SELECT p.product_name, ROUND(SUM(s.quantity * s.unit_price), 2) AS revenue "
    "FROM sales s JOIN products p ON p.product_id = s.product_id "
    "GROUP BY p.product_id ORDER BY revenue DESC LIMIT 1"
)


# --- Successful generation and request format ----------------------------------

def test_returns_sql_from_json_reply(fake_gemini):
    fake_gemini.reply_sql(GOOD_SQL)
    assert generate_sql(QUESTION) == GOOD_SQL


def test_request_goes_to_generate_content_for_the_configured_model(fake_gemini):
    generate_sql(QUESTION)
    assert [(m, p) for m, p, _ in fake_gemini.requests] == [
        ("POST", f"/v1beta/models/{GEMINI_TEST_MODEL}:generateContent")
    ]


def test_request_asks_for_json_sql_deterministically(fake_gemini):
    generate_sql(QUESTION)
    body = fake_gemini.generate_requests[0]
    generation = body["generationConfig"]
    assert generation["temperature"] == 0
    assert generation["maxOutputTokens"] == gemini_service.MAX_OUTPUT_TOKENS
    assert generation["responseMimeType"] == "application/json"
    assert generation["responseJsonSchema"]["required"] == ["sql"]
    assert body["contents"][0]["parts"][0]["text"] == QUESTION
    system = body["systemInstruction"]["parts"][0]["text"]
    assert "products (" in system and "sales (" in system and "unit_price" in system
    assert "query_history" not in system
    assert "exactly one read-only SELECT" in system


def test_api_key_is_sent_in_a_header_not_the_url(fake_gemini):
    generate_sql(QUESTION)
    assert fake_gemini.api_key_headers == [GEMINI_TEST_KEY]
    assert all(GEMINI_TEST_KEY not in path for _, path, _ in fake_gemini.requests)


def test_request_contains_no_sales_data(fake_gemini):
    """Only the question and the schema are sent — never rows from the database."""
    generate_sql(QUESTION)
    sent = json.dumps(fake_gemini.generate_requests[0])
    for value in ("Laptop Pro 14", "Standing Desk", "Electronics", "East", "2025-"):
        assert value not in sent


def test_only_one_request_is_made_with_no_automatic_retries(fake_gemini):
    fake_gemini.fail(503, "UNAVAILABLE", "The model is overloaded.")
    with pytest.raises(GeminiError):
        generate_sql(QUESTION)
    assert len(fake_gemini.requests) == 1


def test_model_is_configurable(fake_gemini, monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.8-flash")
    generate_sql(QUESTION)
    assert fake_gemini.requests[0][1] == "/v1beta/models/gemini-3.8-flash:generateContent"


def test_defaults_when_environment_is_unset():
    assert config.get_ai_provider() == "gemini"
    assert config.get_gemini_model() == "gemini-3.5-flash-lite"
    assert config.get_gemini_base_url() == "https://generativelanguage.googleapis.com"
    assert config.get_gemini_timeout() == 30.0
    assert config.get_gemini_api_key() is None


@pytest.mark.parametrize("value", ["abc", "-5", "0"])
def test_invalid_timeout_falls_back_to_default(monkeypatch, value):
    monkeypatch.setenv("GEMINI_TIMEOUT_SECONDS", value)
    assert config.get_gemini_timeout() == 30.0


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "ftp://example.com", "generativelanguage.googleapis.com", "https://",
     "http://generativelanguage.googleapis.com", "http://evil.example.com"],
)
def test_insecure_or_invalid_base_url_is_refused_before_sending_the_key(fake_gemini, monkeypatch, url):
    monkeypatch.setenv("GEMINI_BASE_URL", url)
    with pytest.raises(GeminiError, match="https"):
        generate_sql(QUESTION)
    assert fake_gemini.requests == []


def test_google_api_key_variable_is_never_used_implicitly(fake_gemini, monkeypatch):
    """The SDK can read GOOGLE_API_KEY on its own; the service must only use GEMINI_API_KEY."""
    monkeypatch.delenv("GEMINI_API_KEY")
    monkeypatch.setenv("GOOGLE_API_KEY", "AIzaOTHER_KEY")
    with pytest.raises(GeminiError, match="GEMINI_API_KEY"):
        generate_sql(QUESTION)
    assert fake_gemini.requests == []


def test_gemini_api_key_is_used_even_when_google_api_key_is_set(fake_gemini, monkeypatch):
    """The SDK prefers GOOGLE_API_KEY when it picks a key itself; the service passes
    GEMINI_API_KEY explicitly, so that is the key sent."""
    monkeypatch.setenv("GOOGLE_API_KEY", "AIzaOTHER_KEY")
    generate_sql(QUESTION)
    assert fake_gemini.api_key_headers == [GEMINI_TEST_KEY]


# --- Missing key ---------------------------------------------------------------

@pytest.mark.parametrize("key", [None, "", "   "])
def test_missing_key_gives_setup_instructions_without_calling_the_api(fake_gemini, monkeypatch, key):
    if key is None:
        monkeypatch.delenv("GEMINI_API_KEY")
    else:
        monkeypatch.setenv("GEMINI_API_KEY", key)
    with pytest.raises(GeminiError) as exc_info:
        generate_sql(QUESTION)
    assert "aistudio.google.com/apikey" in exc_info.value.message
    assert "GEMINI_API_KEY" in exc_info.value.message
    assert fake_gemini.requests == []


# --- Invalid input and empty / malformed replies -------------------------------

@pytest.mark.parametrize("question", ["", "   ", None])
def test_empty_question_is_rejected_without_calling_the_api(fake_gemini, question):
    with pytest.raises(GeminiError, match="Please enter a question"):
        generate_sql(question)
    assert fake_gemini.requests == []


@pytest.mark.parametrize("text", ["", "   ", '{"sql": ""}', '{"sql": null}', '{"answer": "SELECT 1"}'])
def test_empty_model_output_is_an_error(fake_gemini, text):
    fake_gemini.reply_text(text)
    with pytest.raises(GeminiError, match="empty response|did not produce"):
        generate_sql(QUESTION)


@pytest.mark.parametrize("body", [{"candidates": []}, {}, {"candidates": [{"content": {"parts": []}}]}])
def test_reply_without_text_is_an_error(fake_gemini, body):
    fake_gemini.body = body
    with pytest.raises(GeminiError, match="empty response"):
        generate_sql(QUESTION)


def test_reply_cut_off_by_the_token_limit_is_explained(fake_gemini):
    fake_gemini.body = {"candidates": [{"content": {"parts": []}, "finishReason": "MAX_TOKENS"}]}
    with pytest.raises(GeminiError, match="ran out of space"):
        generate_sql(QUESTION)


def test_blocked_question_is_explained(fake_gemini):
    fake_gemini.body = {"promptFeedback": {"blockReason": "SAFETY"}}
    with pytest.raises(GeminiError, match="declined to answer"):
        generate_sql(QUESTION)


def test_malformed_json_body_is_an_error(fake_gemini):
    fake_gemini.raw_body = b"<html>not json</html>"
    with pytest.raises(GeminiError, match="could not be read"):
        generate_sql(QUESTION)


def test_oversized_reply_is_refused(fake_gemini):
    fake_gemini.reply_text("SELECT 1 -- " + "x" * gemini_service.MAX_REPLY_CHARS)
    with pytest.raises(GeminiError, match="too large"):
        generate_sql(QUESTION)


# --- Connection, timeout, and API errors ----------------------------------------

def test_connection_failure_gives_a_clear_message(gemini_down):
    with pytest.raises(GeminiError) as exc_info:
        generate_sql(QUESTION)
    assert "Could not connect to Gemini" in exc_info.value.message
    assert "Demo Mode" in exc_info.value.message


def test_timeout_is_reported(fake_gemini, monkeypatch):
    fake_gemini.delay = 1.0
    monkeypatch.setenv("GEMINI_TIMEOUT_SECONDS", "0.2")
    with pytest.raises(GeminiError, match="did not answer within 0.2 seconds"):
        generate_sql(QUESTION)


@pytest.mark.parametrize(
    "code, status, message, expected",
    [
        (400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid API key.", "rejected the API key"),
        (401, "UNAUTHENTICATED", "Request had invalid authentication credentials.", "rejected the API key"),
        (403, "PERMISSION_DENIED", "Permission denied on resource project.", "not allowed to use the Gemini API"),
        (429, "RESOURCE_EXHAUSTED", "Resource has been exhausted (e.g. check quota).", "quota or rate limit"),
        (404, "NOT_FOUND", "models/x is not found for API version v1beta", "was not found. Set GEMINI_MODEL"),
        (500, "INTERNAL", "An internal error has occurred.", r"temporarily unavailable \(HTTP 500\)"),
        (503, "UNAVAILABLE", "The model is overloaded.", r"temporarily unavailable \(HTTP 503\)"),
        (400, "INVALID_ARGUMENT", "Invalid JSON payload received.", r"could not process this request \(HTTP 400\)"),
    ],
)
def test_api_errors_give_specific_messages(fake_gemini, code, status, message, expected):
    fake_gemini.fail(code, status, message)
    with pytest.raises(GeminiError, match=expected):
        generate_sql(QUESTION)


def test_internal_error_details_are_not_shown(fake_gemini):
    fake_gemini.fail(500, "INTERNAL", "worker crashed at /srv/internal/model.py line 42")
    with pytest.raises(GeminiError) as exc_info:
        generate_sql(QUESTION)
    assert "/srv/internal" not in exc_info.value.message


@pytest.mark.parametrize("code, status", [(400, "INVALID_ARGUMENT"), (403, "PERMISSION_DENIED"), (500, "INTERNAL")])
def test_key_never_appears_in_messages_or_logs(fake_gemini, caplog, code, status):
    fake_gemini.fail(code, status, f"API key not valid: {GEMINI_TEST_KEY}")  # even if echoed
    caplog.set_level(logging.DEBUG)
    with pytest.raises(GeminiError) as exc_info:
        generate_sql(QUESTION)
    ok, status_message = gemini_service.check_status()
    assert GEMINI_TEST_KEY not in exc_info.value.message
    assert GEMINI_TEST_KEY not in status_message
    assert GEMINI_TEST_KEY not in caplog.text


def test_key_is_not_logged_on_connection_failure(gemini_down, caplog):
    caplog.set_level(logging.DEBUG)
    with pytest.raises(GeminiError):
        generate_sql(QUESTION)
    assert GEMINI_TEST_KEY not in caplog.text


# --- Reply parsing (shared extraction rules) ------------------------------------

@pytest.mark.parametrize(
    "text, expected",
    [
        ('{"sql": "SELECT 1"}', "SELECT 1"),
        ('```json\n{"sql": "SELECT 1"}\n```', "SELECT 1"),
        ("```sql\nSELECT region FROM sales\n```", "SELECT region FROM sales"),
        ("Here is the query:\nSELECT region FROM sales", "SELECT region FROM sales"),
    ],
)
def test_reply_formats_are_extracted(fake_gemini, text, expected):
    fake_gemini.reply_text(text)
    assert generate_sql(QUESTION) == expected


def test_extra_statements_are_left_for_the_guard(fake_gemini):
    fake_gemini.reply_sql("SELECT 1; DROP TABLE sales")
    assert generate_sql(QUESTION) == "SELECT 1; DROP TABLE sales"


def test_multiple_fenced_queries_are_refused(fake_gemini):
    fake_gemini.reply_text("```sql\nSELECT 1\n```\nor\n```sql\nDELETE FROM sales\n```")
    with pytest.raises(GeminiError, match="more than one query"):
        generate_sql(QUESTION)


# --- Status check -------------------------------------------------------------

def test_status_ok_when_key_accepted_and_model_exists(fake_gemini):
    ok, message = gemini_service.check_status()
    assert ok and GEMINI_TEST_MODEL in message
    assert [(m, p) for m, p, _ in fake_gemini.requests] == [("GET", f"/v1beta/models/{GEMINI_TEST_MODEL}")]
    assert fake_gemini.generate_requests == []  # no content generated


def test_status_reports_unknown_model(fake_gemini, monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-0-retired")
    ok, message = gemini_service.check_status()
    assert not ok and "GEMINI_MODEL" in message


def test_status_reports_invalid_key(fake_gemini):
    fake_gemini.fail(400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid API key.")
    ok, message = gemini_service.check_status()
    assert not ok and "rejected the API key" in message


def test_status_reports_missing_key_without_calling_the_api(no_gemini_key):
    ok, message = gemini_service.check_status()
    assert not ok and "GEMINI_API_KEY" in message
    assert no_gemini_key.requests == []


def test_status_reports_unreachable_api(gemini_down):
    ok, message = gemini_service.check_status()
    assert not ok and "Could not connect to Gemini" in message


# --- Provider selection -------------------------------------------------------

def test_gemini_is_the_default_provider():
    assert ai_providers.current() is gemini_service
    assert ai_providers.display_name() == "Gemini"


def test_hugging_face_can_still_be_selected(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "HuggingFace")
    assert ai_providers.current() is hf_service


def test_unknown_provider_is_reported_not_crashing(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openai")
    ok, message = ai_providers.check_status()
    assert not ok and "AI_PROVIDER must be one of" in message
    with pytest.raises(Exception, match="AI_PROVIDER must be one of"):
        ai_providers.generate_sql(QUESTION)
    assert ai_providers.display_name() == "Gemini"
