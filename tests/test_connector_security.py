"""Connector security: network policy (SSRF), encrypted secrets and connection profiles."""

import logging
import sqlite3

import pytest
from cryptography.fernet import Fernet

from src import config
from src.connectors import network
from src.connectors.profiles import ConnectionStore, ConnectorError, validate_settings
from src.core import secrets

KEY = Fernet.generate_key().decode()
DB_SETTINGS = {"host": "db.example.com", "port": 5432, "database": "shop", "username": "reader", "ssl": "require"}


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("INSIGHTSQL_SECRET_KEY", KEY)
    return KEY


@pytest.fixture
def store(key):
    return ConnectionStore(config.get_app_db_path())


# --- Network policy ---------------------------------------------------------------------

@pytest.mark.parametrize("host", [
    "127.0.0.1", "localhost", "127.1.2.3", "10.0.0.1", "172.16.5.4", "192.168.1.1", "100.64.0.1",
    "0.0.0.0", "::1", "fe80::1", "fd12::1", "224.0.0.1", "2130706433", "0x7f000001", "017700000001",
    "::ffff:127.0.0.1", "::ffff:10.0.0.1",
])
def test_private_and_local_destinations_are_refused(host):
    with pytest.raises(network.DestinationError, match="private or local network"):
        network.check(host, 5432)


@pytest.mark.parametrize("host", ["169.254.169.254", "metadata.google.internal", "::ffff:169.254.169.254",
                                  "169.254.170.2", "100.100.100.200", "fd00:ec2::254"])
def test_metadata_is_refused_even_when_allow_listed(host, monkeypatch):
    monkeypatch.setenv("INSIGHTSQL_ALLOWED_PRIVATE_HOSTS", f"{host},{host}:80")
    with pytest.raises(network.DestinationError, match="metadata"):
        network.check(host, 80)


def test_allow_list_is_exact(monkeypatch):
    monkeypatch.setenv("INSIGHTSQL_ALLOWED_PRIVATE_HOSTS", "127.0.0.1:5432, DB.Internal")
    assert network.check("127.0.0.1", 5432).addresses == ("127.0.0.1",)
    for host, port in (("127.0.0.1", 3306), ("localhost", 5432), ("127.0.0.2", 5432)):
        with pytest.raises(network.DestinationError):
            network.check(host, port)


def test_every_resolved_address_is_checked(monkeypatch):
    """A name that resolves to a public AND a private address is refused."""
    def fake_resolve(host, port, **kwargs):
        return [(2, 1, 6, "", ("93.184.216.34", port)), (2, 1, 6, "", ("10.0.0.5", port))]
    monkeypatch.setattr(network.socket, "getaddrinfo", fake_resolve)
    with pytest.raises(network.DestinationError, match="10.0.0.5"):
        network.check("mixed.example.com", 443)


def test_ipv4_mapped_public_address_is_allowed():
    """::ffff:8.8.8.8 is the public address 8.8.8.8 written as IPv6, not a private one."""
    assert network.check("::ffff:8.8.8.8", 443).addresses == ("::ffff:8.8.8.8",)


def test_public_destination_is_allowed(monkeypatch):
    monkeypatch.setattr(network.socket, "getaddrinfo", lambda h, p, **k: [(2, 1, 6, "", ("93.184.216.34", p))])
    assert network.check("api.example.com", 443).addresses == ("93.184.216.34",)


@pytest.mark.parametrize("host, port", [("", 5432), ("http://x.com", 80), ("a b", 80), ("x.com", 0), ("x.com", 70000),
                                        ("user@x.com", 80), ("no-such-host.invalid", 80)])
def test_invalid_or_unknown_hosts(host, port):
    with pytest.raises(network.DestinationError):
        network.check(host, port)


# --- Secrets ----------------------------------------------------------------------------

def test_secrets_round_trip_and_are_not_plaintext(key):
    token = secrets.encrypt("s3cret-Password!")
    assert b"s3cret" not in token and secrets.decrypt(token) == "s3cret-Password!"


@pytest.mark.parametrize("value, message", [(None, "needs an encryption key"), ("not-a-key", "not a valid key")])
def test_missing_or_invalid_key(monkeypatch, value, message):
    if value:
        monkeypatch.setenv("INSIGHTSQL_SECRET_KEY", value)
    with pytest.raises(secrets.SecretError, match=message):
        secrets.encrypt("x")
    assert not secrets.available()


def test_changed_key_cannot_read_old_secrets(monkeypatch, key):
    token = secrets.encrypt("old")
    monkeypatch.setenv("INSIGHTSQL_SECRET_KEY", Fernet.generate_key().decode())
    with pytest.raises(secrets.SecretError, match="was the key changed"):
        secrets.decrypt(token)


# --- Profiles ---------------------------------------------------------------------------

