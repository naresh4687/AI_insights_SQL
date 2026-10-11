"""Shared pytest fixtures."""

import json
import logging
import socket
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src import database
from src.core import logging_setup


# Real credentials or settings from the developer's .env must never reach a test.
_REAL_AI_SETTINGS = (
    "AI_PROVIDER", "GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_MODEL", "GEMINI_BASE_URL",
    "GEMINI_TIMEOUT_SECONDS", "HF_TOKEN", "HF_MODEL", "HF_BASE_URL", "HF_TIMEOUT_SECONDS",
    # Connection secrets and network permissions are also set explicitly by each test.
    "INSIGHTSQL_SECRET_KEY", "INSIGHTSQL_ALLOWED_PRIVATE_HOSTS", "INSIGHTSQL_CONNECTOR_TIMEOUT_SECONDS",
    # Sign-in is off unless a test turns it on.
    "INSIGHTSQL_AUTH", "INSIGHTSQL_ADMIN_EMAILS", "INSIGHTSQL_ALLOWED_SIGNINS", "INSIGHTSQL_DEFAULT_ROLE",
)


@pytest.fixture(autouse=True)
def _no_real_ai_credentials(monkeypatch):
    for name in _REAL_AI_SETTINGS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    """Every test gets its own app and dataset stores, never the real files in data/."""
    monkeypatch.setenv("INSIGHTSQL_APP_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("INSIGHTSQL_DATASETS_DB_PATH", str(tmp_path / "datasets.db"))
    monkeypatch.setenv("INSIGHTSQL_UPLOADS_DIR", str(tmp_path / "uploads"))


@pytest.fixture(autouse=True)
def _restore_logging():
    """Undo configure_logging() (run by app tests) after each test, so redaction and the
    ``src`` log level never hide what another test checks, such as a key being logged."""
    src_logger = logging.getLogger("src")
    level, handlers = src_logger.level, list(src_logger.handlers)
    yield
    logging_setup.uninstall_redaction()
    src_logger.setLevel(level)
    src_logger.handlers[:] = handlers


@pytest.fixture
def seeded_db(tmp_path):
    """A freshly seeded database in a temporary directory (never the real one)."""
    db_path = tmp_path / "test.db"
    database.seed_sample_data(db_path)
    return db_path


TEST_TOKEN = "hf_test_token_DO_NOT_SHOW"
TEST_MODEL = "Qwen/Qwen2.5-Coder-32B-Instruct"


class FakeHF:
    """Scriptable stand-in for the Hugging Face Inference Providers API
    (POST /v1/chat/completions, GET /v1/models).

    Runs a real HTTP server on 127.0.0.1, so the production HTTP code, timeouts, and
    error handling are exercised without a token, a model, or internet access.
    """

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        """Back to the default state (used between tests that share one server)."""
        self.requests: list[tuple[str, dict | None]] = []
        self.auth_headers: list[str | None] = []
        self.status = 200
        self.raw_body: bytes | None = None
        self.delay = 0.0
        self.models = [TEST_MODEL]
        self.reply_sql("SELECT 1")

    def reply_sql(self, sql: str) -> None:
        """Reply with the {"sql": ...} JSON the prompt asks for."""
        self.reply_content(json.dumps({"sql": sql}))

    def reply_content(self, content: str) -> None:
        self.raw_body = None
        self.body = {
            "object": "chat.completion",
            "model": TEST_MODEL,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        }

    def fail(self, status: int, error: str) -> None:
        self.status, self.body = status, {"error": error}

    @property
    def chat_requests(self) -> list[dict]:
        return [payload for path, payload in self.requests if path == "/v1/chat/completions"]


def _handler_for(fake: FakeHF):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status, payload):
            data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            fake.requests.append((self.path, json.loads(self.rfile.read(length) or b"null")))
            fake.auth_headers.append(self.headers.get("Authorization"))
            if fake.delay:
                time.sleep(fake.delay)
            self._send(fake.status, fake.raw_body if fake.raw_body is not None else fake.body)

        def do_GET(self):
            fake.requests.append((self.path, None))
            fake.auth_headers.append(self.headers.get("Authorization"))
            self._send(200, {"object": "list", "data": [{"id": m, "object": "model"} for m in fake.models]})

        def log_message(self, *args):
            pass

    return Handler


@contextmanager
def running_fake_hf():
    """Start a FakeHF HTTP server; yields (fake, base_url)."""
    fake = FakeHF()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(fake))
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield fake, f"http://127.0.0.1:{server.server_address[1]}/v1"
    finally:
        server.shutdown()
        server.server_close()


