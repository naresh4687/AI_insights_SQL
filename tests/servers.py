"""Test servers for connector tests: PostgreSQL and MySQL in Docker, and a fake REST API.

The database servers are throwaway containers bound to 127.0.0.1 on random ports, with test
passwords only. They are started once per test session and removed afterwards. Without Docker
(or the images) the database tests are skipped with the reason shown.
"""

import base64
import json
import shutil
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

ADMIN_PASSWORD = "admin-test-pass-1"
READER_PASSWORD = "reader-test-pass-1"
IMAGES = {"postgres": "postgres:17-alpine", "mysql": "mysql:8.4"}

POSTGRES_SEED = f"""
CREATE SCHEMA shop;
CREATE TABLE shop.orders (
    order_id integer PRIMARY KEY, customer text, amount numeric(10, 2), ordered_on date,
    created_at timestamptz, paid boolean, note text, photo bytea);
INSERT INTO shop.orders VALUES
    (1, 'Zoë', 10.50, '2025-01-05', '2025-01-05 10:00:00+05:30', true, '=HYPERLINK("x")', '\\x00ff'),
    (2, 'Acme', 20.00, '2025-02-10', '2025-02-10 08:30:00+00:00', false, NULL, NULL),
    (3, NULL, NULL, NULL, NULL, NULL, 'plain', NULL);
CREATE VIEW shop.big_orders AS SELECT order_id, amount FROM shop.orders WHERE amount > 15;
CREATE TABLE shop.many AS SELECT g AS n FROM generate_series(1, 1500) AS g;
CREATE TABLE public."Order Items" (id integer, qty integer);
INSERT INTO public."Order Items" VALUES (1, 5), (2, 7);
CREATE TABLE public.salaries (id integer, salary integer);
INSERT INTO public.salaries VALUES (1, 90000);
CREATE ROLE reader LOGIN PASSWORD '{READER_PASSWORD}';
GRANT USAGE ON SCHEMA shop TO reader;
GRANT SELECT ON ALL TABLES IN SCHEMA shop TO reader;
GRANT SELECT ON public."Order Items" TO reader;
ALTER ROLE reader SET timezone = 'Asia/Kolkata';  -- values come back as +05:30, so UTC conversion is tested
"""

MYSQL_SEED = [
    "CREATE TABLE orders (order_id INT PRIMARY KEY, customer VARCHAR(50), amount DECIMAL(10, 2), ordered_on DATE, "
    "created_at DATETIME, paid BOOLEAN, note TEXT, photo BLOB)",
    "INSERT INTO orders VALUES (1, 'Zoë', 10.50, '2025-01-05', '2025-01-05 10:00:00', TRUE, '=HYPERLINK(\"x\")', "
    "X'00FF'), (2, 'Acme', 20.00, '2025-02-10', '2025-02-10 08:30:00', FALSE, NULL, NULL), "
    "(3, NULL, NULL, NULL, NULL, NULL, 'plain', NULL)",
    "CREATE VIEW big_orders AS SELECT order_id, amount FROM orders WHERE amount > 15",
    "CREATE TABLE many (n INT)",
    "SET SESSION cte_max_recursion_depth = 2000",
    "INSERT INTO many WITH RECURSIVE seq(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM seq WHERE n < 1500) "
    "SELECT n FROM seq",
    "CREATE TABLE `Order Items` (id INT, qty INT)",
    "INSERT INTO `Order Items` VALUES (1, 5), (2, 7)",
    "CREATE TABLE salaries (id INT, salary INT)",
    "INSERT INTO salaries VALUES (1, 90000)",
    f"CREATE USER 'reader'@'%' IDENTIFIED BY '{READER_PASSWORD}'",
    "GRANT SELECT ON shop.orders TO 'reader'@'%'",
    "GRANT SELECT ON shop.big_orders TO 'reader'@'%'",
    "GRANT SELECT ON shop.many TO 'reader'@'%'",
    "GRANT SELECT ON shop.`Order Items` TO 'reader'@'%'",
]


