from datetime import timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import COOKIE_NAME, EmailInput, PasswordInput, digest, hash_password, issue_token, now, verify_password
from app.database import SessionLocal
from app.main import app
from app.models import AuthSession, AuthToken, User
from app.schemas import MembershipCreate

PASSWORD = "A-unique-testing-passphrase-2026"
NEW_PASSWORD = "A-different-testing-passphrase-2026"
HEADERS = {"X-Setu-Request": "1", "Origin": "http://localhost:3000"}


def signup(client, email="owner@example.test"):
    response = client.post("/api/v1/auth/signup", json={
        "name": "Workspace Owner", "workspace_name": "Community Foundation", "email": email,
        "password": PASSWORD, "phone": "+91 9000000000",
    }, headers=HEADERS)
    assert response.status_code == 201, response.text
    return response.json()


def login(client, email="owner@example.test", password=PASSWORD, **extra):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password, **extra}, headers=HEADERS)


def invite(client, role="MEMBER", email="member@example.test"):
    response = client.post("/api/v1/admin/users/invite", headers=HEADERS,
                           json={"name": "Team Member", "email": email, "role": role})
    assert response.status_code == 201, response.text
    return response.json()


def accept(client, invitation):
    response = client.post("/api/v1/auth/accept-invitation", headers=HEADERS,
                           json={"token": invitation["token"], "password": PASSWORD})
    assert response.status_code == 204, response.text


@pytest.mark.parametrize("path", ["/organizations", "/compliances", "/tasks", "/documents", "/memberships",
                                 "/subscription", "/notifications", "/audit-events", "/dashboard", "/admin/users"])
def test_anonymous_requests_cannot_read_workspace(path):
    with TestClient(app) as client:
        assert client.get("/api/v1" + path, headers={"x-tenant-id": "tenant-demo"}).status_code == 401


def test_signup_creates_isolated_admin_and_secure_cookie():
    with TestClient(app) as client:
        owner = signup(client)
        assert owner["role"] == "ADMIN"
        assert owner["tenant_id"] != "tenant-demo"
        assert "password_hash" not in owner
        assert client.get("/api/v1/organizations").json() == []
        assert client.get("/api/v1/auth/me").json()["workspace_name"] == "Community Foundation"
        assert client.get("/api/v1/subscription").json()["user_limit"] == 5
        with SessionLocal() as db:
            user = db.get(User, owner["id"])
            assert PASSWORD not in user.password_hash
            assert verify_password(PASSWORD, user.password_hash)
            raw_token = client.cookies.get(COOKIE_NAME)
            stored = db.get(AuthSession, digest(raw_token))
            assert stored and stored.token_hash != raw_token
        response = login(client, remember=True)
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=lax" in cookie and "max-age=2592000" in cookie
        assert response.headers["cache-control"] == "no-store"


def test_password_hashes_use_unique_salts():
    first, second = hash_password(PASSWORD), hash_password(PASSWORD)
    assert first != second
    assert verify_password(PASSWORD, first)
    assert not verify_password("Incorrect password", first)


def test_validation_does_not_echo_password_and_signup_rejects_extra_role():
    with TestClient(app) as client:
        payload = {"name": "Owner", "workspace_name": "Foundation", "email": "owner@example.test", "password": "short"}
        response = client.post("/api/v1/auth/signup", json=payload, headers=HEADERS)
        assert response.status_code == 422 and '"input"' not in response.text
        payload.update(password=PASSWORD, role="ADMIN")
        assert client.post("/api/v1/auth/signup", json=payload, headers=HEADERS).status_code == 422


@pytest.mark.parametrize("email", [
    "missing-at.example.org", "two@@example.org", ".owner@example.org", "owner..name@example.org",
    "owner@-example.org", "owner@example-.org", "owner@example", "owner@example..org", "owner@example.1",
])
def test_email_validation_rejects_malformed_addresses(email):
    with pytest.raises(ValueError):
        EmailInput(email=email)


def test_email_validation_normalizes_safe_addresses():
    assert EmailInput(email="  Owner.Team+alerts@Example.ORG  ").email == "owner.team+alerts@example.org"
    membership = MembershipCreate(name="Reviewer", email=" Reviewer@Example.ORG ", role="AUDITOR")
    assert membership.email == "reviewer@example.org"


