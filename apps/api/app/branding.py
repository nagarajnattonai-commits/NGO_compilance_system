"""Tenant-owned white-label configuration extending existing auth/audit conventions."""
from __future__ import annotations
from .auth_policy import is_platform_admin

import copy
import logging
import os
import secrets
from datetime import datetime, timezone
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile
from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from .auth import AdminUser as ExistingAdminUser, CurrentUser, DB, check_mutation, tenant_context
from .brand_domains import active_domain, invalidate_domains, platform_hosts, verify_domain_records
from .brand_storage import BrandStorage, validate_image
from .branding_schema import ASSET_TYPES, BrandConfiguration, DomainInput, DraftInput, EntitlementInput, PlatformBrandAction, RevisionInput
from .features import can_use_feature
from .models import AuditEvent, BrandAsset, BrandingVersion, TenantBranding, TenantDomain, TenantEntitlement, TenantLocale, UserPreference, Workspace
from .permissions import has_permission

Tenant = Annotated[str, Depends(tenant_context)]
router = APIRouter(prefix="/api/v1", dependencies=[Depends(check_mutation)])
logger = logging.getLogger(__name__)


def white_label_admin(user: ExistingAdminUser):
    if not has_permission(user, "white_label.manage"):
        raise HTTPException(403, "White-label management permission is required")
    return user


AdminUser = Annotated[object, Depends(white_label_admin)]


def audit(db, user, action: str, entity_id: str, summary: str, tenant_id: str | None = None):
    db.add(AuditEvent(tenant_id=tenant_id or user.tenant_id, actor_name=user.name, action=action,
                      entity_type="WhiteLabel", entity_id=entity_id, summary=summary[:280]))


def require_feature(db, tenant_id: str):
    if not can_use_feature(db, tenant_id, "white_label"):
        raise HTTPException(403, "White-label configuration is preserved but inactive under the current subscription")


def platform_admin(user: AdminUser):
    allowed = {email.strip().lower() for email in os.getenv("PLATFORM_ADMIN_EMAILS", "").split(",") if email.strip()}
    if not is_platform_admin(user):
        raise HTTPException(403, "Platform administrator access is required")
    return user


PlatformAdmin = Annotated[object, Depends(platform_admin)]


def ensure_branding(db, tenant_id: str) -> TenantBranding:
    state = db.get(TenantBranding, tenant_id)
    if not state:
        state = TenantBranding(tenant_id=tenant_id)
        db.add(state)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            state = db.get(TenantBranding, tenant_id)
    return state


@lru_cache(maxsize=256)
def parsed_configuration(configuration: str) -> dict:
    return BrandConfiguration.model_validate_json(configuration).model_dump()


def version_configuration(db, tenant_id: str, version: int | None) -> BrandConfiguration:
    row = db.scalar(select(BrandingVersion).where(BrandingVersion.tenant_id == tenant_id,
                                                BrandingVersion.version == version)) if version else None
    if row:
        try:
            return BrandConfiguration.model_validate(copy.deepcopy(parsed_configuration(row.configuration)))
        except (ValueError, ValidationError):
            logger.warning("Invalid brand version; platform fallback used")
    return BrandConfiguration()


def contrast(first: str, second: str) -> float:
    def luminance(color):
        values = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        values = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4 for value in values]
        return sum(value * weight for value, weight in zip(values, (.2126, .7152, .0722)))
    light, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (light + .05) / (dark + .05)


def theme_warnings(configuration: BrandConfiguration) -> list[str]:
    warnings = []
    for name in ("light", "dark"):
        theme = getattr(configuration, name)
        if contrast(theme.text, theme.surface) < 4.5 or contrast(theme.text, theme.background) < 4.5:
            warnings.append(f"{name}: text contrast must be at least 4.5:1 on surface and background")
        if contrast(theme.muted, theme.surface) < 4.5:
            warnings.append(f"{name}: muted text contrast must be at least 4.5:1")
        if contrast(theme.primary, theme.surface) < 4.5:
            warnings.append(f"{name}: primary text/accent contrast must be at least 4.5:1 on surface")
    return warnings


