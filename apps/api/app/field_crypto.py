"""Encryption for identity numbers stored in rows (donor PAN or Aadhaar).

The key comes from SETU_FIELD_ENCRYPTION_KEY (a Fernet key). Production refuses to
start without a valid key (see production_security). Outside production a fixed
development key is used so local data stays readable between restarts; it must
never protect real data.

Rotation: put the new key in SETU_FIELD_ENCRYPTION_KEY and the old keys,
comma-separated, in SETU_FIELD_ENCRYPTION_OLD_KEYS. Old values stay readable;
lookup hashes are derived from the current key, so recompute them after rotating.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

_DEVELOPMENT_KEY = base64.urlsafe_b64encode(hashlib.sha256(b"setu-development-only-field-key").digest())


def valid_key(value: str) -> bool:
    try:
        Fernet(value.encode())
        return True
    except (ValueError, TypeError):
        return False


def _keys() -> list[bytes]:
    current = os.getenv("SETU_FIELD_ENCRYPTION_KEY", "").strip()
    if not current:
        if os.getenv("APP_ENV") == "production":
            raise RuntimeError("SETU_FIELD_ENCRYPTION_KEY is required in production")
        return [_DEVELOPMENT_KEY]
    old = [item.strip() for item in os.getenv("SETU_FIELD_ENCRYPTION_OLD_KEYS", "").split(",") if item.strip()]
    return [key.encode() for key in [current, *old]]


def encrypt(value: str) -> str:
    keys = _keys()
    return Fernet(keys[0]).encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    if not token:
        return ""
    try:
        return MultiFernet([Fernet(key) for key in _keys()]).decrypt(token.encode()).decode()
    except InvalidToken:
        raise RuntimeError("Stored identity number cannot be decrypted with the configured keys") from None


def lookup_hash(value: str) -> str:
    """Keyed hash used only to find duplicates without decrypting every row."""
    key = hmac.new(_keys()[0], b"setu-lookup-v1", hashlib.sha256).digest()
    return hmac.new(key, value.strip().upper().encode(), hashlib.sha256).hexdigest()