def docker_available() -> str | None:
    """None if Docker and both images are available, else the reason."""
    if not shutil.which("docker"):
        return "Docker is not installed"
    try:
        subprocess.run(["docker", "info"], check=True, capture_output=True, timeout=20)
    except (subprocess.SubprocessError, OSError):
        return "Docker is not running or not accessible"
    for image in IMAGES.values():
        found = subprocess.run(["docker", "image", "inspect", image], capture_output=True)
        if found.returncode != 0:
            return f"Docker image {image} is not available (docker pull {image})"
    return None


class DatabaseServer:
    def __init__(self, kind: str, container: str, port: int):
        self.kind, self.container, self.port = kind, container, port

    @property
    def database(self) -> str:
        return "shop"

    def settings(self, username="reader", **overrides) -> dict:
        return {"host": "127.0.0.1", "port": self.port, "database": self.database, "username": username,
                "ssl": "disable", **overrides}


def _start(kind: str) -> DatabaseServer:
    name = f"insightsql-test-{kind}-{uuid.uuid4().hex[:8]}"
    env = (["-e", f"POSTGRES_PASSWORD={ADMIN_PASSWORD}", "-e", "POSTGRES_DB=shop"] if kind == "postgres" else
           ["-e", f"MYSQL_ROOT_PASSWORD={ADMIN_PASSWORD}", "-e", "MYSQL_DATABASE=shop"])
    inner = 5432 if kind == "postgres" else 3306
    subprocess.run(["docker", "run", "-d", "--rm", "--name", name, *env, "-p", f"127.0.0.1::{inner}", IMAGES[kind]],
                   check=True, capture_output=True, timeout=120)
    try:
        mapping = subprocess.run(["docker", "port", name, str(inner)], check=True, capture_output=True,
                                 text=True).stdout
        server = DatabaseServer(kind, name, int(mapping.strip().splitlines()[0].rsplit(":", 1)[1]))
        _wait_until_ready(server)
        _seed(server)  # once: a failure here is a real error and is reported as it is
        return server
    except BaseException:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=60)
        raise


def _admin_connection(server: DatabaseServer):
    if server.kind == "postgres":
        import psycopg
        return psycopg.connect(host="127.0.0.1", port=server.port, user="postgres", password=ADMIN_PASSWORD,
                               dbname="shop", connect_timeout=3, autocommit=True)
    import pymysql
    return pymysql.connect(host="127.0.0.1", port=server.port, user="root", password=ADMIN_PASSWORD,
                           database="shop", connect_timeout=3, autocommit=True)


def _wait_until_ready(server: DatabaseServer) -> None:
    deadline, last = time.monotonic() + 180, None
    while time.monotonic() < deadline:
        try:
            conn = _admin_connection(server)
            try:
                conn.cursor().execute("SELECT 1")
            finally:
                conn.close()
            return
        except Exception as exc:  # still starting
            last = exc
            time.sleep(1)
    raise RuntimeError(f"{server.kind} test server did not start: {last}")


def _seed(server: DatabaseServer) -> None:
    conn = _admin_connection(server)
    try:
        cursor = conn.cursor()
        for statement in ([POSTGRES_SEED] if server.kind == "postgres" else MYSQL_SEED):
            cursor.execute(statement)
    finally:
        conn.close()


def _stop(server: DatabaseServer) -> None:
    subprocess.run(["docker", "rm", "-f", server.container], capture_output=True, timeout=60)


@pytest.fixture(scope="session")
def db_servers():
    """{'postgres': DatabaseServer, 'mysql': DatabaseServer}, or skip with the reason."""
    reason = docker_available()
    if reason:
        pytest.skip(reason)
    servers = {}
    try:
        for kind in IMAGES:
            servers[kind] = _start(kind)
        yield servers
    finally:
        for server in servers.values():
            _stop(server)


# --- Fake REST API ----------------------------------------------------------------------