def validate_assets(db, tenant_id: str, configuration: BrandConfiguration):
    for asset_type, asset_id in configuration.assets.items():
        asset = db.scalar(select(BrandAsset).where(BrandAsset.id == asset_id, BrandAsset.tenant_id == tenant_id,
                                                  BrandAsset.asset_type == asset_type, BrandAsset.removed_at.is_(None)))
        if not asset:
            raise HTTPException(422, "Brand asset is unavailable in this tenant")
    if configuration.login_background == "IMAGE" and not configuration.assets.get("LOGIN_BACKGROUND"):
        raise HTTPException(422, "Upload a login background before selecting image mode")


def claim_revision(db, state: TenantBranding, expected_revision: int):
    changed = db.execute(update(TenantBranding).where(TenantBranding.tenant_id == state.tenant_id,
                                                     TenantBranding.revision == expected_revision,
                                                     TenantBranding.status != "SUSPENDED")
                         .values(revision=expected_revision + 1, updated_at=datetime.now(timezone.utc)))
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Brand configuration changed or is suspended. Reload before continuing.")
    db.refresh(state)


def create_draft(db, state: TenantBranding, user, configuration: BrandConfiguration, revision: int):
    validate_assets(db, state.tenant_id, configuration)
    claim_revision(db, state, revision)
    version = (db.scalar(select(func.max(BrandingVersion.version)).where(BrandingVersion.tenant_id == state.tenant_id)) or 0) + 1
    row = BrandingVersion(tenant_id=state.tenant_id, version=version,
                          configuration=configuration.model_dump_json(), created_by=user.name)
    db.add(row)
    state.draft_version = version
    state.status = "PUBLISHED" if state.published_version else "DRAFT"
    previous = version_configuration(db, state.tenant_id, state.published_version)
    changed = [key for key, value in configuration.model_dump().items() if previous.model_dump().get(key) != value]
    audit(db, user, "WHITE_LABEL_DRAFT_SAVED", state.tenant_id, f"Saved version {version}; fields: {', '.join(changed)}")
    db.commit()


def asset_output(asset: BrandAsset) -> dict:
    return {"id": asset.id, "asset_type": asset.asset_type, "url": f"/api/v1/white-label/assets/{asset.id}/content",
            "mime_type": asset.mime_type, "file_size": asset.file_size, "width": asset.width, "height": asset.height,
            "created_at": asset.created_at.isoformat()}


def domain_output(domain: TenantDomain) -> dict:
    return {"id": domain.id, "hostname": domain.hostname, "status": domain.status, "ssl_status": domain.ssl_status,
            "is_primary": domain.is_primary, "verification_method": domain.verification_method,
            "platform_suspended": domain.platform_suspended,
            "txt_name": "_setu-verification." + domain.hostname, "txt_value": domain.verification_token,
            "cname_target": os.getenv("WHITE_LABEL_CNAME_TARGET", ""),
            "verified_at": domain.verified_at.isoformat() if domain.verified_at else None,
            "last_checked_at": domain.last_checked_at.isoformat() if domain.last_checked_at else None}


def settings_output(db, state: TenantBranding) -> dict:
    version = state.draft_version or state.published_version
    history = db.scalars(select(BrandingVersion).where(BrandingVersion.tenant_id == state.tenant_id)
                         .order_by(BrandingVersion.version.desc()).limit(30)).all()
    assets = db.scalars(select(BrandAsset).where(BrandAsset.tenant_id == state.tenant_id, BrandAsset.removed_at.is_(None))).all()
    domains = db.scalars(select(TenantDomain).where(TenantDomain.tenant_id == state.tenant_id).order_by(TenantDomain.created_at)).all()
    configuration = version_configuration(db, state.tenant_id, version)
    events = db.scalars(select(AuditEvent).where(AuditEvent.tenant_id == state.tenant_id, AuditEvent.entity_type == "WhiteLabel")
                        .order_by(AuditEvent.created_at.desc()).limit(20)).all()
    return {"status": state.status, "revision": state.revision, "draft_version": state.draft_version,
            "published_version": state.published_version, "entitled": can_use_feature(db, state.tenant_id, "white_label"),
            "configuration": configuration.model_dump(), "warnings": theme_warnings(configuration),
            "assets": [asset_output(asset) for asset in assets], "domains": [domain_output(domain) for domain in domains],
            "audit_events": [{"actor_name": event.actor_name, "action": event.action, "summary": event.summary, "created_at": event.created_at.isoformat()} for event in events],
            "history": [{"version": row.version, "created_by": row.created_by, "created_at": row.created_at.isoformat(),
                         "published_by": row.published_by, "published_at": row.published_at.isoformat() if row.published_at else None}
                        for row in history]}