def test_profile_stores_settings_and_only_an_encrypted_secret(store):
    profile = store.save("Shop DB", "postgres", DB_SETTINGS, "pw-SHOULD-NOT-BE-STORED")
    assert profile.connection_id == "shop_db" and profile.has_secret and profile.kind_label == "PostgreSQL"
    assert profile.summary == "reader@db.example.com:5432/shop"
    assert store.secret("shop_db") == "pw-SHOULD-NOT-BE-STORED"
    raw = config.get_app_db_path().read_bytes()
    assert b"pw-SHOULD-NOT-BE-STORED" not in raw
    conn = sqlite3.connect(config.get_app_db_path())
    try:
        settings = conn.execute("SELECT settings_json FROM connections").fetchone()[0]
    finally:
        conn.close()
    assert "pw-" not in settings and "password" not in settings


def test_updating_without_a_secret_keeps_it(store):
    store.save("Shop DB", "postgres", DB_SETTINGS, "first")
    updated = store.save("Shop DB", "postgres", {**DB_SETTINGS, "port": 6543}, None, connection_id="shop_db")
    assert updated.settings["port"] == 6543 and store.secret("shop_db") == "first"
    store.save("Shop DB", "postgres", DB_SETTINGS, "second", connection_id="shop_db")
    assert store.secret("shop_db") == "second"


def test_new_database_profile_needs_a_secret(store):
    with pytest.raises(ConnectorError, match="password"):
        store.save("Shop", "postgres", DB_SETTINGS, None)


def test_api_without_authentication_has_no_secret(store, monkeypatch):
    profile = store.save("Open API", "rest", {"base_url": "https://api.example.com/v1/", "auth": "none"}, "ignored")
    assert not profile.has_secret and profile.settings["base_url"] == "https://api.example.com/v1"


def test_duplicate_names_and_ids(store):
    store.save("Shop", "postgres", DB_SETTINGS, "x")
    with pytest.raises(ConnectorError, match="already exists"):
        store.save("Shop", "mysql", {**DB_SETTINGS, "ssl": "disable", "port": 3306}, "x")
    assert store.save("Shop!", "postgres", DB_SETTINGS, "x").connection_id == "shop_2"


def test_saving_without_a_key_is_refused_and_stores_nothing(monkeypatch):
    s = ConnectionStore(config.get_app_db_path())
    with pytest.raises(secrets.SecretError):
        s.save("Shop", "postgres", DB_SETTINGS, "pw")
    assert s.list() == []


def test_delete_and_test_status(store):
    store.save("Shop", "postgres", DB_SETTINGS, "x")
    store.record_test("shop", True)
    assert store.get("shop").last_test_ok is True and store.get("shop").last_tested_at
    store.delete("shop")
    assert store.get("shop") is None and store.list() == []


@pytest.mark.parametrize("kind, settings, message", [
    ("oracle", {}, "Choose"),
    ("postgres", {**DB_SETTINGS, "host": "https://db.example.com"}, "host name"),
    ("postgres", {**DB_SETTINGS, "host": "db.example.com/x"}, "host name"),
    ("postgres", {**DB_SETTINGS, "port": "abc"}, "number"),
    ("postgres", {**DB_SETTINGS, "port": 0}, "between"),
    ("postgres", {**DB_SETTINGS, "database": ""}, "database name"),
    ("postgres", {**DB_SETTINGS, "username": ""}, "user name"),
    ("postgres", {**DB_SETTINGS, "ssl": "maybe"}, "encryption"),
    ("rest", {"base_url": "ftp://x.com"}, "base address"),
    ("rest", {"base_url": "https://user:pw@x.com"}, "must not contain"),
    ("rest", {"base_url": "https://x.com/v1?token=abc"}, "must not contain"),
    ("rest", {"base_url": "http://api.example.com"}, "Use https://"),
    ("rest", {"base_url": "https://x.com", "auth": "header", "auth_header": "Bad Header"}, "header name"),
    ("rest", {"base_url": "https://x.com", "auth": "header", "auth_header": "Host"}, "header name"),
    ("rest", {"base_url": "https://x.com", "auth": "basic", "username": "a:b"}, "user name"),
])
def test_invalid_settings(kind, settings, message):
    with pytest.raises(ConnectorError, match=message):
        validate_settings(kind, settings)


def test_plain_http_only_for_allow_listed_api_hosts(monkeypatch):
    monkeypatch.setenv("INSIGHTSQL_ALLOWED_PRIVATE_HOSTS", "127.0.0.1:8080")
    assert validate_settings("rest", {"base_url": "http://127.0.0.1:8080/v1"})["base_url"] == "http://127.0.0.1:8080/v1"


def test_secret_key_never_appears_in_logs(key, caplog):
    from src.core.logging_setup import configure_logging
    configure_logging()
    caplog.set_level(logging.DEBUG)
    logging.getLogger("src.test").warning("loaded key %s", key)
    assert key not in caplog.text
