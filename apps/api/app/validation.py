from __future__ import annotations

import re


EMAIL_LOCAL = re.compile(r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+$", re.IGNORECASE)
DOMAIN_LABEL = re.compile(r"^[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?$", re.IGNORECASE)
COMMON_PASSWORDS = {
    "123456789012",
    "admin123456",
    "changeme123",
    "letmein12345",
    "ngo123456789",
    "password123",
    "password1234",
    "password12345",
    "password123456",
    "qwerty123456",
    "welcome1234",
}
SEQUENCES = (
    "abcdefghijklmnopqrstuvwxyz",
    "0123456789",
    "qwertyuiopasdfghjklzxcvbnm",
)


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 200 or email.count("@") != 1 or any(ord(char) < 33 or ord(char) == 127 for char in email):
        raise ValueError("Enter a valid email address")
    local, domain = email.rsplit("@", 1)
    if not local or len(local) > 64 or local.startswith(".") or local.endswith(".") or ".." in local:
        raise ValueError("Enter a valid email address")
    if not EMAIL_LOCAL.fullmatch(local):
        raise ValueError("Enter a valid email address")
    if len(domain) > 253 or "." not in domain or domain.startswith(".") or domain.endswith(".") or ".." in domain:
        raise ValueError("Enter a valid email address")
    labels = domain.split(".")
    if any(not DOMAIN_LABEL.fullmatch(label) for label in labels) or len(labels[-1]) < 2 or not labels[-1].isalpha():
        raise ValueError("Enter a valid email address")
    return email


def validate_new_password(value: str) -> str:
    if value != value.strip():
        raise ValueError("Password cannot start or end with spaces")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("Password cannot contain control characters")

    folded = value.casefold()
    compact = re.sub(r"[^a-z0-9]", "", folded)
    if len(set(folded)) < 5:
        raise ValueError("Use at least five different characters")
    if compact in COMMON_PASSWORDS:
        raise ValueError("Choose a less predictable password or passphrase")
    if any(len(compact) >= 8 and (compact in sequence or compact in sequence[::-1]) for sequence in SEQUENCES):
        raise ValueError("Avoid keyboard, alphabetic, or numeric sequences")
    if re.fullmatch(r"(.{1,8})\1{2,}", folded):
        raise ValueError("Avoid repeated words or character patterns")
    return value