def resolve_tenant_branding(db, tenant_id: str | None, locale: str = "en-IN") -> dict:
    state = db.get(TenantBranding, tenant_id) if tenant_id else None
    enabled = bool(state and state.status != "SUSPENDED" and state.published_version and can_use_feature(db, tenant_id, "white_label"))
    configuration = version_configuration(db, tenant_id, state.published_version) if enabled else BrandConfiguration()
    default_locale = db.scalar(select(TenantLocale.locale_code).where(TenantLocale.tenant_id == tenant_id,
                                                                      TenantLocale.enabled.is_(True), TenantLocale.is_default.is_(True))) if tenant_id else None
    assets = {}
    for asset_type, asset_id in configuration.assets.items():
        asset = db.scalar(select(BrandAsset).where(BrandAsset.id == asset_id, BrandAsset.tenant_id == tenant_id,
                                                  BrandAsset.removed_at.is_(None)))
        if asset:
            assets[asset_type] = asset_output(asset)["url"]
    return {"enabled": enabled, "version": state.published_version if enabled else 0,
            "brand_name": configuration.brand_name, "product_name": configuration.product_name,
            "short_name": configuration.short_name, "tagline": configuration.localized_taglines.get(locale) or configuration.localized_taglines.get(default_locale) or configuration.tagline,
            "description": configuration.description, "assets": assets,
            "light": configuration.light.model_dump(), "dark": configuration.dark.model_dump(),
            "login_background": configuration.login_background, "support_email": configuration.support_email,
            "support_phone": configuration.support_phone, "support_url": configuration.support_url,
            "website_url": configuration.website_url, "privacy_url": configuration.privacy_url, "terms_url": configuration.terms_url,
            "footer_text": configuration.footer_text, "default_locale": default_locale or "en-IN"}


@router.get("/entitlements")
def entitlements(db: DB, tenant_id: Tenant):
    return {"white_label": can_use_feature(db, tenant_id, "white_label")}


@router.get("/white-label")
def branding_settings(db: DB, tenant_id: Tenant, _: AdminUser):
    return settings_output(db, ensure_branding(db, tenant_id))


@router.get("/white-label/published")
def published_branding(db: DB, tenant_id: Tenant, user: CurrentUser, locale: str = "en-IN"):
    preference = db.get(UserPreference, user.id)
    return resolve_tenant_branding(db, tenant_id, preference.locale if preference and preference.locale else locale)


@router.get("/white-label/public")
def public_branding(db: DB, hostname: str, locale: str = "en-IN"):
    hostname = hostname.lower().rstrip(".")
    if hostname in platform_hosts():
        return resolve_tenant_branding(db, None, locale)
    domain = active_domain(db, hostname)
    if not domain:
        raise HTTPException(404, "Branding is unavailable for this domain")
    return resolve_tenant_branding(db, domain.tenant_id, locale)