@pytest.mark.parametrize("password", [
    " password-safe-2026", "password-safe-2026 ", "password\nSafe2026", "aaaaaaaaaaaa",
    "Password-1234", "abcdefghijkl", "abcabcabcabc",
])
def test_new_password_validation_rejects_ambiguous_or_predictable_values(password):
    with pytest.raises(ValueError):
        PasswordInput(password=password)


def test_duplicate_email_and_wrong_login():
    with TestClient(app) as client:
        signup(client)
        response = client.post("/api/v1/auth/signup", headers=HEADERS, json={
            "name": "Other Person", "workspace_name": "Other", "email": "OWNER@example.test", "password": PASSWORD,
        })
        assert response.status_code == 409
        wrong = login(client, password="Wrong-password")
        missing = login(client, email="missing@example.test", password="Wrong-password")
        assert wrong.status_code == missing.status_code == 401
        assert wrong.json() == missing.json()


def test_mutations_require_custom_header_and_allowed_origin():
    with TestClient(app) as client:
        signup(client)
        assert client.post("/api/v1/auth/logout").status_code == 403
        assert client.post("/api/v1/auth/logout", headers={"X-Setu-Request": "1", "Origin": "https://attacker.test"}).status_code == 403
        preflight = client.options("/api/v1/auth/logout", headers={"Origin": "https://attacker.test", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "X-Setu-Request"})
        assert preflight.status_code == 400
        assert client.get("/api/v1/auth/me").status_code == 200


def test_logout_revokes_session_and_expired_session_is_rejected():
    with TestClient(app) as client:
        signup(client)
        raw_token = client.cookies.get(COOKIE_NAME)
        assert client.post("/api/v1/auth/logout", headers=HEADERS).status_code == 204
        client.cookies.set(COOKIE_NAME, raw_token)
        assert client.get("/api/v1/auth/me").status_code == 401
        client.cookies.clear()
        assert login(client).status_code == 200
        with SessionLocal() as db:
            session = db.get(AuthSession, digest(client.cookies.get(COOKIE_NAME)))
            session.expires_at = now() - timedelta(seconds=1)
            db.commit()
        assert client.get("/api/v1/auth/me").status_code == 401


def test_tenant_spoofing_and_cross_tenant_user_changes_are_blocked():
    with TestClient(app) as first, TestClient(app) as second:
        owner = signup(first)
        other = signup(second, "other@example.test")
        assert first.get("/api/v1/organizations", headers={"x-tenant-id": other["tenant_id"]}).status_code == 403
        assert first.patch(f"/api/v1/admin/users/{other['id']}", headers=HEADERS, json={"role": "VIEWER", "status": "DISABLED"}).status_code == 404
        assert [user["id"] for user in first.get("/api/v1/admin/users").json()] == [owner["id"]]
        assert first.get("/api/v1/documents/doc-pan/versions").status_code == 404


@pytest.mark.parametrize("role", ["MEMBER", "VIEWER"])
def test_non_admin_permissions_and_invitation_flow(role):
    with TestClient(app) as admin, TestClient(app) as member:
        signup(admin)
        invitation = invite(admin, role)
        assert login(member, "member@example.test").status_code == 401
        accept(member, invitation)
        assert login(member, "member@example.test").status_code == 200
        assert member.get("/api/v1/organizations").status_code == 200
        assert member.get("/api/v1/admin/users").status_code == 403
        assert member.get("/api/v1/memberships").status_code == 403
        assert member.post("/api/v1/admin/users/invite", headers=HEADERS, json={"name": "Escalation", "email": "extra@example.test", "role": "ADMIN"}).status_code == 403
        assert member.post("/api/v1/organizations", headers=HEADERS, json={"name": "Another NGO", "legal_type": "TRUST", "registration_number": "REG123", "generate_compliance_plan": False}).status_code == 403
        if role == "VIEWER":
            assert member.patch("/api/v1/tasks/anything", headers=HEADERS, json={"status": "DONE"}).status_code == 403
        assert login(member, "member@example.test", admin_only=True).status_code == 403
        assert member.post("/api/v1/auth/accept-invitation", headers=HEADERS, json={"token": invitation["token"], "password": NEW_PASSWORD}).status_code == 400


