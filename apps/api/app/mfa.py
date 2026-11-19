"""Phase 27 time-based one-time password (TOTP) second factor.

Verification is held per session: a password or Google sign-in creates a session
that can reach only the MFA endpoints until a valid code is entered. Gating at the
session (rather than in each sign-in route) covers every existing sign-in path.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import struct
import time
from datetime import datetime
from typing import Annotated
from urllib.parse import quote

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import Field
from sqlalchemy import BigInteger, DateTime, String, Text, delete, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .database import Base
from .models import AuthSession, User, utcnow

ISSUER = os.getenv("AUTH_MFA_ISSUER", "Setu Compliance")[:40]
STEP_SECONDS = 30
DIGITS = 6
RECOVERY_CODE_COUNT = 10
MFA_PREFIX = "/api/v1/auth/mfa"


class MfaFactor(Base):
    __tablename__ = "auth_mfa_factors"
    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    secret_ciphertext: Mapped[str] = mapped_column(Text)
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_step: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MfaRecoveryCode(Base):
    __tablename__ = "auth_mfa_recovery_codes"
    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MfaSessionVerification(Base):
    # No foreign key: sessions are deleted in several places and must never be blocked by this row.
    __tablename__ = "auth_mfa_session_verifications"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---------- secret protection ----------

def _key() -> bytes | None:
    raw = os.getenv("AUTH_MFA_ENCRYPTION_KEY", "").strip()
    if raw:
        try:
            key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        except ValueError:
            return None
        return key if len(key) == 32 else None
    if os.getenv("APP_ENV") == "production":
        return None  # Fail closed: production secrets need an operator-supplied key.
    return hashlib.sha256(b"setu-development-only-mfa-key").digest()


def mfa_available() -> bool:
    return _key() is not None


def validate_mfa_configuration(environment=None) -> None:
    values = os.environ if environment is None else environment
    if values.get("APP_ENV") != "production":
        return
    raw = values.get("AUTH_MFA_ENCRYPTION_KEY", "").strip()
    if not raw:
        if values.get("AUTH_ADMIN_MFA_REQUIRED") == "1":
            raise RuntimeError("AUTH_ADMIN_MFA_REQUIRED=1 needs AUTH_MFA_ENCRYPTION_KEY")
        return
    try:
        valid = len(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))) == 32
    except ValueError:
        valid = False
    if not valid:
        raise RuntimeError("AUTH_MFA_ENCRYPTION_KEY must be 32 bytes, base64url encoded")


def _seal(secret: str, user_id: str) -> str:
    key = _key()
    if key is None:
        raise HTTPException(503, "Two-step verification is not configured")
    nonce = secrets.token_bytes(12)
    sealed = AESGCM(key).encrypt(nonce, secret.encode(), user_id.encode())
    return base64.urlsafe_b64encode(nonce + sealed).decode()


def _open(ciphertext: str, user_id: str) -> str:
    key = _key()
    if key is None:
        raise HTTPException(503, "Two-step verification is not configured")
    data = base64.urlsafe_b64decode(ciphertext)
    return AESGCM(key).decrypt(data[:12], data[12:], user_id.encode()).decode()


# ---------- RFC 6238 TOTP ----------

def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def totp(secret: str, step: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    mac = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    value = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10 ** DIGITS).zfill(DIGITS)


def matching_step(secret: str, code: str, last_step: int, at: float | None = None) -> int | None:
    """Return the accepted time step, allowing one step of clock drift and refusing replays."""
    code = "".join(ch for ch in code if ch.isdigit())
    if len(code) != DIGITS:
        return None
    current = int((time.time() if at is None else at) // STEP_SECONDS)
    for step in (current - 1, current, current + 1):
        if step > last_step and hmac.compare_digest(totp(secret, step), code):
            return step
    return None


def provisioning_uri(secret: str, email: str) -> str:
    label = quote(f"{ISSUER}:{email}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(ISSUER)}&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}"


# ---------- session gate ----------

def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def enrolled(db: Session, user_id: str) -> bool:
    factor = db.get(MfaFactor, user_id)
    return bool(factor and factor.enabled_at)


def admin_mfa_required(context) -> bool:
    return os.getenv("AUTH_ADMIN_MFA_REQUIRED") == "1" and bool(context and context.audience == "admin")


def session_verified(db: Session, token_hash: str) -> bool:
    return db.get(MfaSessionVerification, token_hash) is not None


def enforce(request: Request, db: Session, user: User, session: AuthSession, context) -> None:
    """Called for every authenticated request. MFA endpoints stay reachable to finish sign-in."""
    if request.url.path.startswith(MFA_PREFIX):
        return
    if enrolled(db, user.id):
        if not session_verified(db, session.token_hash):
            raise HTTPException(401, {"code": "MFA_REQUIRED", "message": "Enter your verification code to continue"})
    elif admin_mfa_required(context):
        raise HTTPException(403, {"code": "MFA_ENROLLMENT_REQUIRED", "message": "Set up two-step verification to use platform administration"})


def mark_verified(db: Session, token_hash: str, user_id: str) -> None:
    if not db.get(MfaSessionVerification, token_hash):
        db.add(MfaSessionVerification(token_hash=token_hash, user_id=user_id))
    # Verifications outlive no session: drop rows for sessions that no longer exist.
    live = select(AuthSession.token_hash)
    db.execute(delete(MfaSessionVerification).where(MfaSessionVerification.user_id == user_id,
                                                    MfaSessionVerification.token_hash.not_in(live),
                                                    MfaSessionVerification.token_hash != token_hash))


def carry_verification(db: Session, old_hash: str, new_hash: str, user_id: str) -> None:
    """Workspace switching rotates the session token; the second factor stays satisfied."""
    if session_verified(db, old_hash):
        mark_verified(db, new_hash, user_id)


# ---------- API ----------

from .auth import (COOKIE_NAME, DB, InputModel, digest, limit_attempts,  # noqa: E402
                   now, record_event, verify_password)


def session_user(request: Request, db: DB) -> tuple[User, AuthSession]:
    """Authenticated session before MFA; only the MFA routes use this directly."""
    from .auth import current_user
    user = current_user(request, db)  # enforce() exempts the MFA prefix
    token = request.cookies.get(COOKIE_NAME, "")
    session = db.get(AuthSession, digest(token))
    return user, session


SessionUser = Annotated[tuple, Depends(session_user)]
router = APIRouter(prefix="/api/v1/auth/mfa")


class CodeInput(InputModel):
    code: str = Field(min_length=6, max_length=20)


class DisableInput(CodeInput):
    password: str = Field(min_length=1, max_length=256)


def _identity(user: User) -> str:
    # User.id is the sign-in identity; workspace switching changes only tenant and role.
    return user.id


def _security(db: Session, request: Request, user: User, event: str) -> None:
    from .auth_experience import security_event
    security_event(db, request, event, user, method="totp")


def _recovery_codes(db: Session, user_id: str) -> list[str]:
    db.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user_id))
    codes = [f"{secrets.token_hex(4)}-{secrets.token_hex(4)}" for _ in range(RECOVERY_CODE_COUNT)]
    for code in codes:
        db.add(MfaRecoveryCode(code_hash=_hash(code), user_id=user_id))
    return codes


def _check_code(db: Session, user_id: str, code: str, allow_recovery: bool) -> str | None:
    factor = db.get(MfaFactor, user_id)
    if not factor or not factor.enabled_at:
        return None
    step = matching_step(_open(factor.secret_ciphertext, user_id), code, factor.last_step or 0)
    if step is not None:
        factor.last_step = step
        return "totp"
    if allow_recovery:
        row = db.get(MfaRecoveryCode, _hash(code.strip().lower()))
        if row and row.user_id == user_id and row.used_at is None:
            row.used_at = now()
            return "recovery"
    return None


@router.get("")
def status(pair: SessionUser, db: DB, response: Response):
    user, session = pair
    identity = _identity(user)
    from .auth_models import SessionContext
    context = db.get(SessionContext, session.token_hash)
    remaining = db.query(MfaRecoveryCode).filter(MfaRecoveryCode.user_id == identity,
                                                 MfaRecoveryCode.used_at.is_(None)).count()
    response.headers["Cache-Control"] = "no-store"
    return {"available": mfa_available(), "enabled": enrolled(db, identity),
            "verified": session_verified(db, session.token_hash),
            "required": admin_mfa_required(context), "recovery_codes_remaining": remaining}


@router.post("/setup")
def setup(pair: SessionUser, db: DB, response: Response):
    user, session = pair
    identity = _identity(user)
    if enrolled(db, identity):
        raise HTTPException(409, "Two-step verification is already on")
    limit_attempts(db, f"mfa-setup:{identity}", 10, 3600)
    secret = new_secret()
    factor = db.get(MfaFactor, identity)
    if factor:
        factor.secret_ciphertext = _seal(secret, identity)
        factor.last_step = 0
    else:
        db.add(MfaFactor(user_id=identity, secret_ciphertext=_seal(secret, identity)))
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return {"secret": secret, "otpauth_uri": provisioning_uri(secret, user.email)}


@router.post("/enable")
def enable(payload: CodeInput, pair: SessionUser, request: Request, db: DB, response: Response):
    user, session = pair
    identity = _identity(user)
    limit_attempts(db, f"mfa-verify:{identity}", 10)
    factor = db.get(MfaFactor, identity)
    if not factor or factor.enabled_at:
        raise HTTPException(409, "Start setup first")
    step = matching_step(_open(factor.secret_ciphertext, identity), payload.code, 0)
    if step is None:
        raise HTTPException(400, "That code is not valid. Check your authenticator app and try again.")
    factor.last_step = step
    factor.enabled_at = now()
    codes = _recovery_codes(db, identity)
    mark_verified(db, session.token_hash, identity)
    _security(db, request, user, "MFA_ENABLED")
    record_event(db, user, "MFA_ENABLED", "Turned on two-step verification", identity)
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return {"recovery_codes": codes}


@router.post("/verify")
def verify(payload: CodeInput, pair: SessionUser, request: Request, db: DB):
    user, session = pair
    identity = _identity(user)
    limit_attempts(db, f"mfa-verify:{identity}", 10)
    method = _check_code(db, identity, payload.code, allow_recovery=True)
    if not method:
        _security(db, request, user, "MFA_FAILED")
        db.commit()
        raise HTTPException(400, "That code is not valid. Check your authenticator app and try again.")
    mark_verified(db, session.token_hash, identity)
    _security(db, request, user, "MFA_RECOVERY_USED" if method == "recovery" else "MFA_VERIFIED")
    db.commit()
    return {"message": "VERIFIED", "method": method}


@router.post("/recovery-codes")
def regenerate(payload: CodeInput, pair: SessionUser, request: Request, db: DB, response: Response):
    user, session = pair
    identity = _identity(user)
    if not session_verified(db, session.token_hash):
        raise HTTPException(401, {"code": "MFA_REQUIRED", "message": "Enter your verification code to continue"})
    limit_attempts(db, f"mfa-verify:{identity}", 10)
    if _check_code(db, identity, payload.code, allow_recovery=False) != "totp":
        raise HTTPException(400, "That code is not valid. Check your authenticator app and try again.")
    codes = _recovery_codes(db, identity)
    _security(db, request, user, "MFA_RECOVERY_REGENERATED")
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return {"recovery_codes": codes}


@router.post("/disable", status_code=204)
def disable(payload: DisableInput, pair: SessionUser, request: Request, db: DB):
    user, session = pair
    identity = _identity(user)
    if not session_verified(db, session.token_hash):
        raise HTTPException(401, {"code": "MFA_REQUIRED", "message": "Enter your verification code to continue"})
    limit_attempts(db, f"mfa-verify:{identity}", 10)
    account = db.get(User, identity)
    # Google-only accounts have no password; the authenticator code alone confirms them.
    if account and account.password_hash and not verify_password(payload.password, account.password_hash):
        raise HTTPException(400, "Password or code is not valid")
    if not _check_code(db, identity, payload.code, allow_recovery=True):
        raise HTTPException(400, "Password or code is not valid")
    db.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == identity))
    db.execute(delete(MfaSessionVerification).where(MfaSessionVerification.user_id == identity))
    db.execute(delete(MfaFactor).where(MfaFactor.user_id == identity))
    _security(db, request, user, "MFA_DISABLED")
    record_event(db, user, "MFA_DISABLED", "Turned off two-step verification", identity)
    db.commit()
