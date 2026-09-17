"""Verified-host resolution. Forwarded host is accepted only from our keyed proxy."""
from __future__ import annotations

import hmac
import ipaddress
import os
import re
import socket
import ssl
import time
from urllib.parse import urlsplit

import dns.exception
import dns.resolver
from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .features import can_use_feature
from .models import TenantBranding, TenantDomain

_domain_cache: dict[str, tuple[float, str]] = {}


def platform_hosts() -> set[str]:
    hosts = {urlsplit(os.getenv("APP_ORIGIN", "http://localhost:3000")).hostname or "localhost"}
    hosts.update(value.strip().lower() for value in os.getenv("PLATFORM_HOSTS", "").split(",") if value.strip())
    if os.getenv("APP_ENV") != "production":
        hosts.update({"localhost", "127.0.0.1", "testserver"})
    return hosts


def proxy_key() -> str:
    configured = os.getenv("BRAND_PROXY_KEY", "")
    return configured or ("setu-development-proxy" if os.getenv("APP_ENV") != "production" else "")


def request_hostname(request: Request) -> str:
    forwarded = request.headers.get("x-setu-host", "")
    key = proxy_key()
    if forwarded and key and hmac.compare_digest(request.headers.get("x-setu-proxy-key", ""), key):
        return forwarded.lower().rstrip(".")
    # Never trust X-Forwarded-Host or a caller's tenant header.
    return (request.url.hostname or "").lower().rstrip(".")


def validate_hostname(value: str) -> str:
    hostname = value.strip().lower().rstrip(".")
    try:
        hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise ValueError("Enter a valid hostname") from error
    labels = hostname.split(".")
    if len(labels) < 3 or len(hostname) > 253 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels):
        raise ValueError("Use a public subdomain such as portal.example.org without a URL, path or port")
    if labels[-1] in {"local", "localhost", "internal", "test", "invalid", "example"} or not re.fullmatch(r"[a-z]{2,63}|xn--[a-z0-9-]+", labels[-1]):
        raise ValueError("Use a public internet domain")
    if any(hostname == host or hostname.endswith("." + host) for host in platform_hosts()):
        raise ValueError("Platform domains cannot be claimed")
    return hostname


def invalidate_domains():
    _domain_cache.clear()


def active_domain(db: Session, hostname: str) -> TenantDomain | None:
    cached = _domain_cache.get(hostname)
    domain = db.get(TenantDomain, cached[1]) if cached and cached[0] > time.monotonic() else None
    if not domain:
        domain = db.scalar(select(TenantDomain).where(TenantDomain.hostname == hostname))
        if domain:
            if len(_domain_cache) >= 512:
                _domain_cache.clear()
            _domain_cache[hostname] = (time.monotonic() + 30, domain.id)
    # Recheck mutable state on every access, including across workers.
    if not domain or domain.hostname != hostname or domain.platform_suspended or domain.status != "ACTIVE" or domain.ssl_status != "ACTIVE":
        return None
    branding = db.get(TenantBranding, domain.tenant_id)
    if (branding and branding.status == "SUSPENDED") or not can_use_feature(db, domain.tenant_id, "white_label"):
        return None
    return domain


def enforce_request_tenant(request: Request, db: Session, tenant_id: str):
    hostname = request_hostname(request)
    if hostname in platform_hosts():
        return
    domain = active_domain(db, hostname)
    if not domain or domain.tenant_id != tenant_id:
        raise HTTPException(403, "This domain is not authorized for this workspace")


def custom_origin_allowed(request: Request, origin: str) -> bool:
    try:
        parsed = urlsplit(origin)
        valid = parsed.scheme == "https" and parsed.port in {None, 443} and not (parsed.path or parsed.query or parsed.fragment or parsed.username)
    except ValueError:
        return False
    if not valid:
        return False
    hostname = request_hostname(request)
    if parsed.hostname != hostname:
        return False
    from .database import SessionLocal
    with SessionLocal() as db:
        return active_domain(db, hostname) is not None


def dns_records(hostname: str, kind: str) -> list[str]:
    resolver = dns.resolver.Resolver()
    resolver.timeout = 2
    resolver.lifetime = 4
    try:
        answers = resolver.resolve(hostname, kind, search=False)
        if kind == "TXT":
            return [b"".join(answer.strings).decode("utf-8", errors="replace") for answer in answers]
        return [str(answer).rstrip(".").lower() for answer in answers]
    except dns.exception.DNSException:
        return []


def valid_https(hostname: str) -> bool:
    addresses = dns_records(hostname, "A") + dns_records(hostname, "AAAA")
    if not addresses:
        return False
    try:
        # Reject private/reserved DNS answers and connect to the validated address,
        # not a second DNS lookup (prevents SSRF/DNS rebinding).
        if any(not ipaddress.ip_address(address).is_global for address in addresses):
            return False
        with socket.create_connection((addresses[0], 443), timeout=4) as connection:
            with ssl.create_default_context().wrap_socket(connection, server_hostname=hostname):
                return True
    except (ValueError, OSError, ssl.SSLError):
        return False


def verify_domain_records(domain: TenantDomain) -> tuple[bool, bool]:
    token_found = domain.verification_token in dns_records("_setu-verification." + domain.hostname, "TXT")
    domain.routing_verified = False
    if not token_found:
        return False, False
    target = os.getenv("WHITE_LABEL_CNAME_TARGET", "").strip().lower().rstrip(".")
    routed = bool(target and target in dns_records(domain.hostname, "CNAME"))
    domain.routing_verified = routed
    return True, routed and valid_https(domain.hostname)
