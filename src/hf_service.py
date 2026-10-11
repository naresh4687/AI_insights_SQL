"""Optional AI Mode: ask a Hugging Face hosted model to translate a question into SQL.

Uses Hugging Face Inference Providers (an OpenAI-compatible chat API). Only the question
and the table structure are sent — never rows from the database.

This module only *proposes* SQL. It never opens the database and never decides whether
SQL is safe — every candidate goes through ``query_service.answer_question()`` →
``run_query()``, the same validation and read-only execution path as Demo Mode.
Prompt rules help the model behave, but they are not a security boundary.

The access token (HF_TOKEN) is sent only to HF_BASE_URL and is never logged or shown.
Uses the standard library HTTP client. The prompt and reply parsing are shared with the
other providers (``src/ai_prompt.py``).
"""

import json
import logging
import urllib.error
import urllib.request

from src import ai_prompt, config
from src.ai_prompt import build_system_prompt, schema_description  # noqa: F401 (part of this module's API)
from src.query_service import SqlGenerationError

logger = logging.getLogger(__name__)

DISPLAY_NAME = "Hugging Face"
MAX_RESPONSE_BYTES = 1_000_000
MAX_OUTPUT_TOKENS = 512
STATUS_TIMEOUT_SECONDS = 5.0
TOKEN_HELP = (
    "AI Mode needs a Hugging Face access token. Create one at "
    "https://huggingface.co/settings/tokens with the permission "
    "'Make calls to Inference Providers', then set HF_TOKEN in your .env file. "
    "Demo Mode works without it."
)


class HuggingFaceError(SqlGenerationError):
    """The model could not provide SQL. ``message`` is safe to show to users."""


def model_name() -> str:
    return config.get_hf_model()


def build_request(question: str, model: str) -> dict:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": build_system_prompt()},
            {"role": "user", "content": question},
        ],
        "stream": False,
        "temperature": 0,
        "max_tokens": MAX_OUTPUT_TOKENS,
    }


def extract_sql(content: str) -> str:
    """See ``ai_prompt.extract_sql``; raises HuggingFaceError for several queries."""
    return ai_prompt.extract_sql(content, HuggingFaceError)


def generate_sql(question: str) -> str:
    """Ask the configured model for SQL answering ``question``. Never executes it."""
    if not isinstance(question, str) or not question.strip():
        raise HuggingFaceError("Please enter a question.")

    base_url, model, token = _settings()
    body = _request_json(
        f"{base_url}/chat/completions", build_request(question.strip(), model), token,
        config.get_hf_timeout(), model,
    )
    content = _reply_content(body)
    if not content:
        raise HuggingFaceError("The AI model returned an empty response. Try rephrasing the question.")

    sql = extract_sql(content)
    if not sql:
        raise HuggingFaceError(
            "The AI model did not produce a read-only query for this question. Try rephrasing it."
        )
    return sql


def check_status() -> tuple[bool, str]:
    """Quick check that a token is set and the model is offered by Inference Providers.

    The token itself is only checked when the first question is sent.
    """
    try:
        base_url, model, token = _settings()
        listing = _request_json(f"{base_url}/models", None, token, STATUS_TIMEOUT_SECONDS, model)
    except HuggingFaceError as exc:
        return False, exc.message
    models = listing.get("data", []) if isinstance(listing, dict) else []
    if any(isinstance(m, dict) and m.get("id") == model for m in models):
        return True, f"Hugging Face model {model} is available."
    return False, _model_unavailable_message(model)


def _settings() -> tuple[str, str, str]:
    token = config.get_hf_token()
    if token is None:
        raise HuggingFaceError(TOKEN_HELP)
    try:
        return config.get_hf_base_url(), config.get_hf_model(), token
    except ValueError as exc:
        raise HuggingFaceError(str(exc)) from None


def _reply_content(body) -> str:
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return ""
    return content.strip() if isinstance(content, str) else ""


def _model_unavailable_message(model: str) -> str:
    return (
        f"The model '{model}' is not available from Hugging Face Inference Providers. "
        "Set HF_MODEL to another chat model (for example meta-llama/Llama-3.3-70B-Instruct)."
    )


def _request_json(url: str, payload: dict | None, token: str, timeout: float, model: str):
    """POST ``payload`` (or GET when None) with the token and return the decoded JSON body."""
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise _http_error(exc, model, token) from None
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise _timeout_error(timeout) from None
        logger.warning("Could not connect to %s: %s", url, exc.reason)
        raise HuggingFaceError(
            "Could not connect to Hugging Face. Check your internet connection and try again, "
            "or switch to Demo Mode."
        ) from None
    except TimeoutError:
        raise _timeout_error(timeout) from None
    except OSError as exc:
        logger.warning("Hugging Face connection error: %s", exc)
        raise HuggingFaceError("The connection to Hugging Face failed. Please try again.") from None

    if len(raw) > MAX_RESPONSE_BYTES:
        raise HuggingFaceError("The AI response was too large to process.")
    try:
        return json.loads(raw)
    except ValueError:
        logger.warning("Hugging Face returned invalid JSON: %r", raw[:200])
        raise HuggingFaceError("Hugging Face returned a response that could not be read.") from None


def _timeout_error(timeout: float) -> HuggingFaceError:
    return HuggingFaceError(
        f"The AI model did not answer within {timeout:g} seconds. Try again, choose a faster "
        "model, or increase HF_TIMEOUT_SECONDS."
    )


def _http_error(exc: urllib.error.HTTPError, model: str, token: str) -> HuggingFaceError:
    try:
        detail = str(json.loads(exc.read(10_000)).get("error", ""))
    except (ValueError, AttributeError, OSError):
        detail = ""
    detail = detail.replace(token, "[token]")  # in case the server echoes it
    logger.warning("Hugging Face HTTP %s: %s", exc.code, detail[:300])
    code, lowered = exc.code, detail.lower()
    if code == 401:
        return HuggingFaceError(
            "Hugging Face rejected the access token (invalid or expired). Create a new token at "
            "https://huggingface.co/settings/tokens and update HF_TOKEN."
        )
    if code == 403:
        return HuggingFaceError(
            "The access token is not allowed to call Inference Providers. Edit the token at "
            "https://huggingface.co/settings/tokens and enable 'Make calls to Inference Providers'."
        )
    if code == 402:
        return HuggingFaceError(
            "Your Hugging Face account has no Inference Providers credits left. Add pre-paid "
            "credits or a PRO subscription at https://huggingface.co/settings/billing, "
            "or use Demo Mode."
        )
    if code == 429:
        return HuggingFaceError("Too many requests to Hugging Face. Wait a minute and try again.")
    if code == 404 or (code == 400 and "model" in lowered and ("not" in lowered or "support" in lowered)):
        return HuggingFaceError(_model_unavailable_message(model))
    if code >= 500:
        return HuggingFaceError(
            f"The Hugging Face model is temporarily unavailable (HTTP {code}). Try again shortly."
        )
    return HuggingFaceError(f"Hugging Face returned an error (HTTP {code}). Please try again.")
