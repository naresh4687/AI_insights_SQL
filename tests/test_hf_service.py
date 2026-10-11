"""Unit tests for the Hugging Face SQL-generation service, against a local fake API server.

No token, real model, or internet access is needed.
"""

import json
import logging

import pytest

from src import config, database, hf_service
from src.hf_service import HuggingFaceError, extract_sql, generate_sql
from tests.conftest import TEST_MODEL, TEST_TOKEN

QUESTION = "Which product generated the highest revenue?"
GOOD_SQL = (
    "SELECT p.product_name, ROUND(SUM(s.quantity * s.unit_price), 2) AS revenue "
    "FROM sales s JOIN products p ON p.product_id = s.product_id "
    "GROUP BY p.product_id ORDER BY revenue DESC LIMIT 1"
)


# --- Successful generation and request format ----------------------------------

def test_returns_sql_from_json_reply(fake_hf):
    fake_hf.reply_sql(GOOD_SQL)
    assert generate_sql(QUESTION) == GOOD_SQL


def test_request_uses_chat_completions_with_model_and_temperature_zero(fake_hf):
    generate_sql(QUESTION)

    assert [path for path, _ in fake_hf.requests] == ["/v1/chat/completions"]
    request = fake_hf.chat_requests[0]
    assert request["model"] == TEST_MODEL
    assert request["stream"] is False
    assert request["temperature"] == 0
    assert request["max_tokens"] == hf_service.MAX_OUTPUT_TOKENS
    assert [m["role"] for m in request["messages"]] == ["system", "user"]
    assert request["messages"][1]["content"] == QUESTION


def test_token_is_sent_as_bearer_header(fake_hf):
    generate_sql(QUESTION)
    assert fake_hf.auth_headers == [f"Bearer {TEST_TOKEN}"]


def test_request_contains_no_sales_data(fake_hf):
    """Only the question and the schema are sent — never rows from the database."""
    generate_sql(QUESTION)
    sent = json.dumps(fake_hf.chat_requests[0])
    for value in ("Laptop Pro 14", "Standing Desk", "Electronics", "East", "2025-"):
        assert value not in sent


def test_model_is_configurable(fake_hf, monkeypatch):
    monkeypatch.setenv("HF_MODEL", "meta-llama/Llama-3.3-70B-Instruct")
    generate_sql(QUESTION)
    assert fake_hf.chat_requests[0]["model"] == "meta-llama/Llama-3.3-70B-Instruct"


def test_defaults_when_environment_is_unset(monkeypatch):
    for name in ("HF_BASE_URL", "HF_MODEL", "HF_TIMEOUT_SECONDS", "HF_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    assert config.get_hf_base_url() == "https://router.huggingface.co/v1"
    assert config.get_hf_model() == "Qwen/Qwen2.5-Coder-32B-Instruct"
    assert config.get_hf_timeout() == 30.0
    assert config.get_hf_token() is None


@pytest.mark.parametrize("value", ["abc", "-5", "0"])
def test_invalid_timeout_falls_back_to_default(monkeypatch, value):
    monkeypatch.setenv("HF_TIMEOUT_SECONDS", value)
    assert config.get_hf_timeout() == 30.0


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "ftp://example.com", "router.huggingface.co/v1", "https://",
     "http://router.huggingface.co/v1", "http://evil.example.com/v1"],
)
def test_insecure_or_invalid_base_url_is_refused_before_sending_the_token(fake_hf, monkeypatch, url):
    monkeypatch.setenv("HF_BASE_URL", url)
    with pytest.raises(HuggingFaceError, match="https"):
        generate_sql(QUESTION)
    assert fake_hf.requests == []


@pytest.mark.parametrize("url", ["http://localhost:8000/v1", "http://127.0.0.1:8000/v1"])
def test_plain_http_is_allowed_only_for_this_machine(monkeypatch, url):
    monkeypatch.setenv("HF_BASE_URL", url)
    assert config.get_hf_base_url() == url


# --- Missing token ------------------------------------------------------------