@router.get("/white-label/domain-authorization", status_code=204)
def authorize_domain_certificate(domain: str, db: DB):
    """Internal Caddy ask gate: indexed lookup, no DNS/TLS call in a handshake.

    Ownership and CNAME must already have been checked by the tenant's explicit
    verification action. ACME independently verifies control before issuance.
    The deployment proxy blocks public access to this internal endpoint.
    """
    hostname = domain.lower().rstrip(".")
    row = db.scalar(select(TenantDomain).where(TenantDomain.hostname == hostname))
    state = db.get(TenantBranding, row.tenant_id) if row else None
    if not row or row.status not in {"VERIFIED", "ACTIVE"} or not row.routing_verified or not row.verified_at or row.platform_suspended:
        raise HTTPException(403, "Domain is not authorized")
    if (state and state.status == "SUSPENDED") or not can_use_feature(db, row.tenant_id, "white_label"):
        raise HTTPException(403, "Domain is not authorized")
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.patch("/white-label/draft")
def save_draft(payload: DraftInput, db: DB, tenant_id: Tenant, user: AdminUser):
    require_feature(db, tenant_id)
    state = ensure_branding(db, tenant_id)
    create_draft(db, state, user, payload.configuration, payload.expected_revision)
    return settings_output(db, state)


@router.post("/white-label/publish")
def publish(payload: RevisionInput, db: DB, tenant_id: Tenant, user: AdminUser):
    require_feature(db, tenant_id)
    state = ensure_branding(db, tenant_id)
    if not state.draft_version:
        raise HTTPException(409, "Save a draft before publishing")
    configuration = version_configuration(db, tenant_id, state.draft_version)
    validate_assets(db, tenant_id, configuration)
    warnings = theme_warnings(configuration)
    if warnings:
        raise HTTPException(422, "; ".join(warnings))
    claim_revision(db, state, payload.expected_revision)
    row = db.scalar(select(BrandingVersion).where(BrandingVersion.tenant_id == tenant_id, BrandingVersion.version == state.draft_version))
    row.published_by = user.name
    row.published_at = datetime.now(timezone.utc)
    state.published_version = state.draft_version
    state.draft_version = None
    state.status = "PUBLISHED"
    audit(db, user, "WHITE_LABEL_BRANDING_PUBLISHED", tenant_id, f"Published branding version {state.published_version}")
    db.commit()
    invalidate_domains()
    return settings_output(db, state)


@router.post("/white-label/discard")
def discard(payload: RevisionInput, db: DB, tenant_id: Tenant, user: AdminUser):
    require_feature(db, tenant_id)
    state = ensure_branding(db, tenant_id)
    claim_revision(db, state, payload.expected_revision)
    state.draft_version = None
    state.status = "PUBLISHED" if state.published_version else "DISABLED"
    audit(db, user, "WHITE_LABEL_DRAFT_DISCARDED", tenant_id, "Discarded draft; version history retained")
    db.commit()
    return settings_output(db, state)


@router.post("/white-label/reset")
def reset(payload: RevisionInput, db: DB, tenant_id: Tenant, user: AdminUser):
    require_feature(db, tenant_id)
    state = ensure_branding(db, tenant_id)
    create_draft(db, state, user, BrandConfiguration(), payload.expected_revision)
    audit(db, user, "WHITE_LABEL_BRANDING_RESET", tenant_id, "Created default branding draft; active version unchanged")
    db.commit()
    return settings_output(db, state)


@router.get("/white-label/versions/{version}")
def brand_version(version: int, db: DB, tenant_id: Tenant, _: AdminUser):
    row = db.scalar(select(BrandingVersion).where(BrandingVersion.tenant_id == tenant_id, BrandingVersion.version == version))
    if not row:
        raise HTTPException(404, "Branding version not found")
    return version_configuration(db, tenant_id, version)


