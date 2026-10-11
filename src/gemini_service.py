"""AI Mode with Google Gemini: ask a Gemini model to translate a question into SQL.

Uses Google's official SDK (``google-genai``) and ``models.generate_content``, which is
stateless: nothing is stored on Google's side between requests. Only the question and the
table structure are sent — never rows from the database. The reply is constrained to the
JSON shape {"sql": "..."}.

This module only *proposes* SQL. It never opens the database and never decides whether
SQL is safe — every candidate goes through ``query_service.answer_question()`` →
``run_query()``, the same validation and read-only execution path as Demo Mode.
Prompt rules help the model behave, but they are not a security boundary.

The API key (GEMINI_API_KEY) is sent only to GEMINI_BASE_URL, in a request header, and
is never logged or shown.
"""

import logging

import httpx
from google import genai
from google.genai import errors, types

from src import ai_prompt, config
from src.query_service import SqlGenerationError

logger = logging.getLogger(__name__)

DISPLAY_NAME = "Gemini"
# Thinking tokens count toward this limit (Gemini 3 models think by default), so it is
# set well above the size of a SQL query.
MAX_OUTPUT_TOKENS = 2048
MAX_REPLY_CHARS = 20_000
STATUS_TIMEOUT_SECONDS = 5.0
KEY_HELP = (
    "AI Mode needs a Gemini API key. Create one at https://aistudio.google.com/apikey, "
    "then set GEMINI_API_KEY in your .env file. Demo Mode works without it."
)


class GeminiError(SqlGenerationError):
    """Gemini could not provide SQL. ``message`` is safe to show to users."""


def model_name() -> str:
    return config.get_gemini_model()


def build_config(dataset=None) -> types.GenerateContentConfig:
    """Request settings; the system prompt describes ``dataset`` (None = the demo data)."""
    return types.GenerateContentConfig(
        system_instruction=ai_prompt.build_system_prompt(dataset),
        temperature=0,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        response_mime_type="application/json",
        response_json_schema=ai_prompt.RESPONSE_SCHEMA,
    )


def extract_sql(content: str) -> str:
    """See ``ai_prompt.extract_sql``; raises GeminiError for several queries."""
    return ai_prompt.extract_sql(content, GeminiError)


def generate_sql(question: str, dataset=None) -> str:
    """Ask the configured Gemini model for SQL answering ``question`` about ``dataset``
    (None = the demo data). Never executes it."""
    if not isinstance(question, str) or not question.strip():
        raise GeminiError("Please enter a question.")

    api_key, model, base_url = _settings()
    timeout = config.get_gemini_timeout()
    with _client(api_key, base_url, timeout) as client:
        response = _call(
            lambda: client.models.generate_content(model=model, contents=question.strip(),
                                                   config=build_config(dataset)),
            api_key, model, timeout,
        )

    content = _reply_text(response)
    if len(content) > MAX_REPLY_CHARS:
        raise GeminiError("The AI response was too large to process.")
    sql = extract_sql(content)
    if not sql:
        raise GeminiError("The AI model did not produce a read-only query for this question. Try rephrasing it.")
    return sql


def check_status() -> tuple[bool, str]:
    """Quick check that a key is set and accepted and that the model exists.

    Looks up the model's details, which does not generate any content.
    """
    try:
        api_key, model, base_url = _settings()
        with _client(api_key, base_url, STATUS_TIMEOUT_SECONDS) as client:
            _call(lambda: client.models.get(model=model), api_key, model, STATUS_TIMEOUT_SECONDS)
    except GeminiError as exc:
        return False, exc.message
    return True, f"Gemini model {model} is available."


def _settings() -> tuple[str, str, str]:
    api_key = config.get_gemini_api_key()
    if api_key is None:
        raise GeminiError(KEY_HELP)
    try:
        return api_key, config.get_gemini_model(), config.get_gemini_base_url()
    except ValueError as exc:
        raise GeminiError(str(exc)) from None


def _client(api_key: str, base_url: str, timeout: float) -> genai.Client:
    """A client with an explicit key (never read implicitly from other variables),
    no automatic retries, and a timeout. Use it as a context manager so it stays open
    for the whole request."""
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            base_url=base_url,
            timeout=int(timeout * 1000),  # milliseconds
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )


def _call(request, api_key: str, model: str, timeout: float):
    """Run an SDK request, turning every failure into a GeminiError with a safe message."""
    try:
        return request()
    except errors.APIError as exc:
        raise _api_error(exc, api_key, model) from None
    except httpx.TimeoutException:
        raise GeminiError(
            f"The AI model did not answer within {timeout:g} seconds. Try again, or increase "
            "GEMINI_TIMEOUT_SECONDS."
        ) from None
    except httpx.TransportError as exc:
        logger.warning("Could not connect to Gemini: %s", type(exc).__name__)
        raise GeminiError(
            "Could not connect to Gemini. Check your internet connection and try again, "
            "or switch to Demo Mode."
        ) from None
    except ValueError as exc:  # malformed JSON or an unexpected response shape
        logger.warning("Unreadable Gemini response: %s", type(exc).__name__)
        raise GeminiError("Gemini returned a response that could not be read.") from None


def _reply_text(response) -> str:
    feedback = getattr(response, "prompt_feedback", None)
    if feedback is not None and getattr(feedback, "block_reason", None):
        raise GeminiError("Gemini declined to answer this question. Try rephrasing it.")
    candidates = getattr(response, "candidates", None) or []
    finish = getattr(candidates[0], "finish_reason", None) if candidates else None
    try:
        text = response.text
    except (ValueError, AttributeError):
        text = None
    if not isinstance(text, str) or not text.strip():
        if finish == types.FinishReason.MAX_TOKENS:
            raise GeminiError("The AI model ran out of space before writing a query. Try a simpler question.")
        raise GeminiError("The AI model returned an empty response. Try rephrasing the question.")
    return text.strip()


def _api_error(exc: errors.APIError, api_key: str, model: str) -> GeminiError:
    detail = str(exc.message or "").replace(api_key, "[key]")
    status = str(exc.status or "")
    logger.warning("Gemini API error %s %s: %s", exc.code, status, detail[:300])
    code, lowered = exc.code, detail.lower()

    if "api key" in lowered or "api_key" in lowered or code == 401:
        return GeminiError(
            "Gemini rejected the API key (invalid or expired). Create a new key at "
            "https://aistudio.google.com/apikey and update GEMINI_API_KEY."
        )
    if code == 403 or status == "PERMISSION_DENIED":
        return GeminiError(
            "This API key is not allowed to use the Gemini API. Check the key's project and "
            "restrictions at https://aistudio.google.com/apikey."
        )
    if code == 429 or status == "RESOURCE_EXHAUSTED":
        return GeminiError(
            "The Gemini quota or rate limit has been reached. Wait a minute and try again, "
            "check your limits at https://aistudio.google.com, or use Demo Mode."
        )
    if code == 404 or status == "NOT_FOUND":
        return GeminiError(
            f"The Gemini model '{model}' was not found. Set GEMINI_MODEL to a current model "
            "(see https://ai.google.dev/gemini-api/docs/models)."
        )
    if code is not None and code >= 500:
        return GeminiError(f"Gemini is temporarily unavailable (HTTP {code}). Try again shortly.")
    if code == 400:
        return GeminiError("Gemini could not process this request (HTTP 400). Try rephrasing the question.")
    return GeminiError(f"Gemini returned an error (HTTP {code}). Please try again.")
