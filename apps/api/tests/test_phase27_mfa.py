"""Phase 27 two-step verification: enrollment, session gate, replay, recovery and admin policy."""
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select

from app.auth_admin import grant
from app.auth_models import AuthSecurityEvent
from app.database import SessionLocal
from app.main import app
from app.mfa import (MfaFactor, MfaSessionVerification, matching_step, totp, validate_mfa_configuration,
                     STEP_SECONDS)
from app.migrate_phase27 import VERSION, apply

PASSWORD = "Two-step-testing-passphrase-2026!"
HEADERS = {"X-Setu-Request": "1"}
EMAIL = "mfa-owner@example.test"


def signup(client, email=EMAIL):
    response = client.post("/api/v1/auth/signup", headers=HEADERS, json={
        "name": "MFA Owner", "workspace_name": "MFA Workspace", "email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    return response.json()


def login(client, email=EMAIL, admin=False):
    return client.post("/api/v1/" + ("admin/auth/login" if admin else "auth/login"), headers=HEADERS,
                       json={"email": email, "password": PASSWORD})


def code_for(secret, offset=0):
    return totp(secret, int(time.time() // STEP_SECONDS) + offset)


def enroll(client):
    setup = client.post("/api/v1/auth/mfa/setup", headers=HEADERS)
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    assert setup.json()["otpauth_uri"].startswith("otpauth://totp/")
    enabled = client.post("/api/v1/auth/mfa/enable", headers=HEADERS, json={"code": code_for(secret)})
    assert enabled.status_code == 200, enabled.text
    codes = enabled.json()["recovery_codes"]
    assert len(codes) == 10 and len(set(codes)) == 10
    return secret, codes


def test_rfc6238_reference_vector():
    # RFC 6238 appendix B, SHA-1 secret "12345678901234567890" at T=59 -> 94287082 (8 digits), 287082 (6 digits)
    import base64
    secret = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
    assert totp(secret, 59 // 30) == "287082"
    assert matching_step(secret, "287082", 0, at=59) == 1
    assert matching_step(secret, "287082", 1, at=59) is None  # replay of an accepted step is refused
    assert matching_step(secret, "12345", 0, at=59) is None


def test_enrollment_gates_every_new_session_until_verified():
    with TestClient(app) as client:
        signup(client)
        assert client.get("/api/v1/auth/mfa").json()["enabled"] is False
        secret, codes = enroll(client)
        # The enrolling session is already verified and keeps working.
        assert client.get("/api/v1/auth/me").status_code == 200
        with SessionLocal() as db:
            factor = db.get(MfaFactor, client.get("/api/v1/auth/me").json()["user"]["id"])
            assert secret not in factor.secret_ciphertext  # stored sealed, never in clear
        assert client.post("/api/v1/auth/mfa/setup", headers=HEADERS).status_code == 409

    with TestClient(app) as fresh:
        assert login(fresh).status_code == 200
        blocked = fresh.get("/api/v1/auth/me")
        assert blocked.status_code == 401 and blocked.json()["detail"]["code"] == "MFA_REQUIRED"
        assert fresh.get("/api/v1/organizations").status_code == 401
        assert fresh.get("/api/v1/auth/mfa").json()["verified"] is False
        assert fresh.post("/api/v1/auth/mfa/verify", headers=HEADERS, json={"code": "000000"}).status_code == 400
        # A recovery code works once.
        assert fresh.post("/api/v1/auth/mfa/verify", headers=HEADERS, json={"code": codes[0]}).json()["method"] == "recovery"
        assert fresh.get("/api/v1/auth/me").status_code == 200
        assert fresh.get("/api/v1/auth/mfa").json()["recovery_codes_remaining"] == 9

    with TestClient(app) as again:
        assert login(again).status_code == 200
        assert again.post("/api/v1/auth/mfa/verify", headers=HEADERS, json={"code": codes[0]}).status_code == 400
        verified = again.post("/api/v1/auth/mfa/verify", headers=HEADERS, json={"code": code_for(secret, 1)})
        assert verified.status_code == 200 and verified.json()["method"] == "totp"
        assert again.get("/api/v1/auth/me").status_code == 200
        with SessionLocal() as db:
            events = {row.event for row in db.scalars(select(AuthSecurityEvent))}
        assert {"MFA_ENABLED", "MFA_FAILED", "MFA_RECOVERY_USED", "MFA_VERIFIED"} <= events


def test_verification_attempts_are_rate_limited():
    with TestClient(app) as client:
        signup(client)
        enroll(client)
    with TestClient(app) as fresh:
        assert login(fresh).status_code == 200
        statuses = [fresh.post("/api/v1/auth/mfa/verify", headers=HEADERS, json={"code": "111111"}).status_code
                    for _ in range(11)]
        # Enrollment already spent one attempt in this 15-minute window.
        assert 429 in statuses and set(statuses[:statuses.index(429)]) == {400}


def test_disable_requires_verified_session_password_and_code():
    with TestClient(app) as client:
        signup(client)
        secret, _ = enroll(client)
        wrong = client.post("/api/v1/auth/mfa/disable", headers=HEADERS, json={"password": "wrong", "code": code_for(secret, 1)})
        assert wrong.status_code == 400
        assert client.post("/api/v1/auth/mfa/disable", headers=HEADERS,
                           json={"password": PASSWORD, "code": code_for(secret, 1)}).status_code == 204
        assert client.get("/api/v1/auth/mfa").json()["enabled"] is False
    with TestClient(app) as fresh:
        assert login(fresh).status_code == 200
        assert fresh.get("/api/v1/auth/me").status_code == 200


def test_workspace_switch_keeps_the_second_factor():
    with TestClient(app) as first, TestClient(app) as second:
        owner = signup(first)
        signup(second, "mfa-other@example.test")
        invitation = first.post("/api/v1/admin/users/invite", headers=HEADERS,
                                json={"name": "Colleague", "email": "mfa-other@example.test", "role": "VIEWER"}).json()
        assert second.post("/api/v1/auth/accept-workspace-invitation", headers=HEADERS,
                           json={"token": invitation["token"], "password": PASSWORD}).status_code == 200
        enroll(second)
        switched = second.post("/api/v1/auth/workspace", headers=HEADERS, json={"tenant_id": owner["tenant_id"]})
        assert switched.status_code == 200
        assert second.get("/api/v1/auth/me").json()["user"]["tenant_id"] == owner["tenant_id"]


def test_admin_policy_requires_enrollment_then_verification(monkeypatch):
    monkeypatch.setenv("AUTH_ADMIN_MFA_REQUIRED", "1")
    monkeypatch.setenv("PLATFORM_ADMIN_EMAILS", EMAIL)
    with TestClient(app) as client:
        signup(client)
        with SessionLocal() as db:
            grant(db, EMAIL)
        assert login(client, admin=True).status_code == 200
        needed = client.get("/api/v1/admin/auth/access")
        assert needed.status_code == 403 and needed.json()["detail"]["code"] == "MFA_ENROLLMENT_REQUIRED"
        assert client.get("/api/v1/auth/mfa").json()["required"] is True
        secret, _ = enroll(client)
        assert client.get("/api/v1/admin/auth/access").json()["allowed"] is True
    with TestClient(app) as fresh:
        assert login(fresh, admin=True).status_code == 200
        assert fresh.get("/api/v1/admin/auth/access").json()["detail"]["code"] == "MFA_REQUIRED"
        assert fresh.post("/api/v1/auth/mfa/verify", headers=HEADERS, json={"code": code_for(secret, 1)}).status_code == 200
        assert fresh.get("/api/v1/admin/auth/access").json()["allowed"] is True
        # Ordinary workspace sign-in is not forced to enroll by the admin policy.
        assert login(fresh).status_code == 200


def test_production_configuration_fails_closed():
    base = {"APP_ENV": "production"}
    validate_mfa_configuration(base)
    with pytest.raises(RuntimeError):
        validate_mfa_configuration(base | {"AUTH_ADMIN_MFA_REQUIRED": "1"})
    with pytest.raises(RuntimeError):
        validate_mfa_configuration(base | {"AUTH_MFA_ENCRYPTION_KEY": "too-short"})
    validate_mfa_configuration(base | {"AUTH_MFA_ENCRYPTION_KEY": "A" * 43})


def test_invalid_key_refuses_setup(monkeypatch):
    with TestClient(app) as client:
        signup(client)
        monkeypatch.setenv("AUTH_MFA_ENCRYPTION_KEY", "not-a-32-byte-key")
        assert client.get("/api/v1/auth/mfa").json()["available"] is False
        assert client.post("/api/v1/auth/mfa/setup", headers=HEADERS).status_code == 503


def test_phase27_migration_is_additive_and_idempotent(tmp_path):
    target = create_engine(f"sqlite:///{tmp_path / 'phase27.db'}")
    assert apply(target) == VERSION and apply(target) == VERSION
    names = set(inspect(target).get_table_names())
    assert {"auth_mfa_factors", "auth_mfa_recovery_codes", MfaSessionVerification.__tablename__} <= names
    target.dispose()
