"""Authentication contracts, identity proofs, admin separation and tenant contexts."""
from datetime import timedelta
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from joserfc import jwt
from joserfc.jwk import RSAKey
from app.main import app
from app.auth import digest,now,issue_token,COOKIE_NAME,verify_password
from app.auth_models import AuthAccount,SessionContext,OAuthPolicy,ProviderIdentity,PendingGoogleIdentity,OAuthFlow,AuthSecurityEvent,WorkspaceAccess
from app.database import SessionLocal
from app.models import User,AuthSession,AuthToken
from app.auth_oauth import validate_identity
from app.auth_admin import grant

PASSWORD="Authentication-testing-passphrase-2026!"
HEADERS={"X-Setu-Request":"1"}
def signup(client,email="auth-owner@example.test",**extras):
    return client.post("/api/v1/auth/signup",headers=HEADERS,json={
      "name":"Auth Owner","workspace_name":"Auth Workspace","email":email,"password":PASSWORD,**extras})
def login(client,email="auth-owner@example.test",admin=False,**extras):
    return client.post("/api/v1/"+("admin/auth/login" if admin else "auth/login"),headers=HEADERS,json={"email":email,"password":PASSWORD,**extras})
def token(email,purpose):
    with SessionLocal() as db:
        user=db.scalar(select(User).where(User.email==email))
        result=issue_token(db,user,purpose,1);db.commit();return result

@pytest.fixture
def email_delivery(monkeypatch):
    monkeypatch.setattr("app.integration_notifications.email_available",lambda db:True)
    monkeypatch.setattr("app.auth_experience.email_available",lambda db:True)
    captured=[]
    monkeypatch.setattr("app.auth_experience.deliver_email",lambda *args:captured.append(args))
    monkeypatch.setattr("app.integration_notifications.deliver_email",lambda *args:captured.append(args))
    return captured

