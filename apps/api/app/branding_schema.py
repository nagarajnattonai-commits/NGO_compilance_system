"""Validated configuration, never tenant-supplied HTML/CSS or executable uploads."""
from __future__ import annotations

import re
from typing import Literal, get_args
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .validation import normalize_email
from .schemas import SupportedLocale

AssetType = Literal["PRIMARY_LOGO", "LIGHT_LOGO", "DARK_LOGO", "COMPACT_LOGO", "LOGIN_LOGO", "FAVICON", "LOGIN_BACKGROUND", "REPORT_LOGO"]
ASSET_TYPES = {"PRIMARY_LOGO", "LIGHT_LOGO", "DARK_LOGO", "COMPACT_LOGO", "LOGIN_LOGO", "FAVICON", "LOGIN_BACKGROUND", "REPORT_LOGO"}
LOCALES = set(get_args(SupportedLocale))


class ConfigurationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def plain_text(cls, value):
        if isinstance(value, str):
            if any(ord(char) < 32 and char not in "\n\t" for char in value) or "<" in value or ">" in value:
                raise ValueError("Use plain text without HTML or control characters")
            return value.strip()
        return value


class ThemeTokens(ConfigurationModel):
    primary: str = "#218838"
    secondary: str = "#173d30"
    accent: str = "#0f766e"
    background: str = "#f5f7f9"
    surface: str = "#ffffff"
    text: str = "#243746"
    muted: str = "#657584"
    border: str = "#dce3e8"
    success: str = "#218838"
    warning: str = "#946200"
    error: str = "#b42332"

    @field_validator("*")
    @classmethod
    def hex_color(cls, value: str):
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            raise ValueError("Enter a six-digit HEX color such as #218838")
        return value.lower()


def dark_theme() -> ThemeTokens:
    return ThemeTokens(primary="#78d995", secondary="#0c251a", accent="#5eead4", background="#0b1511", surface="#13231b", text="#e4eee8", muted="#a5b8ac", border="#355144", success="#78d995", warning="#ffd280", error="#ff929c")


class BrandConfiguration(ConfigurationModel):
    brand_name: str = Field(default="Setu NGO", min_length=2, max_length=160)
    product_name: str = Field(default="Setu NGO", min_length=2, max_length=160)
    legal_company_name: str = Field(default="", max_length=200)
    short_name: str = Field(default="Setu", min_length=1, max_length=24)
    tagline: str = Field(default="Compliance and impact management", max_length=200)
    description: str = Field(default="A connected workspace for NGO compliance, evidence and impact.", max_length=600)
    localized_taglines: dict[str, str] = Field(default_factory=dict, max_length=20)
    light: ThemeTokens = Field(default_factory=ThemeTokens)
    dark: ThemeTokens = Field(default_factory=dark_theme)
    preset: Literal["DEFAULT", "PROFESSIONAL", "MINIMAL", "CORPORATE", "CUSTOM"] = "DEFAULT"
    assets: dict[AssetType, str] = Field(default_factory=dict, max_length=8)
    login_background: Literal["SOLID", "IMAGE"] = "SOLID"
    support_email: str = Field(default="", max_length=200)
    support_phone: str = Field(default="", max_length=40)
    support_url: str = Field(default="", max_length=500)
    website_url: str = Field(default="", max_length=500)
    privacy_url: str = Field(default="", max_length=500)
    terms_url: str = Field(default="", max_length=500)
    footer_text: str = Field(default="", max_length=500)
    sender_name: str = Field(default="", max_length=120)
    reply_to: str = Field(default="", max_length=200)
    email_signature: str = Field(default="", max_length=600)
    email_footer: str = Field(default="", max_length=600)
    report_footer: str = Field(default="", max_length=600)
    report_generated_by: bool = True

    @field_validator("support_url", "website_url", "privacy_url", "terms_url")
    @classmethod
    def https_url(cls, value: str):
        if not value:
            return ""
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in {None, 443} or any(char.isspace() for char in value):
            raise ValueError("Use a valid HTTPS URL without credentials")
        return value

    @field_validator("support_email", "reply_to")
    @classmethod
    def email(cls, value: str):
        return normalize_email(value) if value else ""

    @field_validator("sender_name")
    @classmethod
    def email_header(cls, value: str):
        if "\n" in value or "\r" in value:
            raise ValueError("Sender name must be a single line")
        return value

    @field_validator("brand_name", "product_name", "legal_company_name", "short_name", "tagline", "support_phone")
    @classmethod
    def single_line(cls, value: str):
        if "\n" in value or "\r" in value or "\t" in value:
            raise ValueError("Use a single line of plain text")
        return value

    @field_validator("localized_taglines")
    @classmethod
    def translations(cls, values: dict[str, str]):
        if any(locale not in LOCALES or len(text) > 200 or "<" in text or ">" in text or any(ord(c) < 32 for c in text) for locale, text in values.items()):
            raise ValueError("Use a supported locale and plain-text tagline of at most 200 characters")
        return values


class DraftInput(ConfigurationModel):
    expected_revision: int = Field(ge=0)
    configuration: BrandConfiguration


class RevisionInput(ConfigurationModel):
    expected_revision: int = Field(ge=0)


class DomainInput(ConfigurationModel):
    hostname: str = Field(min_length=4, max_length=253)


class EntitlementInput(ConfigurationModel):
    enabled: bool


class PlatformBrandAction(ConfigurationModel):
    action: Literal["SUSPEND", "RESUME", "RESET"]