@router.post("/white-label/assets", status_code=201)
def upload_asset(asset_type: str, file: UploadFile, db: DB, tenant_id: Tenant, user: AdminUser):
    require_feature(db, tenant_id)
    state = ensure_branding(db, tenant_id)
    if state.status == "SUSPENDED":
        raise HTTPException(403, "Branding is suspended")
    if asset_type not in ASSET_TYPES:
        raise HTTPException(422, "Unsupported asset type")
    asset_count = db.scalar(select(func.count()).select_from(BrandAsset).where(BrandAsset.tenant_id == tenant_id, BrandAsset.removed_at.is_(None))) or 0
    if asset_count >= 50:
        raise HTTPException(409, "Remove unused brand assets before uploading more")
    try:
        maximum = 5 * 1024 * 1024 if asset_type == "LOGIN_BACKGROUND" else 2 * 1024 * 1024
        content, width, height, mime_type = validate_image(file.file.read(maximum + 1), file.content_type or "", asset_type)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    finally:
        file.file.close()
    extension = "webp" if mime_type == "image/webp" else "png"
    key = f"{tenant_id}/{secrets.token_hex(24)}.{extension}"
    try:
        BrandStorage().put(key, content, mime_type)
    except Exception as error:
        logger.error("Brand asset storage unavailable")
        raise HTTPException(503, "Brand asset storage is unavailable") from error
    asset = BrandAsset(tenant_id=tenant_id, asset_type=asset_type, storage_key=key, mime_type=mime_type,
                       file_size=len(content), width=width, height=height, created_by=user.name)
    db.add(asset)
    db.flush()
    audit(db, user, "WHITE_LABEL_LOGO_UPLOADED" if asset_type != "LOGIN_BACKGROUND" else "WHITE_LABEL_BACKGROUND_UPLOADED", asset.id, f"Uploaded {asset_type} ({width}x{height})")
    db.commit()
    return asset_output(asset)