@pytest.mark.parametrize("token", [None, "", "   "])
def test_missing_token_gives_setup_instructions_without_calling_the_api(fake_hf, monkeypatch, token):
    if token is None:
        monkeypatch.delenv("HF_TOKEN", raising=False)
    else:
        monkeypatch.setenv("HF_TOKEN", token)
    with pytest.raises(HuggingFaceError) as exc_info:
        generate_sql(QUESTION)
    assert "huggingface.co/settings/tokens" in exc_info.value.message
    assert "HF_TOKEN" in exc_info.value.message
    assert fake_hf.requests == []


# --- Prompt -------------------------------------------------------------------

def test_prompt_contains_the_real_schema_for_allowed_tables_only(seeded_db):
    prompt = hf_service.build_system_prompt()
    conn = database.connect(seeded_db)
    for table in ("products", "sales"):
        for column in (row[1] for row in conn.execute(f"PRAGMA table_info({table})")):
            assert column in prompt
    conn.close()
    assert "query_history" not in prompt
    assert "sqlite_master" not in prompt


def test_prompt_states_revenue_rule_and_read_only_rules():
    prompt = hf_service.build_system_prompt()
    assert "SUM(sales.quantity * sales.unit_price)" in prompt
    assert "exactly one read-only SELECT" in prompt
    for keyword in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "PRAGMA", "ATTACH"):
        assert keyword in prompt
    assert "load_extension" not in prompt and "zeroblob" not in prompt


# --- Invalid input and empty / malformed replies -------------------------------

@pytest.mark.parametrize("question", ["", "   ", None])
def test_empty_question_is_rejected_without_calling_the_api(fake_hf, question):
    with pytest.raises(HuggingFaceError, match="Please enter a question"):
        generate_sql(question)
    assert fake_hf.requests == []


@pytest.mark.parametrize("content", ["", "   ", '{"sql": ""}', '{"sql": null}', '{"answer": "SELECT 1"}'])
def test_empty_model_output_is_an_error(fake_hf, content):
    fake_hf.reply_content(content)
    with pytest.raises(HuggingFaceError, match="empty response|did not produce"):
        generate_sql(QUESTION)


@pytest.mark.parametrize("body", [{"choices": []}, {"object": "chat.completion"}, {"choices": [{"message": None}]}, []])
def test_reply_without_choices_is_an_error(fake_hf, body):
    fake_hf.body = body
    with pytest.raises(HuggingFaceError, match="empty response"):
        generate_sql(QUESTION)


def test_malformed_json_body_is_an_error(fake_hf):
    fake_hf.raw_body = b"<html>not json</html>"
    with pytest.raises(HuggingFaceError, match="could not be read"):
        generate_sql(QUESTION)


def test_oversized_response_is_refused(fake_hf):
    fake_hf.raw_body = b"x" * (hf_service.MAX_RESPONSE_BYTES + 10)
    with pytest.raises(HuggingFaceError, match="too large"):
        generate_sql(QUESTION)


# --- Connection, timeout, and HTTP failures -------------------------------------

def test_connection_failure_gives_a_clear_message(hf_down):
    with pytest.raises(HuggingFaceError) as exc_info:
        generate_sql(QUESTION)
    assert "Could not connect to Hugging Face" in exc_info.value.message
    assert "Demo Mode" in exc_info.value.message


def test_timeout_is_reported(fake_hf, monkeypatch):
    fake_hf.delay = 1.0
    monkeypatch.setenv("HF_TIMEOUT_SECONDS", "0.2")
    with pytest.raises(HuggingFaceError, match="did not answer within 0.2 seconds"):
        generate_sql(QUESTION)


@pytest.mark.parametrize(
    "status, error, expected",
    [
        (401, "Invalid credentials in Authorization header", "rejected the access token"),
        (403, "This authentication method does not have sufficient permissions", "Make calls to Inference Providers"),
        (402, "You have no remaining credits. Purchase pre-paid credits", "no Inference Providers credits left"),
        (429, "Rate limit reached", "Too many requests"),
        (404, "Model not found", "not available from Hugging Face Inference Providers"),
        (400, "The requested model 'x' is not supported by any provider", "not available from Hugging Face"),
        (503, "Service unavailable", "temporarily unavailable (HTTP 503)"),
        (418, "teapot", "returned an error (HTTP 418)"),
    ],
)
def test_http_errors_give_specific_messages(fake_hf, status, error, expected):
    fake_hf.fail(status, error)
    with pytest.raises(HuggingFaceError, match=expected.replace("(", r"\(").replace(")", r"\)")):
        generate_sql(QUESTION)