def test_disabling_user_revokes_access_and_self_disable_is_blocked():
    with TestClient(app) as admin, TestClient(app) as member:
        owner = signup(admin)
        invitation = invite(admin)
        accept(member, invitation)
        login(member, "member@example.test")
        assert admin.patch(f"/api/v1/admin/users/{owner['id']}", headers=HEADERS, json={"role": "VIEWER", "status": "DISABLED"}).status_code == 409
        assert admin.patch(f"/api/v1/admin/users/{invitation['user']['id']}", headers=HEADERS, json={"role": "MEMBER", "status": "DISABLED"}).status_code == 200
        assert member.get("/api/v1/auth/me").status_code == 401
        assert login(member, "member@example.test").status_code == 401


def test_invitation_renewal_invalidates_old_link_and_expiry_is_enforced():
    with TestClient(app) as client:
        signup(client)
        invitation = invite(client)
        renewed = client.post(f"/api/v1/admin/users/{invitation['user']['id']}/invitation", headers=HEADERS).json()
        assert client.post("/api/v1/auth/accept-invitation", headers=HEADERS, json={"token": invitation["token"], "password": PASSWORD}).status_code == 400
        with SessionLocal() as db:
            token = db.get(AuthToken, digest(renewed["token"]))
            token.expires_at = now() - timedelta(seconds=1)
            db.commit()
        assert client.post("/api/v1/auth/accept-invitation", headers=HEADERS, json={"token": renewed["token"], "password": PASSWORD}).status_code == 400


def test_change_password_revokes_all_sessions_and_persists_profile():
    with TestClient(app) as first, TestClient(app) as second:
        signup(first)
        login(second)
        result = first.patch("/api/v1/auth/profile", headers=HEADERS, json={"name": "Updated Owner", "phone": "9000000001"})
        assert result.json()["name"] == "Updated Owner"
        assert first.post("/api/v1/auth/change-password", headers=HEADERS, json={"current_password": "Wrong-password", "password": NEW_PASSWORD}).status_code == 400
        assert first.post("/api/v1/auth/change-password", headers=HEADERS, json={"current_password": PASSWORD, "password": NEW_PASSWORD}).status_code == 204
        assert first.get("/api/v1/auth/me").status_code == second.get("/api/v1/auth/me").status_code == 401
        assert login(first).status_code == 401
        assert login(first, password=NEW_PASSWORD).status_code == 200
        assert first.get("/api/v1/auth/me").json()["user"]["phone"] == "9000000001"


def test_password_recovery_requires_mail_configuration(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_FROM", raising=False)
    with TestClient(app) as client:
        signup(client)
        response = client.post("/api/v1/auth/forgot-password", headers=HEADERS, json={"email": "owner@example.test"})
        assert response.status_code == 503
        assert "not configured" in response.json()["detail"]
        assert "token" not in response.json()


def test_reset_link_delivery_single_use_and_session_revocation(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SMTP_FROM", "noreply@example.test")
    with TestClient(app) as client, patch("app.auth.smtplib.SMTP_SSL") as smtp:
        signup(client)
        response = client.post("/api/v1/auth/forgot-password", headers=HEADERS, json={"email": "owner@example.test"})
        assert response.status_code == 200
        message = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
        assert message.get_body(preferencelist=("html",)) is not None
        token = message.get_body(preferencelist=("plain",)).get_content().split("#token=")[1].split()[0]
        assert token not in response.text
        assert client.post("/api/v1/auth/reset-password", headers=HEADERS, json={"token": token, "password": NEW_PASSWORD}).status_code == 204
        assert client.get("/api/v1/auth/me").status_code == 401
        assert client.post("/api/v1/auth/reset-password", headers=HEADERS, json={"token": token, "password": PASSWORD}).status_code == 400
        assert login(client, password=NEW_PASSWORD).status_code == 200


def test_reset_token_cannot_accept_an_invitation():
    with TestClient(app) as client:
        owner = signup(client)
        with SessionLocal() as db:
            token = issue_token(db, db.get(User, owner["id"]), "RESET", 1)
            db.commit()
        assert client.post("/api/v1/auth/accept-invitation", headers=HEADERS, json={"token": token, "password": PASSWORD}).status_code == 400


def test_login_attempts_are_throttled():
    with TestClient(app) as client:
        signup(client)
        for _ in range(10):
            assert login(client, password="Wrong-password").status_code == 401
        response = login(client)
        assert response.status_code == 429 and "Retry-After" in response.headers


def test_accounts_survive_application_restart():
    with TestClient(app) as client:
        owner = signup(client)
    with TestClient(app) as restarted:
        assert login(restarted).status_code == 200
        assert restarted.get("/api/v1/auth/me").json()["user"]["id"] == owner["id"]
