"""Shared, escaped output templates: localized content + published tenant brand."""
from __future__ import annotations

import html
from datetime import date, datetime, timezone
from typing import Annotated
from zoneinfo import ZoneInfo

from babel.dates import format_date, format_datetime
from babel.numbers import format_percent
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import Field
from sqlalchemy import select

from .auth import AdminUser, CurrentUser, DB, APP_ORIGIN, check_mutation, tenant_context
from .branding import resolve_tenant_branding, version_configuration
from .branding_schema import ConfigurationModel, BrandConfiguration
from .brand_domains import active_domain
from .models import Compliance, Organization, TenantBranding, TenantDomain, TenantLocale, UserPreference

Tenant = Annotated[str, Depends(tenant_context)]
router = APIRouter(prefix="/api/v1", dependencies=[Depends(check_mutation)])

CONTENT = {
    "en-IN": {"resetSubject": "Reset your password", "reset": "Use this single-use link within one hour. If you did not request this, ignore this email.", "inviteSubject": "Your workspace invitation", "invite": "You have been invited to your compliance workspace.", "deadlineSubject": "Compliance deadline reminder", "deadline": "Your compliance deadline is approaching.", "report": "Compliance Status Report", "client": "Client NGO", "generated": "Generated", "provider": "Service provider", "code": "Code", "compliance": "Compliance", "deadlineHeader": "Deadline", "status": "Status", "progress": "Progress", "owner": "Owner", "empty": "No compliance records found"},
    "hi-IN": {"resetSubject": "अपना पासवर्ड रीसेट करें", "reset": "एक घंटे के भीतर इस एकल-उपयोग लिंक का उपयोग करें। यदि आपने अनुरोध नहीं किया है, तो इस ईमेल को अनदेखा करें।", "inviteSubject": "आपका कार्यक्षेत्र आमंत्रण", "invite": "आपको अनुपालन कार्यक्षेत्र में आमंत्रित किया गया है।", "deadlineSubject": "अनुपालन समयसीमा अनुस्मारक", "deadline": "आपकी अनुपालन समयसीमा निकट आ रही है।", "report": "अनुपालन स्थिति रिपोर्ट", "client": "ग्राहक एनजीओ", "generated": "निर्मित", "provider": "सेवा प्रदाता", "code": "कोड", "compliance": "अनुपालन", "deadlineHeader": "समयसीमा", "status": "स्थिति", "progress": "प्रगति", "owner": "जिम्मेदार", "empty": "कोई अनुपालन रिकॉर्ड नहीं मिला"},
    "kn-IN": {"resetSubject": "ನಿಮ್ಮ ಪಾಸ್‌ವರ್ಡ್ ಮರುಹೊಂದಿಸಿ", "reset": "ಒಂದು ಗಂಟೆಯೊಳಗೆ ಈ ಏಕ-ಬಳಕೆಯ ಲಿಂಕ್ ಬಳಸಿ. ನೀವು ವಿನಂತಿಸದಿದ್ದರೆ ಈ ಇಮೇಲ್ ನಿರ್ಲಕ್ಷಿಸಿ.", "inviteSubject": "ನಿಮ್ಮ ಕಾರ್ಯಕ್ಷೇತ್ರದ ಆಹ್ವಾನ", "invite": "ನಿಮ್ಮ ಅನುಸರಣೆ ಕಾರ್ಯಕ್ಷೇತ್ರಕ್ಕೆ ನಿಮ್ಮನ್ನು ಆಹ್ವಾನಿಸಲಾಗಿದೆ.", "deadlineSubject": "ಅನುಸರಣೆ ಗಡುವಿನ ನೆನಪಿನ ಸಂದೇಶ", "deadline": "ನಿಮ್ಮ ಅನುಸರಣೆ ಗಡುವು ಸಮೀಪಿಸುತ್ತಿದೆ.", "report": "ಅನುಸರಣೆ ಸ್ಥಿತಿ ವರದಿ", "client": "ಗ್ರಾಹಕ ಎನ್‌ಜಿಒ", "generated": "ರಚಿಸಲಾಗಿದೆ", "provider": "ಸೇವಾ ಪೂರೈಕೆದಾರ", "code": "ಕೋಡ್", "compliance": "ಅನುಸರಣೆ", "deadlineHeader": "ಗಡುವು", "status": "ಸ್ಥಿತಿ", "progress": "ಪ್ರಗತಿ", "owner": "ಜವಾಬ್ದಾರರು", "empty": "ಯಾವುದೇ ಅನುಸರಣೆ ದಾಖಲೆಗಳು ಕಂಡುಬಂದಿಲ್ಲ"},
    "mr-IN": {"resetSubject": "तुमचा पासवर्ड रीसेट करा", "reset": "एका तासाच्या आत ही एकदा वापरण्याची लिंक वापरा. तुम्ही विनंती केली नसल्यास हा ईमेल दुर्लक्षित करा.", "inviteSubject": "तुमचे कार्यक्षेत्र आमंत्रण", "invite": "तुम्हाला अनुपालन कार्यक्षेत्रात आमंत्रित केले आहे.", "deadlineSubject": "अनुपालन मुदत स्मरणपत्र", "deadline": "तुमची अनुपालन मुदत जवळ येत आहे.", "report": "अनुपालन स्थिती अहवाल", "client": "ग्राहक एनजीओ", "generated": "तयार केले", "provider": "सेवा प्रदाता", "code": "कोड", "compliance": "अनुपालन", "deadlineHeader": "मुदत", "status": "स्थिती", "progress": "प्रगती", "owner": "जबाबदार", "empty": "अनुपालन नोंदी आढळल्या नाहीत"},
}
STATUSES = {
    "en-IN": {"NOT_STARTED": "Not started", "IN_PROGRESS": "In progress", "UNDER_REVIEW": "Under review", "READY_TO_FILE": "Ready to file", "FILED": "Filed", "COMPLETED": "Completed", "ON_HOLD": "On hold", "OVERDUE": "Overdue"},
    "hi-IN": {"NOT_STARTED": "शुरू नहीं हुआ", "IN_PROGRESS": "प्रगति में", "UNDER_REVIEW": "समीक्षा में", "READY_TO_FILE": "दाखिल करने के लिए तैयार", "FILED": "दाखिल", "COMPLETED": "पूर्ण", "ON_HOLD": "रुका हुआ", "OVERDUE": "अतिदेय"},
    "kn-IN": {"NOT_STARTED": "ಆರಂಭವಾಗಿಲ್ಲ", "IN_PROGRESS": "ಪ್ರಗತಿಯಲ್ಲಿದೆ", "UNDER_REVIEW": "ಪರಿಶೀಲನೆಯಲ್ಲಿದೆ", "READY_TO_FILE": "ಸಲ್ಲಿಕೆಗೆ ಸಿದ್ಧ", "FILED": "ಸಲ್ಲಿಸಲಾಗಿದೆ", "COMPLETED": "ಪೂರ್ಣಗೊಂಡಿದೆ", "ON_HOLD": "ತಡೆಹಿಡಿಯಲಾಗಿದೆ", "OVERDUE": "ಬಾಕಿಯಾಗಿದೆ"},
    "mr-IN": {"NOT_STARTED": "सुरू नाही", "IN_PROGRESS": "प्रगतीत", "UNDER_REVIEW": "पुनरावलोकनात", "READY_TO_FILE": "दाखल करण्यास तयार", "FILED": "दाखल", "COMPLETED": "पूर्ण", "ON_HOLD": "स्थगित", "OVERDUE": "मुदत उलटलेली"},
}