def test_verified_signup_never_issues_session_or_platform_access(email_delivery,monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_EMAILS","auth-owner@example.test")
    with TestClient(app) as client:
        response=signup(client,verify_email=True,organization_type="TRUST",terms_accepted=True)
        assert response.status_code==201 and not client.cookies.get(COOKIE_NAME)
        assert "password" not in response.json()
        assert email_delivery and "/verify-email#token=" in email_delivery[0][4]
        assert login(client).status_code==403
        link=token("auth-owner@example.test","VERIFY")
        assert client.post("/api/v1/auth/verify-email",headers=HEADERS,json={"token":link}).status_code==200
        assert client.post("/api/v1/auth/verify-email",headers=HEADERS,json={"token":link}).status_code==400
        assert login(client).status_code==200
        assert login(client,admin=True).status_code==403
        assert client.get("/api/v1/admin/compliance-master/access").json()["allowed"] is False
        with SessionLocal() as db:
            account=db.scalar(select(AuthAccount));assert account.verified and not account.platform_access and account.terms_at

@pytest.mark.parametrize("extra",[{"terms_accepted":False,"organization_type":"TRUST"},{"terms_accepted":True},{"terms_accepted":True,"organization_type":"FAKE"}])
def test_signup_requires_valid_organization_and_terms(email_delivery,extra):
    with TestClient(app) as client:assert signup(client,verify_email=True,**extra).status_code==422

def test_operator_admin_session_and_logout(monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_EMAILS","auth-owner@example.test")
    with TestClient(app) as client:
        assert signup(client).status_code==201
        with SessionLocal() as db:grant(db,"auth-owner@example.test")
        assert client.get("/api/v1/admin/auth/access").json()["allowed"] is False
        assert login(client,admin=True,remember=True).status_code==200
        assert client.get("/api/v1/admin/auth/access").json()["allowed"] is True
        assert client.get("/api/v1/admin/compliance-master/access").json()["allowed"] is True
        assert client.get("/api/v1/admin/auth/access",headers={"X-Setu-Host":"portal.unverified.org","X-Setu-Proxy-Key":"setu-development-proxy"}).status_code==403
        assert client.post("/api/v1/auth/logout",headers=HEADERS).status_code==204
        assert client.get("/api/v1/admin/auth/access").status_code==401

def test_admin_recovery_is_generic_and_admin_tokens_cannot_reset_user_flow(email_delivery,monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_EMAILS","auth-owner@example.test")
    with TestClient(app) as client:
        signup(client)
        with SessionLocal() as db:grant(db,"auth-owner@example.test")
        known=client.post("/api/v1/admin/auth/forgot-password",headers=HEADERS,json={"email":"auth-owner@example.test"})
        unknown=client.post("/api/v1/admin/auth/forgot-password",headers=HEADERS,json={"email":"missing@example.test"})
        assert known.json()==unknown.json()
        link=token("auth-owner@example.test","ADMIN_RESET")
        assert client.post("/api/v1/auth/reset-password",headers=HEADERS,json={"token":link,"password":PASSWORD+"new"}).status_code==400
        assert client.post("/api/v1/admin/auth/reset-password",headers=HEADERS,json={"token":link,"password":PASSWORD+"new"}).status_code==204
        assert client.get("/api/v1/auth/me").status_code==401

def test_verification_expiry_resend_and_no_account_enumeration(email_delivery):
    with TestClient(app) as client:
        signup(client,verify_email=True,organization_type="SOCIETY",terms_accepted=True)
        known=client.post("/api/v1/auth/resend-verification",headers=HEADERS,json={"email":"auth-owner@example.test"})
        unknown=client.post("/api/v1/auth/resend-verification",headers=HEADERS,json={"email":"missing@example.test"})
        assert known.json()==unknown.json()
        link=token("auth-owner@example.test","VERIFY")
        with SessionLocal() as db:
            db.get(AuthToken,digest(link)).expires_at=now()-timedelta(seconds=1);db.commit()
        assert client.post("/api/v1/auth/verify-email",headers=HEADERS,json={"token":link}).status_code==400

def test_change_unverified_email_requires_password_and_invalidates_old_link(email_delivery):
    with TestClient(app) as client:
        signup(client,verify_email=True,organization_type="TRUST",terms_accepted=True)
        old=token("auth-owner@example.test","VERIFY")
        data={"email":"auth-owner@example.test","new_email":"corrected@example.test","password":"wrong"}
        assert client.post("/api/v1/auth/change-unverified-email",headers=HEADERS,json=data).status_code==401
        data["password"]=PASSWORD
        assert client.post("/api/v1/auth/change-unverified-email",headers=HEADERS,json=data).status_code==200
        assert client.post("/api/v1/auth/verify-email",headers=HEADERS,json={"token":old}).status_code==400

def test_existing_user_invitation_creates_membership_without_identity_or_password_change():
    with TestClient(app) as first,TestClient(app) as second:
        owner=signup(first).json();other=signup(second,"other-auth@example.test").json()
        invitation=first.post("/api/v1/admin/users/invite",headers=HEADERS,json={"name":"Existing colleague","email":"other-auth@example.test","role":"VIEWER"}).json()
        payload={"token":invitation["token"],"password":PASSWORD}
        assert second.post("/api/v1/auth/accept-invitation",headers=HEADERS,json=payload).status_code==400
        assert second.post("/api/v1/auth/accept-workspace-invitation",headers=HEADERS,json=payload).status_code==200
        me=second.get("/api/v1/auth/me").json()["user"]
        assert me["tenant_id"]==owner["tenant_id"] and me["role"]=="VIEWER"
        assert second.post("/api/v1/organizations",headers=HEADERS,json={}).status_code==403
        assert {row["id"] for row in second.get("/api/v1/auth/workspaces").json()}=={owner["tenant_id"],other["tenant_id"]}
        assert login(second,"other-auth@example.test",remember=True).status_code==200
        switched=second.post("/api/v1/auth/workspace",headers=HEADERS,json={"tenant_id":owner["tenant_id"]})
        assert switched.status_code==200 and "Max-Age=" in switched.headers["set-cookie"]
        assert second.post("/api/v1/auth/workspace",headers=HEADERS,json={"tenant_id":"forged"}).status_code==403
        assert second.post("/api/v1/auth/workspace",headers=HEADERS,json={"tenant_id":other["tenant_id"]}).status_code==200
        assert second.get("/api/v1/auth/me").json()["user"]["role"]=="ADMIN"
        with SessionLocal() as db:
            identity=db.get(User,other["id"]);assert identity.tenant_id==other["tenant_id"] and verify_password(PASSWORD,identity.password_hash)
            assert len(db.scalars(select(User)).all())==2

def test_session_management_is_owner_scoped_and_logs_never_expose_ip_or_tokens():
    with TestClient(app) as first,TestClient(app) as second:
        signup(first);signup(second,"other-auth@example.test")
        row=first.get("/api/v1/auth/sessions").json()[0]
        assert second.delete("/api/v1/auth/sessions/"+row["id"],headers=HEADERS).status_code==404
        assert first.delete("/api/v1/auth/sessions/"+row["id"],headers=HEADERS).status_code==204
        assert first.get("/api/v1/auth/me").status_code==401
        login(first)
        assert "ip_hash" not in str(first.get("/api/v1/auth/security-events").json())
        assert PASSWORD not in str(first.get("/api/v1/auth/security-events").json())

@pytest.mark.parametrize("changes",[{"iss":"https://attacker.org"},{"aud":"other-client"},{"nonce":"wrong"},{"email_verified":False},{"exp":1},{"azp":"other-client"}])
def test_google_oidc_rejects_signed_invalid_claims(monkeypatch,changes):
    key=RSAKey.generate_key(2048);key.ensure_kid()
    mock=MagicMock();mock.__enter__.return_value=mock;mock.get.return_value.json.return_value={"keys":[key.as_dict(private=False)]}
    monkeypatch.setattr("app.auth_oauth.requests.Session",lambda:mock)
    row=OAuthPolicy(client_id="qa-client")
    claims={"iss":"https://accounts.google.com","aud":"qa-client","sub":"qa-subject","iat":int(now().timestamp()),"exp":int(now().timestamp())+600,"nonce":"qa-nonce","email":"owner@gmail.com","email_verified":True,**changes}
    encoded=jwt.encode({"alg":"RS256","kid":key.kid},claims,key)
    with pytest.raises(Exception):validate_identity(encoded,row,"qa-nonce")

def test_google_oidc_validates_real_signature_and_verified_claims(monkeypatch):
    key=RSAKey.generate_key(2048);key.ensure_kid()
    mock=MagicMock();mock.__enter__.return_value=mock;mock.get.return_value.json.return_value={"keys":[key.as_dict(private=False)]}
    monkeypatch.setattr("app.auth_oauth.requests.Session",lambda:mock)
    claims={"iss":"https://accounts.google.com","aud":"qa-client","sub":"qa-subject","iat":int(now().timestamp()),"exp":int(now().timestamp())+600,"nonce":"qa-nonce","email":"OWNER@gmail.com","email_verified":True}
    encoded=jwt.encode({"alg":"RS256","kid":key.kid},claims,key)
    assert validate_identity(encoded,OAuthPolicy(client_id="qa-client"),"qa-nonce")["email"]=="owner@gmail.com"
    wrong=RSAKey.generate_key(2048);wrong.ensure_kid()
    with pytest.raises(Exception):validate_identity(jwt.encode({"alg":"RS256","kid":wrong.kid},claims,wrong),OAuthPolicy(client_id="qa-client"),"qa-nonce")

def test_google_state_binding_provider_cancellation_and_replay(monkeypatch):
    with TestClient(app) as client:
        with SessionLocal() as db:
            db.add(OAuthPolicy(provider="google",client_id="qa-client",secret_ref="env://test",user_enabled=True));db.commit()
        session=MagicMock();session.create_authorization_url.return_value=("https://accounts.google.com/o/oauth2/v2/auth",None)
        monkeypatch.setattr("app.auth_oauth.client",lambda row:session)
        assert client.get("/api/v1/auth/google",follow_redirects=False).status_code==303
        with SessionLocal() as db:
            flow=db.scalar(select(OAuthFlow));flow.state_hash=digest("test-state");db.commit()
        client.cookies.clear()
        assert client.get("/api/v1/auth/google/callback?state=test-state&error=access_denied",follow_redirects=False).status_code==400
        # Rebind a known browser for the cancellation/replay test.
        with SessionLocal() as db:flow=db.scalar(select(OAuthFlow));flow.browser_hash=digest("qa-browser");db.commit()
        client.cookies.set("setu_oauth_browser","qa-browser",path="/api/v1/auth/google")
        assert client.get("/api/v1/auth/google/callback?state=test-state&error=access_denied",follow_redirects=False).status_code==303
        assert client.get("/api/v1/auth/google/callback?state=test-state&error=access_denied",follow_redirects=False).status_code==400

def test_google_signup_collects_organization_and_never_provisions_platform(monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_EMAILS","new-google@gmail.com")
    with TestClient(app) as client:
        with SessionLocal() as db:
            db.add(OAuthPolicy(provider="google",client_id="qa-client",secret_ref="env://test",signup_enabled=True))
            db.add(PendingGoogleIdentity(token_hash=digest("g"*43),email="new-google@gmail.com",subject="qa-google",name="QA",expires_at=now()+timedelta(minutes=10)));db.commit()
        payload={"token":"g"*43,"name":"Google User","workspace_name":"Google Trust","organization_type":"TRUST","terms_accepted":True}
        assert client.post("/api/v1/auth/google/signup",headers=HEADERS,json=payload).status_code==201
        assert client.get("/api/v1/auth/me").status_code==200
        assert client.get("/api/v1/admin/auth/access").json()["allowed"] is False
        assert client.post("/api/v1/auth/google/signup",headers=HEADERS,json=payload).status_code==400

def test_admin_mfa_policy_fails_closed_until_provider_exists(monkeypatch):
    monkeypatch.setenv("AUTH_ADMIN_MFA_REQUIRED","1");monkeypatch.setenv("PLATFORM_ADMIN_EMAILS","auth-owner@example.test")
    with TestClient(app) as client:
        signup(client)
        with SessionLocal() as db:grant(db,"auth-owner@example.test")
        assert login(client,admin=True).status_code==503
        assert login(client).status_code==200

def test_verification_resend_is_rate_limited(email_delivery):
    with TestClient(app) as client:
        for _ in range(3):assert client.post("/api/v1/auth/resend-verification",headers=HEADERS,json={"email":"missing@example.test"}).status_code==200
        assert client.post("/api/v1/auth/resend-verification",headers=HEADERS,json={"email":"missing@example.test"}).status_code==429


def test_real_authlib_pkce_and_google_callback_resolves_verified_existing_identity(monkeypatch):
    from urllib.parse import urlsplit,parse_qs
    from authlib.integrations.requests_client import OAuth2Session
    monkeypatch.setenv("SETU_SECRET_"+"A"*32,"dummy-server-secret")
    key=RSAKey.generate_key(2048);key.ensure_kid()
    with TestClient(app) as client:
        signup(client,"verified-google@gmail.com")
        with SessionLocal() as db:
            db.add(OAuthPolicy(provider="google",client_id="qa-client",secret_ref="env://SETU_SECRET_"+"A"*32,user_enabled=True));db.commit()
        result=client.get("/api/v1/auth/google",follow_redirects=False)
        assert result.status_code==303
        query=parse_qs(urlsplit(result.headers["location"]).query)
        assert query["code_challenge_method"]==["S256"] and query["scope"]==["openid email profile"]
        state=query["state"][0]
        with SessionLocal() as db:nonce=db.get(OAuthFlow,digest(state)).nonce
        claims={"iss":"https://accounts.google.com","aud":"qa-client","sub":"verified-subject","iat":int(now().timestamp()),"exp":int(now().timestamp())+600,
                "nonce":nonce,"email":"verified-google@gmail.com","email_verified":True}
        encoded=jwt.encode({"alg":"RS256","kid":key.kid},claims,key)
        monkeypatch.setattr(OAuth2Session,"fetch_token",lambda *args,**kwargs:{"id_token":encoded})
        transport=MagicMock();transport.__enter__.return_value=transport;transport.get.return_value.json.return_value={"keys":[key.as_dict(private=False)]}
        monkeypatch.setattr("app.auth_oauth.requests.Session",lambda:transport)
        result=client.get("/api/v1/auth/google/callback",params={"state":state,"code":"dummy-code"},follow_redirects=False)
        assert result.status_code==303 and result.headers["location"]=="/dashboard"
        assert client.get("/api/v1/auth/me").json()["user"]["email"]=="verified-google@gmail.com"
        with SessionLocal() as db:
            assert db.scalar(select(ProviderIdentity)).subject=="verified-subject"
            assert db.scalar(select(AuthSecurityEvent).where(AuthSecurityEvent.event=="GOOGLE_LOGIN"))
        assert client.get("/api/v1/auth/google/callback",params={"state":state,"code":"dummy-code"},follow_redirects=False).status_code==400

def test_suspended_workspace_and_revoked_membership_cannot_use_sessions():
    from app.models import Subscription
    with TestClient(app) as first:
        owner=signup(first).json()
        with SessionLocal() as db:
            db.scalar(select(Subscription).where(Subscription.tenant_id==owner["tenant_id"])).status="SUSPENDED";db.commit()
        assert first.get("/api/v1/auth/me").status_code==403
        assert login(first).status_code==403

def test_additive_migration_preserves_existing_identity_and_columns():
    from sqlalchemy import create_engine, inspect
    from app.migrate_auth import apply, NAMES, VERSION
    from app.integration_models import IntegrationSchemaVersion
    target=create_engine("sqlite:///:memory:")
    with target.begin() as connection:
        for name in ("workspaces","auth_users","auth_sessions","auth_tokens"):
            from app.database import Base
            Base.metadata.tables[name].create(connection)
        connection.execute(User.__table__.insert().values(id="migration-user",tenant_id="legacy",email="legacy@example.test",name="Legacy",role="ADMIN",status="ACTIVE"))
    def columns():
        return [{**column,"type":str(column["type"])} for column in inspect(target).get_columns("auth_users")]
    before=columns()
    assert apply(target)==sorted(NAMES)
    assert apply(target)==sorted(NAMES)
    assert columns()==before
    with target.connect() as connection:
        assert connection.execute(select(User.__table__.c.email)).scalar_one()=="legacy@example.test"
        assert len(connection.execute(IntegrationSchemaVersion.__table__.select().where(IntegrationSchemaVersion.version==VERSION)).all())==1
    target.dispose()
