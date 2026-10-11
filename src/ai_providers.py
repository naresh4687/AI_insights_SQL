"""The AI service used by AI Mode, chosen with AI_PROVIDER ('gemini' by default).

Each provider module offers the same functions: ``generate_sql(question)``,
``check_status()``, ``model_name()`` and ``DISPLAY_NAME``. Providers only propose SQL;
``query_service.answer_question()`` validates and runs it.
"""

from types import ModuleType

from src import config, gemini_service, hf_service
from src.query_service import SqlGenerationError

PROVIDERS: dict[str, ModuleType] = {"gemini": gemini_service, "huggingface": hf_service}


def current() -> ModuleType:
    """The configured provider module. Raises SqlGenerationError if AI_PROVIDER is invalid."""
    try:
        return PROVIDERS[config.get_ai_provider()]
    except ValueError as exc:
        raise SqlGenerationError(str(exc)) from None


def display_name() -> str:
    """Provider name for the UI; falls back to the default if AI_PROVIDER is invalid."""
    try:
        return current().DISPLAY_NAME
    except SqlGenerationError:
        return PROVIDERS[config.DEFAULT_AI_PROVIDER].DISPLAY_NAME


def generate_sql(question: str, dataset=None) -> str:
    """Ask the configured provider (resolved on every call) for SQL about ``dataset``
    (None = the demo data)."""
    provider = current()
    return provider.generate_sql(question) if dataset is None else provider.generate_sql(question, dataset)


def check_status() -> tuple[bool, str]:
    try:
        provider = current()
    except SqlGenerationError as exc:
        return False, exc.message
    return provider.check_status()
