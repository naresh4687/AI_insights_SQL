"""REST API connector against a local fake API: auth, pagination, limits, SSRF, and import."""

import json
import logging

import pytest
from cryptography.fernet import Fernet

from src import config, data_access
from src.connectors import rest, snapshot
from src.connectors.profiles import ConnectionStore, ConnectorError
from src.ingest import store
from src.ingest.preprocess import CleanOptions, clean
from src.ingest.profiling import profile as profile_of
from src.ingest.readers import ReadOptions
from src.ingest.validation import validate
from src.query_service import answer_question
from tests.servers import API_KEY, API_TOKEN, BASIC, ORDERS, running_fake_api


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("INSIGHTSQL_SECRET_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("INSIGHTSQL_CONNECTOR_TIMEOUT_SECONDS", "2")
    with running_fake_api() as fake:
        monkeypatch.setenv("INSIGHTSQL_ALLOWED_PRIVATE_HOSTS", f"127.0.0.1:{fake.port}")
        yield fake


def connection(api, auth="bearer", **extra):
    secret = {"bearer": API_TOKEN, "header": API_KEY, "basic": BASIC[1], "none": None}[auth]
    profile = ConnectionStore(config.get_app_db_path()).save(
        f"API {auth}", "rest", {"base_url": api.base_url, "auth": auth, **extra}, secret)
    return profile, ConnectionStore(config.get_app_db_path()).secret(profile.connection_id)


def fetch(api, endpoint, auth="bearer", max_records=10_000, **extra):
    profile, secret = connection(api, auth, **extra)
    return rest.fetch(profile, secret, endpoint, max_records)


# --- Authentication -------------------------------------------------------------------------

def test_bearer_token_is_sent_in_the_header_only(api):
    result = fetch(api, rest.Endpoint("/orders", records_path="data"))
    assert len(result.records) == 7
    request = api.requests[-1]
    assert request["headers"]["Authorization"] == f"Bearer {API_TOKEN}"
    assert API_TOKEN not in json.dumps(request["query"])


def test_api_key_header_and_basic_auth(api):
    assert fetch(api, rest.Endpoint("/apikey"), auth="header", auth_header="X-API-Key").records == [{"id": 1}]
    assert fetch(api, rest.Endpoint("/basic"), auth="basic", username=BASIC[0]).records == [{"id": 1}]


def test_wrong_credentials_are_reported_without_the_secret(api, caplog):
    caplog.set_level(logging.DEBUG)
    profile, _ = connection(api)
    with pytest.raises(ConnectorError, match="rejected the credentials") as exc:
        rest.fetch(profile, "wrong-token-value", rest.Endpoint("/orders", records_path="data"), 100)
    assert "wrong-token-value" not in exc.value.message and "wrong-token-value" not in caplog.text
    assert API_TOKEN not in caplog.text


# --- Pagination -----------------------------------------------------------------------------

@pytest.mark.parametrize("endpoint, requests", [
    (rest.Endpoint("/orders", records_path="data", pagination="page", page_size=3), 3),
    (rest.Endpoint("/offset", pagination="offset", page_size=2), 4),
    (rest.Endpoint("/cursor", records_path="results", pagination="next_link", next_path="links.next"), 3),
])
def test_every_pagination_style_returns_every_record_once(api, endpoint, requests):
    result = fetch(api, endpoint)
    assert [r["id"] for r in result.records] == [o["id"] for o in ORDERS]
    assert len(api.requests) == requests and len(result.pages) == requests


def test_page_parameters_are_sent(api):
    fetch(api, rest.Endpoint("/orders", params={"status": "all"}, records_path="data", pagination="page", page_size=5))
    assert api.requests[0]["query"] == {"status": "all", "page": "1", "per_page": "5"}
    assert api.requests[1]["query"]["page"] == "2"


def test_too_many_pages_is_an_error_not_a_silent_cut(api):
    with pytest.raises(ConnectorError, match="more than 3 pages"):
        fetch(api, rest.Endpoint("/infinite", pagination="page", page_size=10, max_pages=3))


def test_too_many_records_is_an_error(api):
    with pytest.raises(ConnectorError, match="more than 5 records"):
        fetch(api, rest.Endpoint("/orders", records_path="data"), max_records=5)


# --- SSRF and redirects ---------------------------------------------------------------------

def test_redirects_are_never_followed(api):
    with pytest.raises(ConnectorError, match="redirect"):
        fetch(api, rest.Endpoint("/redirect"))
    assert [r["path"] for r in api.requests] == ["/v1/redirect"]


@pytest.mark.parametrize("path, message", [("/evil_next", "different address"), ("/other_host_next", "different address")])
def test_next_links_cannot_leave_the_api(api, path, message):
    with pytest.raises(ConnectorError, match=message):
        fetch(api, rest.Endpoint(path, records_path="results", pagination="next_link", next_path="links.next"))


@pytest.mark.parametrize("path", ["//evil.com/x", "https://evil.com/x", "/a/../../admin", "/x@evil.com", "orders",
                                  "/orders?token=1", "/a\\b"])
def test_endpoint_paths_cannot_change_the_host(api, path):
    with pytest.raises(ConnectorError):
        fetch(api, rest.Endpoint(path))
    assert api.requests == []


def test_private_api_is_refused_unless_allow_listed(api, monkeypatch):
    profile, secret = connection(api)
    monkeypatch.setenv("INSIGHTSQL_ALLOWED_PRIVATE_HOSTS", "")
    with pytest.raises(ConnectorError, match="private or local network"):
        rest.fetch(profile, secret, rest.Endpoint("/orders", records_path="data"), 100)
    assert api.requests == []


def test_environment_proxies_are_ignored(api, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")  # would fail if used
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:9")
    assert len(fetch(api, rest.Endpoint("/orders", records_path="data")).records) == 7


# --- Errors and limits ----------------------------------------------------------------------

@pytest.mark.parametrize("path, message", [
    ("/always429", "rate limiting"), ("/server_error", "HTTP 500"), ("/missing", "not found"),
    ("/html", "did not return JSON"), ("/bad_json", "not valid JSON"), ("/not_list", "No list of records"),
    ("/scalars", "must be JSON objects"), ("/slow", "did not answer in time"),
])
def test_bad_responses_are_explained(api, path, message):
    records_path = "data" if path == "/not_list" else ""
    with pytest.raises(ConnectorError, match=message):
        fetch(api, rest.Endpoint(path, records_path=records_path))


def test_rate_limit_is_retried_as_the_server_asks(api):
    assert len(fetch(api, rest.Endpoint("/ratelimit")).records) == 2
    assert api.counters["/ratelimit"] == 2


def test_oversized_responses_are_refused(api, monkeypatch):
    monkeypatch.setattr(rest, "MAX_RESPONSE_BYTES", 50_000)
    with pytest.raises(ConnectorError, match="larger than"):
        fetch(api, rest.Endpoint("/big"))


# --- Records to a table ---------------------------------------------------------------------

def test_nested_records_are_flattened_without_losing_data(api):
    frame = rest.to_frame(fetch(api, rest.Endpoint("/orders", records_path="data")).records)
    assert list(frame.columns) == ["id", "amount", "paid", "tags", "note", "customer_name", "customer_address"]
    first = frame.iloc[0].to_dict()
    assert first["customer_name"] == "C1" and json.loads(first["customer_address"]) == {"city": "Chennai"}
    assert first["tags"] == '["a", "b"]' and first["note"] == "" and first["paid"] == "false"


def test_preview_fetches_only_the_first_page(api):
    profile, secret = connection(api)
    frame = rest.preview(profile, secret, rest.Endpoint("/orders", records_path="data", pagination="page", page_size=3))
    assert len(frame) == 3 and len(api.requests) == 1


def test_api_snapshot_imports_into_a_queryable_dataset(api, seeded_db):
    profile, secret = connection(api)
    snap = snapshot.from_api(profile, secret, rest.Endpoint("/orders", records_path="data", pagination="page",
                                                            page_size=3), max_records=1000, max_columns=50)
    result = clean(snap.raw, CleanOptions())
    dataset = store.save_import(
        name="API orders", description="", raw=snap.raw, content=snap.content, read_options=ReadOptions(),
        clean_options=CleanOptions(), result=result, checks=validate(snap.raw, profile_of(snap.raw)),
        confirmed_destructive=True, catalog=data_access.catalog(), datasets_db=config.get_datasets_db_path(),
        uploads_dir=config.get_uploads_dir(), source=snap.source)
    assert dataset.source_type.value == "rest"
    assert dataset.extra["source"]["endpoint"]["path"] == "/orders" and dataset.extra["source"]["pages"] == 3
    assert API_TOKEN not in json.dumps(dataset.extra)
    stored = config.get_uploads_dir() / dataset.dataset_id / "original.json"
    assert len(json.loads(stored.read_bytes())) == 3  # the 3 pages exactly as received
    target = data_access.target(dataset.dataset_id, seeded_db)
    answer = answer_question(seeded_db, "total", source="sql", target=target,
                             generate_sql=lambda q: "SELECT COUNT(*), SUM(amount) FROM api_orders WHERE paid = 1")
    assert answer.data.values.tolist() == [[3, 18.0]]  # orders 2, 4, 6 are paid: 3 + 6 + 9
    assert dict(zip([c.name for c in result.columns], [c.kind for c in result.columns]))["amount"] == "float"
