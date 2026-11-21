"""Client address resolution for rate limits: forwarded headers only from configured proxies."""
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.auth import configured_limit, request_ip
from app.main import app

HEADERS = {"X-Setu-Request": "1"}


def make_request(peer, forwarded=None):
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded is not None else []
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers,
                    "client": (peer, 50000), "query_string": b""})


def test_forwarded_header_is_ignored_by_default(monkeypatch):
    monkeypatch.delenv("AUTH_TRUSTED_PROXIES", raising=False)
    assert request_ip(make_request("10.0.0.5", "203.0.113.9")) == "10.0.0.5"


def test_untrusted_peer_cannot_choose_its_address(monkeypatch):
    monkeypatch.setenv("AUTH_TRUSTED_PROXIES", "10.0.0.0/8")
    assert request_ip(make_request("198.51.100.7", "203.0.113.9")) == "198.51.100.7"


def test_trusted_proxy_reports_the_nearest_untrusted_hop(monkeypatch):
    monkeypatch.setenv("AUTH_TRUSTED_PROXIES", "10.0.0.0/8, 192.0.2.10")
    # A client-supplied fake entry on the left is skipped; the proxies appended the real address.
    request = make_request("10.0.0.5", "1.2.3.4, 203.0.113.9, 192.0.2.10")
    assert request_ip(request) == "203.0.113.9"


def test_malformed_or_fully_trusted_chains_fall_back_to_the_peer(monkeypatch):
    monkeypatch.setenv("AUTH_TRUSTED_PROXIES", "10.0.0.0/8")
    assert request_ip(make_request("10.0.0.5", "not-an-ip, 203.0.113.9")) == "203.0.113.9"
    assert request_ip(make_request("10.0.0.5", "203.0.113.9, garbage")) == "10.0.0.5"
    assert request_ip(make_request("10.0.0.5", "10.1.1.1")) == "10.0.0.5"
    assert request_ip(make_request("10.0.0.5", "")) == "10.0.0.5"


def test_invalid_trusted_proxy_entries_are_ignored(monkeypatch):
    monkeypatch.setenv("AUTH_TRUSTED_PROXIES", "not-a-network")
    assert request_ip(make_request("10.0.0.5", "203.0.113.9")) == "10.0.0.5"


def test_configured_limit_is_bounded(monkeypatch):
    monkeypatch.delenv("AUTH_LOGIN_IP_RATE_LIMIT", raising=False)
    assert configured_limit("AUTH_LOGIN_IP_RATE_LIMIT", 60) == 60
    for raw, expected in (("0", 1), ("-5", 1), ("abc", 60), ("999999", 10_000), ("250", 250)):
        monkeypatch.setenv("AUTH_LOGIN_IP_RATE_LIMIT", raw)
        assert configured_limit("AUTH_LOGIN_IP_RATE_LIMIT", 60) == expected


def test_login_ip_limit_still_applies_and_ignores_spoofed_headers(monkeypatch):
    monkeypatch.setenv("AUTH_LOGIN_IP_RATE_LIMIT", "3")
    monkeypatch.delenv("AUTH_TRUSTED_PROXIES", raising=False)
    with TestClient(app) as client:
        statuses = [client.post("/api/v1/auth/login", headers=HEADERS | {"X-Forwarded-For": f"203.0.113.{n}"},
                                json={"email": f"nobody{n}@example.test", "password": "Wrong-password-123!"}).status_code
                    for n in range(4)]
    assert statuses == [401, 401, 401, 429]