def test_internal_error_details_are_not_shown(fake_hf):
    fake_hf.fail(500, "worker crashed at /opt/provider/internal.py line 42")
    with pytest.raises(HuggingFaceError) as exc_info:
        generate_sql(QUESTION)
    assert "/opt/provider" not in exc_info.value.message


@pytest.mark.parametrize("status", [401, 403, 500])
def test_token_never_appears_in_messages_or_logs(fake_hf, caplog, status):
    fake_hf.fail(status, f"bad token {TEST_TOKEN}")  # even if the server echoes it
    caplog.set_level(logging.DEBUG)
    with pytest.raises(HuggingFaceError) as exc_info:
        generate_sql(QUESTION)
    assert TEST_TOKEN not in exc_info.value.message
    assert TEST_TOKEN not in caplog.text
    ok, message = hf_service.check_status()
    assert TEST_TOKEN not in message


def test_token_is_not_logged_on_connection_failure(hf_down, caplog):
    caplog.set_level(logging.DEBUG)
    with pytest.raises(HuggingFaceError):
        generate_sql(QUESTION)
    assert TEST_TOKEN not in caplog.text


# --- SQL extraction -----------------------------------------------------------

@pytest.mark.parametrize(
    "content, expected",
    [
        ('{"sql": "SELECT 1"}', "SELECT 1"),
        ('```json\n{"sql": "SELECT 1"}\n```', "SELECT 1"),
        ("```sql\nSELECT 1\n```", "SELECT 1"),
        ("```\nSELECT 1\n```", "SELECT 1"),
        ("Sure! Here is the query:\n```sql\nSELECT region FROM sales\n```\nHope this helps.", "SELECT region FROM sales"),
        ("Here is the query:\nSELECT region FROM sales", "SELECT region FROM sales"),
        ('{"sql": "```sql\\nSELECT 1\\n```"}', "SELECT 1"),
        ("WITH t AS (SELECT 1 AS x) SELECT x FROM t", "WITH t AS (SELECT 1 AS x) SELECT x FROM t"),
        ('<think>I could SELECT * FROM sales…</think>\n{"sql": "SELECT 1"}', "SELECT 1"),
    ],
)
def test_extract_sql_handles_fences_json_prose_and_reasoning(content, expected):
    assert extract_sql(content) == expected


@pytest.mark.parametrize(
    "content",
    ["SELECT 1; DROP TABLE sales", "SELECT * FROM sales;\nThis query lists all sales."],
)
def test_extract_sql_never_trims_extra_statements_or_trailing_text(content):
    """Left intact so the SQL guard rejects it, rather than silently 'repairing' it."""
    assert extract_sql(content) == content


def test_multiple_fenced_queries_are_refused(fake_hf):
    fake_hf.reply_content("```sql\nSELECT 1\n```\nor\n```sql\nDELETE FROM sales\n```")
    with pytest.raises(HuggingFaceError, match="more than one query"):
        generate_sql(QUESTION)


def test_markdown_reply_is_extracted_end_to_end(fake_hf):
    fake_hf.reply_content(f"Here you go:\n```sql\n{GOOD_SQL}\n```")
    assert generate_sql(QUESTION) == GOOD_SQL


# --- Status check -------------------------------------------------------------

def test_status_ok_when_model_is_offered(fake_hf):
    ok, message = hf_service.check_status()
    assert ok and TEST_MODEL in message
    assert [path for path, _ in fake_hf.requests] == ["/v1/models"]


def test_status_reports_unavailable_model(fake_hf):
    fake_hf.models = ["meta-llama/Llama-3.3-70B-Instruct"]
    ok, message = hf_service.check_status()
    assert not ok and "HF_MODEL" in message


def test_status_reports_missing_token_without_calling_the_api(no_hf_token):
    ok, message = hf_service.check_status()
    assert not ok and "HF_TOKEN" in message
    assert no_hf_token.requests == []


def test_status_reports_unreachable_api(hf_down):
    ok, message = hf_service.check_status()
    assert not ok and "Could not connect to Hugging Face" in message