for _locale, _subject, _body in [
    ("en-IN","Verify your email","Use this single-use verification link within 24 hours."),
    ("hi-IN","अपना ईमेल सत्यापित करें","24 घंटे के भीतर इस एकल-उपयोग सत्यापन लिंक का उपयोग करें।"),
    ("kn-IN","ನಿಮ್ಮ ಇಮೇಲ್ ಪರಿಶೀಲಿಸಿ","24 ಗಂಟೆಗಳ ಒಳಗೆ ಈ ಏಕಬಳಕೆಯ ಪರಿಶೀಲನಾ ಲಿಂಕ್ ಬಳಸಿ."),
    ("mr-IN","तुमचा ईमेल पडताळा","24 तासांच्या आत ही एकदाच वापरण्याची पडताळणी लिंक वापरा.")
]:
    CONTENT[_locale].update(verifySubject=_subject,verify=_body)


def output_locale(db, tenant_id: str, requested: str | None) -> str:
    default = db.scalar(select(TenantLocale.locale_code).where(TenantLocale.tenant_id == tenant_id,
                                                              TenantLocale.is_default.is_(True), TenantLocale.enabled.is_(True)))
    return requested if requested in CONTENT else default if default in CONTENT else "en-IN"


def site_origin(db, tenant_id: str) -> str:
    primary = db.scalar(select(TenantDomain).where(TenantDomain.tenant_id == tenant_id, TenantDomain.is_primary.is_(True)))
    return "https://" + primary.hostname if primary and active_domain(db, primary.hostname) else APP_ORIGIN