@router.get("/white-label/assets/{asset_id}/content")
def asset_content(asset_id: str, request: Request, db: DB):
    asset = db.get(BrandAsset, asset_id)
    if not asset or asset.removed_at:
        raise HTTPException(404, "Brand asset not found")
    state = db.get(TenantBranding, asset.tenant_id)
    configuration = version_configuration(db, asset.tenant_id, state.published_version) if state else BrandConfiguration()
    public = bool(state and state.status != "SUSPENDED" and can_use_feature(db, asset.tenant_id, "white_label") and asset_id in configuration.assets.values())
    if not public:
        from .auth import current_user
        user = current_user(request, db)
        if user.tenant_id != asset.tenant_id or user.role != "ADMIN":
            raise HTTPException(404, "Brand asset not found")
    try:
        return Response(BrandStorage().get(asset.storage_key), media_type=asset.mime_type,
                        headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'", "Cache-Control": "no-store"})
    except Exception as error:
        raise HTTPException(404, "Brand asset is unavailable") from error


@router.delete("/white-label/assets/{asset_id}", status_code=204)
def remove_asset(asset_id: str, db: DB, tenant_id: Tenant, user: AdminUser):
    require_feature(db, tenant_id)
    asset = db.scalar(select(BrandAsset).where(BrandAsset.id == asset_id, BrandAsset.tenant_id == tenant_id, BrandAsset.removed_at.is_(None)))
    if not asset:
        raise HTTPException(404, "Brand asset not found")
    state = ensure_branding(db, tenant_id)
    if asset_id in version_configuration(db, tenant_id, state.published_version).assets.values():
        raise HTTPException(409, "Publish a replacement before removing an active asset")
    asset.removed_at = datetime.now(timezone.utc)
    audit(db, user, "WHITE_LABEL_LOGO_REMOVED", asset.id, f"Removed {asset.asset_type}; immutable history retained")
    db.commit()


@router.get("/white-label/domains")
def domains(db: DB, tenant_id: Tenant, _: AdminUser):
    return [domain_output(domain) for domain in db.scalars(select(TenantDomain).where(TenantDomain.tenant_id == tenant_id)).all()]


@router.post("/white-label/domains", status_code=201)
def add_domain(payload: DomainInput, db: DB, tenant_id: Tenant, user: AdminUser):
    require_feature(db, tenant_id)
    if ensure_branding(db, tenant_id).status == "SUSPENDED":
        raise HTTPException(403, "Branding is suspended")
    from .brand_domains import validate_hostname
    try:
        hostname = validate_hostname(payload.hostname)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    if (db.scalar(select(func.count()).select_from(TenantDomain).where(TenantDomain.tenant_id == tenant_id)) or 0) >= 5:
        raise HTTPException(409, "A maximum of five custom domains is supported")
    if db.scalar(select(TenantDomain.id).where(TenantDomain.hostname == hostname)):
        raise HTTPException(409, "This hostname is already registered")
    domain = TenantDomain(tenant_id=tenant_id, hostname=hostname, verification_token="setu-verify=" + secrets.token_urlsafe(32))
    db.add(domain)
    try:
        db.flush()
        audit(db, user, "WHITE_LABEL_DOMAIN_ADDED", domain.id, f"Added pending domain {hostname}")
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(409, "This hostname is already registered") from error
    invalidate_domains()
    return domain_output(domain)


def own_domain(db, tenant_id: str, domain_id: str) -> TenantDomain:
    domain = db.scalar(select(TenantDomain).where(TenantDomain.id == domain_id, TenantDomain.tenant_id == tenant_id))
    if not domain:
        raise HTTPException(404, "Custom domain not found")
    return domain


@router.post("/white-label/domains/{domain_id}/verify")
def verify_domain(domain_id: str, db: DB, tenant_id: Tenant, user: AdminUser):
    require_feature(db, tenant_id)
    domain = own_domain(db, tenant_id, domain_id)
    if domain.platform_suspended or ensure_branding(db, tenant_id).status == "SUSPENDED":
        raise HTTPException(403, "This domain or branding is suspended by the platform administrator")
    now = datetime.now(timezone.utc)
    previous_check = domain.last_checked_at
    if previous_check and (now - previous_check.replace(tzinfo=timezone.utc)).total_seconds() < 10:
        raise HTTPException(429, "Wait ten seconds before checking DNS again")
    verified, https = verify_domain_records(domain)
    domain.last_checked_at = now
    domain.updated_at = now
    domain.status = "ACTIVE" if https else "VERIFIED" if verified else "FAILED"
    domain.ssl_status = "ACTIVE" if https else "PENDING"
    domain.verified_at = now if verified else None
    if not https:
        domain.is_primary = False
    audit(db, user, "WHITE_LABEL_DOMAIN_VERIFIED" if verified else "WHITE_LABEL_DOMAIN_VERIFICATION_FAILED", domain.id,
          f"Domain {domain.hostname}: {domain.status}; HTTPS {domain.ssl_status}")
    db.commit()
    invalidate_domains()
    return domain_output(domain)


@router.delete("/white-label/domains/{domain_id}", status_code=204)
def delete_domain(domain_id: str, db: DB, tenant_id: Tenant, user: AdminUser):
    require_feature(db, tenant_id)
    domain = own_domain(db, tenant_id, domain_id)
    # Preserve ownership/history to prevent silent re-claiming by another tenant.
    domain.status = "DISABLED"
    domain.is_primary = False
    domain.updated_at = datetime.now(timezone.utc)
    audit(db, user, "WHITE_LABEL_DOMAIN_REMOVED", domain.id, f"Disabled domain {domain.hostname}")
    db.commit()
    invalidate_domains()


@router.post("/white-label/domains/{domain_id}/primary")
def primary_domain(domain_id: str, db: DB, tenant_id: Tenant, user: AdminUser):
    require_feature(db, tenant_id)
    domain = own_domain(db, tenant_id, domain_id)
    if not active_domain(db, domain.hostname):
        raise HTTPException(409, "Verify DNS and HTTPS before selecting a primary domain")
    # Serialize primary changes on the tenant's branding row.
    state = ensure_branding(db, tenant_id)
    db.execute(select(TenantBranding).where(TenantBranding.tenant_id == tenant_id).with_for_update())
    db.execute(update(TenantDomain).where(TenantDomain.tenant_id == tenant_id).values(is_primary=False))
    domain.is_primary = True
    domain.updated_at = datetime.now(timezone.utc)
    state.updated_at = domain.updated_at
    audit(db, user, "WHITE_LABEL_DOMAIN_PRIMARY_CHANGED", domain.id, f"Primary domain: {domain.hostname}")
    db.commit()
    invalidate_domains()
    return domain_output(domain)


@router.get("/platform/white-label/access")
def platform_access(user: CurrentUser):
    allowed = {email.strip().lower() for email in os.getenv("PLATFORM_ADMIN_EMAILS", "").split(",") if email.strip()}
    return {"allowed": user.role == "ADMIN" and is_platform_admin(user)}


@router.get("/platform/white-label")
def platform_brands(db: DB, _: PlatformAdmin):
    states = db.scalars(select(TenantBranding).order_by(TenantBranding.updated_at.desc())).all()
    configured = {state.tenant_id for state in states}
    states = list(states) + [TenantBranding(tenant_id=workspace.id, status="DISABLED", revision=0, draft_version=None, published_version=None)
                            for workspace in db.scalars(select(Workspace)).all() if workspace.id not in configured]
    return [{"tenant_id": state.tenant_id, "workspace_name": (db.get(Workspace, state.tenant_id).name if db.get(Workspace, state.tenant_id) else "Workspace"),
             **settings_output(db, state)} for state in states]


@router.put("/platform/white-label/{tenant_id}/entitlement")
def set_entitlement(tenant_id: str, payload: EntitlementInput, db: DB, user: PlatformAdmin):
    if not db.get(Workspace, tenant_id) and not db.get(TenantBranding, tenant_id):
        raise HTTPException(404, "Workspace not found")
    row = db.scalar(select(TenantEntitlement).where(TenantEntitlement.tenant_id == tenant_id, TenantEntitlement.feature_key == "white_label"))
    if not row:
        row = TenantEntitlement(tenant_id=tenant_id, feature_key="white_label")
        db.add(row)
    row.enabled = payload.enabled
    row.updated_by = user.name
    row.updated_at = datetime.now(timezone.utc)
    audit(db, user, "WHITE_LABEL_ENTITLEMENT_CHANGED", tenant_id, f"white_label enabled={payload.enabled}", tenant_id)
    db.commit()
    invalidate_domains()
    return {"enabled": can_use_feature(db, tenant_id, "white_label")}


@router.post("/platform/white-label/{tenant_id}/action")
def platform_action(tenant_id: str, payload: PlatformBrandAction, db: DB, user: PlatformAdmin):
    state = db.scalar(select(TenantBranding).where(TenantBranding.tenant_id == tenant_id).with_for_update())
    if not state and not db.get(Workspace, tenant_id):
        raise HTTPException(404, "Branding not found")
    state = state or ensure_branding(db, tenant_id)
    state.revision += 1
    state.updated_at = datetime.now(timezone.utc)
    if payload.action == "RESET":
        state.status = "DISABLED"
        state.draft_version = None
        state.published_version = None
    elif payload.action == "SUSPEND":
        state.status = "SUSPENDED"
        db.execute(update(TenantDomain).where(TenantDomain.tenant_id == tenant_id).values(is_primary=False))
    else:
        state.status = "PUBLISHED" if state.published_version else "DRAFT" if state.draft_version else "DISABLED"
    audit(db, user, "WHITE_LABEL_PLATFORM_" + payload.action, tenant_id, f"Platform action {payload.action}; history retained", tenant_id)
    db.commit()
    invalidate_domains()
    return settings_output(db, state)


@router.post("/platform/white-label/{tenant_id}/domains/{domain_id}/suspend")
def suspend_domain(tenant_id: str, domain_id: str, db: DB, user: PlatformAdmin):
    domain = own_domain(db, tenant_id, domain_id)
    domain.status = "DISABLED"
    domain.platform_suspended = True
    domain.is_primary = False
    audit(db, user, "WHITE_LABEL_DOMAIN_SUSPENDED", domain.id, f"Platform suspended {domain.hostname}", tenant_id)
    db.commit()
    invalidate_domains()
    return domain_output(domain)


@router.post("/platform/white-label/{tenant_id}/domains/{domain_id}/resume")
def resume_domain(tenant_id: str, domain_id: str, db: DB, user: PlatformAdmin):
    domain = own_domain(db, tenant_id, domain_id)
    domain.platform_suspended = False
    domain.status = "PENDING"
    domain.ssl_status = "PENDING"
    audit(db, user, "WHITE_LABEL_DOMAIN_RESUMED", domain.id, f"Platform resumed {domain.hostname}; verification required", tenant_id)
    db.commit()
    invalidate_domains()
    return domain_output(domain)