API_TOKEN = "api-test-token-SHOULD-NOT-LEAK-123"
API_KEY = "key-test-SHOULD-NOT-LEAK-456"
BASIC = ("apiuser", "basic-pass-SHOULD-NOT-LEAK-789")
ORDERS = [{"id": i, "customer": {"name": f"C{i}", "address": {"city": "Chennai"}}, "amount": i * 1.5,
           "paid": i % 2 == 0, "tags": ["a", "b"] if i == 1 else [], "note": "=cmd" if i == 2 else None}
          for i in range(1, 8)]


class FakeApi:
    def __init__(self):
        self.requests: list[dict] = []
        self.counters: dict[str, int] = {}
        self.port = 0
        self.orders = [dict(o) for o in ORDERS]  # change these to simulate new source data

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"


def _api_handler(api: FakeApi):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status, body=None, content_type="application/json", headers=None):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: C901 - one branch per scenario
            parts = urlsplit(self.path)
            query = {k: v[0] for k, v in parse_qs(parts.query).items()}
            api.requests.append({"path": parts.path, "query": query, "headers": dict(self.headers)})
            path = parts.path.removeprefix("/v1")
            count = api.counters[path] = api.counters.get(path, 0) + 1
            authorised = self.headers.get("Authorization") == f"Bearer {API_TOKEN}"
            if path == "/apikey":
                ok = self.headers.get("X-API-Key") == API_KEY
                return self._send(200, [{"id": 1}]) if ok else self._send(401, {"error": "no"})
            if path == "/basic":
                expected = "Basic " + base64.b64encode(f"{BASIC[0]}:{BASIC[1]}".encode()).decode()
                return self._send(200, [{"id": 1}]) if self.headers.get("Authorization") == expected else \
                    self._send(401, {"error": "no"})
            if path == "/public":
                return self._send(200, {"data": {"items": api.orders[:2]}})
            if not authorised:
                return self._send(401, {"error": "unauthorised"})
            if path == "/orders":
                page, size = int(query.get("page", 1)), int(query.get("per_page", 100))
                return self._send(200, {"data": api.orders[(page - 1) * size: page * size]})
            if path == "/offset":
                offset, limit = int(query.get("offset", 0)), int(query.get("limit", 100))
                return self._send(200, api.orders[offset: offset + limit])
            if path == "/cursor":
                after = int(query.get("after", 0))
                chunk = api.orders[after: after + 3]
                nxt = f"/v1/cursor?after={after + 3}" if after + 3 < len(api.orders) else None
                return self._send(200, {"results": chunk, "links": {"next": nxt}})
            if path == "/evil_next":
                return self._send(200, {"results": api.orders[:1], "links": {"next": "http://169.254.169.254/latest"}})
            if path == "/other_host_next":
                return self._send(200, {"results": api.orders[:1], "links": {"next": "https://example.com/steal"}})
            if path == "/redirect":
                return self._send(302, {}, headers={"Location": "http://169.254.169.254/latest/meta-data"})
            if path == "/ratelimit":
                return self._send(429, {"error": "slow down"}, headers={"Retry-After": "0"}) if count == 1 else \
                    self._send(200, api.orders[:2])
            if path == "/always429":
                return self._send(429, {"error": "slow down"}, headers={"Retry-After": "0"})
            if path == "/server_error":
                return self._send(500, {"error": "boom"})
            if path == "/html":
                return self._send(200, b"<html>hi</html>", content_type="text/html")
            if path == "/bad_json":
                return self._send(200, b"{not json")
            if path == "/not_list":
                return self._send(200, {"data": {"a": 1}})
            if path == "/scalars":
                return self._send(200, [1, 2, 3])
            if path == "/empty":
                return self._send(200, [])
            if path == "/big":
                return self._send(200, [{"text": "x" * 1000} for _ in range(100)])
            if path == "/slow":
                time.sleep(3)
                return self._send(200, [])
            if path == "/infinite":
                size = int(query.get("per_page", 100))
                return self._send(200, [{"n": i} for i in range(size)])
            return self._send(404, {"error": "not found"})

        def log_message(self, *args):
            pass

    return Handler


@contextmanager
def running_fake_api():
    api = FakeApi()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _api_handler(api))
    server.daemon_threads = True
    api.port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield api
    finally:
        server.shutdown()
        server.server_close()