def output_configuration(db, tenant_id: str):
    state = db.get(TenantBranding, tenant_id)
    brand = resolve_tenant_branding(db, tenant_id)
    return version_configuration(db, tenant_id, state.published_version if state and brand["enabled"] else None)


def render_email(db, tenant_id: str, template_key: str, variables: dict[str, str], locale: str | None = None, platform: bool = False) -> dict:
    locale = output_locale(db, tenant_id, locale)
    content = CONTENT[locale]
    names = {"auth.emailVerification": ("verifySubject", "verify"), "auth.passwordReset": ("resetSubject", "reset"), "auth.invitation": ("inviteSubject", "invite"), "compliance.deadlineReminder": ("deadlineSubject", "deadline")}
    if template_key not in names:
        raise ValueError("Unsupported email template")
    subject_key, body_key = names[template_key]
    brand = resolve_tenant_branding(db, tenant_id, locale)
    if platform:
        brand = resolve_tenant_branding(db, None, locale)
    configuration = BrandConfiguration() if platform else output_configuration(db, tenant_id)
    body = content[body_key]
    detail = variables.get("complianceName", "")
    if variables.get("dueDate"):
        try:
            detail += " — " + format_date(date.fromisoformat(variables["dueDate"]), format="long", locale=locale.replace("-", "_"))
        except ValueError:
            pass
    link = variables.get("link", "")
    # Only application-generated links on an approved origin are renderable.
    if link and not link.startswith((APP_ORIGIN if platform else site_origin(db, tenant_id)) + "/"):
        raise ValueError("Email links must use the authorized application origin")
    footer = configuration.email_footer or configuration.footer_text or brand["brand_name"]
    logo = brand["assets"].get("PRIMARY_LOGO")
    logo_html = f'<img src="{html.escape(site_origin(db, tenant_id) + logo, quote=True)}" alt="{html.escape(brand["brand_name"], quote=True)}" style="max-width:180px;max-height:64px;object-fit:contain" />' if logo else ""
    text = "\n\n".join(part for part in (brand["product_name"], variables.get("userName", ""), body, detail, link, configuration.email_signature, footer, configuration.support_email) if part)
    markup = f'<!doctype html><html lang="{locale}"><body style="margin:0;background:#f5f7f9;font-family:Arial,sans-serif"><main style="max-width:600px;margin:24px auto;padding:28px;background:#fff;border-top:5px solid {brand["light"]["primary"]};color:#243746">{logo_html}<h1>{html.escape(brand["product_name"])}</h1><p>{html.escape(variables.get("userName", ""))}</p><p>{html.escape(body)}</p><p>{html.escape(detail)}</p>'
    if link:
        markup += f'<p><a href="{html.escape(link, quote=True)}">{html.escape(content[subject_key])}</a></p>'
    markup += f'<p>{html.escape(configuration.email_signature)}</p><hr/><footer>{html.escape(footer)}<br/>{html.escape(configuration.support_email)}</footer></main></body></html>'
    return {"subject": f'{brand["product_name"]}: {content[subject_key]}', "text": text, "html": markup,
            "sender_name": configuration.sender_name or brand["brand_name"], "reply_to": configuration.reply_to,
            "locale": locale, "template_key": template_key}


class EmailPreviewInput(ConfigurationModel):
    locale: str = "en-IN"
    template_key: str = "compliance.deadlineReminder"
    variables: dict[str, str] = Field(default_factory=dict, max_length=10)


@router.post("/white-label/email-preview")
def email_preview(payload: EmailPreviewInput, db: DB, tenant_id: Tenant, _: AdminUser):
    try:
        return render_email(db, tenant_id, payload.template_key, payload.variables, payload.locale)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.get("/reports/compliance/print")