def unused_port() -> int:
    """A local port with nothing listening on it (connections are refused)."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def fake_hf(monkeypatch):
    """A running fake Hugging Face API; the app's HF_* settings point at it."""
    with running_fake_hf() as (fake, base_url):
        monkeypatch.setenv("AI_PROVIDER", "huggingface")
        monkeypatch.setenv("HF_BASE_URL", base_url)
        monkeypatch.setenv("HF_TOKEN", TEST_TOKEN)
        monkeypatch.setenv("HF_MODEL", TEST_MODEL)
        monkeypatch.setenv("HF_TIMEOUT_SECONDS", "5")
        yield fake


@pytest.fixture
def hf_down(monkeypatch):
    """Token set, but HF_BASE_URL points at a local port with nothing listening."""
    monkeypatch.setenv("AI_PROVIDER", "huggingface")
    monkeypatch.setenv("HF_BASE_URL", f"http://127.0.0.1:{unused_port()}/v1")
    monkeypatch.setenv("HF_TOKEN", TEST_TOKEN)
    monkeypatch.setenv("HF_MODEL", TEST_MODEL)


@pytest.fixture
def no_hf_token(fake_hf, monkeypatch):
    """The fake API is running, but no token is configured."""
    monkeypatch.delenv("HF_TOKEN", raising=False)
    return fake_hf


# --- Fake Gemini API --------------------------------------------------------------

GEMINI_TEST_KEY = "AIzaTEST_KEY_DO_NOT_SHOW"
GEMINI_TEST_MODEL = "gemini-3.5-flash-lite"


class FakeGemini:
    """Scriptable stand-in for the Gemini API (generateContent and models.get).

    A real HTTP server on 127.0.0.1: the official google-genai SDK runs unchanged against
    it (via GEMINI_BASE_URL), so request building, headers, timeouts and error parsing are
    all exercised without a key, a model, or internet access.
    """

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self.requests: list[tuple[str, str, dict | None]] = []  # (method, path, body)
        self.api_key_headers: list[str | None] = []
        self.status = 200
        self.raw_body: bytes | None = None
        self.delay = 0.0
        self.models = [GEMINI_TEST_MODEL]
        self.reply_sql("SELECT 1")

    def reply_sql(self, sql: str) -> None:
        """Reply with the {"sql": ...} JSON the request asks for."""
        self.reply_text(json.dumps({"sql": sql}))

    def reply_text(self, text: str, finish_reason: str = "STOP") -> None:
        self.status, self.raw_body = 200, None
        self.body = {
            "candidates": [
                {"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": finish_reason}
            ],
            "modelVersion": GEMINI_TEST_MODEL,
        }

    def fail(self, code: int, status: str, message: str) -> None:
        """Reply with a Google API error body, e.g. fail(429, "RESOURCE_EXHAUSTED", "...")."""
        self.status, self.raw_body = code, None
        self.body = {"error": {"code": code, "status": status, "message": message}}

    @property
    def generate_requests(self) -> list[dict]:
        return [body for method, path, body in self.requests if path.endswith(":generateContent")]


def _gemini_handler_for(fake: FakeGemini):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status, payload):
            data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _record(self, body):
            fake.requests.append((self.command, self.path, body))
            fake.api_key_headers.append(self.headers.get("x-goog-api-key"))

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            self._record(json.loads(self.rfile.read(length) or b"null"))
            if fake.delay:
                time.sleep(fake.delay)
            self._send(fake.status, fake.raw_body if fake.raw_body is not None else fake.body)

        def do_GET(self):  # models.get: /v1beta/models/<model>
            self._record(None)
            model = self.path.rsplit("/", 1)[-1]
            if fake.status != 200:
                return self._send(fake.status, fake.body)
            if model not in fake.models:
                return self._send(404, {"error": {"code": 404, "status": "NOT_FOUND",
                                                  "message": f"models/{model} is not found"}})
            self._send(200, {"name": f"models/{model}", "displayName": model})

        def log_message(self, *args):
            pass

    return Handler


@contextmanager
def running_fake_gemini():
    """Start a FakeGemini HTTP server; yields (fake, base_url)."""
    fake = FakeGemini()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _gemini_handler_for(fake))
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield fake, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def use_gemini(monkeypatch, base_url: str) -> None:
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_BASE_URL", base_url)
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_TEST_KEY)
    monkeypatch.setenv("GEMINI_MODEL", GEMINI_TEST_MODEL)
    monkeypatch.setenv("GEMINI_TIMEOUT_SECONDS", "5")


@pytest.fixture
def fake_gemini(monkeypatch):
    """A running fake Gemini API; AI Mode is set to Gemini and points at it."""
    with running_fake_gemini() as (fake, base_url):
        use_gemini(monkeypatch, base_url)
        yield fake


@pytest.fixture
def gemini_down(monkeypatch):
    """Key set, but GEMINI_BASE_URL points at a local port with nothing listening."""
    use_gemini(monkeypatch, f"http://127.0.0.1:{unused_port()}")


@pytest.fixture
def no_gemini_key(fake_gemini, monkeypatch):
    """The fake API is running, but no key is configured."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    return fake_gemini