def compliance_print_report(db: DB, tenant_id: Tenant, user: CurrentUser, organization_id: str | None = None, locale: str | None = None):
    preference = db.get(UserPreference, user.id)
    locale = output_locale(db, tenant_id, preference.locale if preference and preference.locale else locale)
    content = CONTENT[locale]
    brand = resolve_tenant_branding(db, tenant_id, locale)
    configuration = output_configuration(db, tenant_id)
    orgs = db.scalars(select(Organization).where(Organization.tenant_id == tenant_id)).all()
    names = {org.id: org.name for org in orgs}
    if organization_id and organization_id not in names:
        raise HTTPException(404, "Organization not found")
    query = select(Compliance).where(Compliance.tenant_id == tenant_id)
    if organization_id:
        query = query.where(Compliance.organization_id == organization_id)
    rows = db.scalars(query.order_by(Compliance.statutory_deadline, Compliance.code)).all()
    generated = format_datetime(datetime.now(timezone.utc), format="long", tzinfo=ZoneInfo(preference.timezone if preference else "Asia/Kolkata"), locale=locale.replace("-", "_"))
    esc = html.escape
    logo = brand["assets"].get("REPORT_LOGO") or brand["assets"].get("PRIMARY_LOGO")
    logo_html = f'<img src="{esc(logo, quote=True)}" alt="{esc(brand["brand_name"], quote=True)}"/>' if logo else ""
    markup = f'<!doctype html><html lang="{locale}" dir="ltr"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/><title>{esc(brand["product_name"])} | {esc(content["report"])}</title><style>body{{font:14px system-ui,sans-serif;color:#243746;max-width:1100px;margin:24px auto;padding:24px}}header{{border-bottom:3px solid {brand["light"]["primary"]};padding-bottom:16px}}header img{{max-width:180px;max-height:70px;object-fit:contain}}h1{{font-size:24px}}table{{width:100%;border-collapse:collapse;margin:24px 0}}th,td{{padding:9px;border:1px solid #dce3e8;text-align:start;overflow-wrap:anywhere}}th{{background:#f5f7f9}}footer{{border-top:1px solid #dce3e8;padding-top:16px;color:#657584}}button{{padding:12px;cursor:pointer}}@page{{size:A4 landscape;margin:15mm}}@media print{{body{{margin:0;padding:0;max-width:none}}.print-actions{{display:none}}thead{{display:table-header-group}}tr{{break-inside:avoid}}footer{{position:running(footer)}}}}@media(max-width:600px){{body{{padding:12px}}.table-wrap{{overflow-x:auto}}table{{min-width:800px}}}}</style></head><body><div class="print-actions"><button onclick="window.print()">PDF / Print</button></div><header>{logo_html}<p>{esc(content["provider"])}: {esc(brand["brand_name"])}</p><h1>{esc(content["report"])}</h1><p>{esc(content["client"])}: {esc(names[organization_id]) if organization_id else esc(", ".join(names.values()))}</p><p>{esc(content["generated"])}: {esc(generated)}</p></header><div class="table-wrap"><table><thead><tr>'
    headers = [content[key] for key in ("code", "compliance", "client", "deadlineHeader", "owner", "status", "progress")]
    markup += "".join(f"<th>{esc(header)}</th>" for header in headers) + "</tr></thead><tbody>"
    for row in rows:
        values = [row.code, row.title, names.get(row.organization_id, row.organization_id), format_date(row.statutory_deadline, format="long", locale=locale.replace("-", "_")), row.owner_name, STATUSES.get(locale, {}).get(row.status) or STATUSES["en-IN"].get(row.status) or row.status.replace("_", " ").title(), format_percent(row.progress / 100, locale=locale.replace("-", "_"))]
        markup += "<tr>" + "".join(f"<td>{esc(value)}</td>" for value in values) + "</tr>"
    if not rows:
        markup += f'<tr><td colspan="7">{esc(content["empty"])}</td></tr>'
    markup += f'</tbody></table></div><footer>{esc(configuration.report_footer or configuration.footer_text or brand["brand_name"])}<br/>{esc(configuration.support_email)} {esc(configuration.support_phone)}'
    if configuration.report_generated_by:
        markup += f'<p>{esc(content["generated"])}: {esc(user.name)}</p>'
    markup += "</footer></body></html>"
    return Response(markup, media_type="text/html", headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; script-src 'unsafe-inline'"})
