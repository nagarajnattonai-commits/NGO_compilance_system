"""Shared, escaped output templates: localized content + published tenant brand."""
from __future__ import annotations

import html
from datetime import date, datetime, timezone
from typing import Annotated, Literal
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
from .features import can_use_feature
from .models import Compliance, Organization, TenantBranding, TenantDomain, TenantLocale, UserPreference
from .reporting_service import compliance_report_rows, reporting_organizations

Tenant = Annotated[str, Depends(tenant_context)]
router = APIRouter(prefix="/api/v1", dependencies=[Depends(check_mutation)])

CONTENT = {
    "en-IN": {"resetSubject": "Reset your password", "reset": "Use this single-use link within one hour. If you did not request this, ignore this email.", "inviteSubject": "Your workspace invitation", "invite": "You have been invited to your compliance workspace.", "deadlineSubject": "Compliance deadline reminder", "deadline": "Your compliance deadline is approaching.", "report": "Compliance Status Report", "client": "Client NGO", "generated": "Generated", "provider": "Service provider", "code": "Code", "compliance": "Compliance", "deadlineHeader": "Deadline", "status": "Status", "progress": "Progress", "owner": "Owner", "empty": "No compliance records found"},
    "hi-IN": {"resetSubject": "अपना पासवर्ड रीसेट करें", "reset": "एक घंटे के भीतर इस एकल-उपयोग लिंक का उपयोग करें। यदि आपने अनुरोध नहीं किया है, तो इस ईमेल को अनदेखा करें।", "inviteSubject": "आपका कार्यक्षेत्र आमंत्रण", "invite": "आपको अनुपालन कार्यक्षेत्र में आमंत्रित किया गया है।", "deadlineSubject": "अनुपालन समयसीमा अनुस्मारक", "deadline": "आपकी अनुपालन समयसीमा निकट आ रही है।", "report": "अनुपालन स्थिति रिपोर्ट", "client": "ग्राहक एनजीओ", "generated": "निर्मित", "provider": "सेवा प्रदाता", "code": "कोड", "compliance": "अनुपालन", "deadlineHeader": "समयसीमा", "status": "स्थिति", "progress": "प्रगति", "owner": "जिम्मेदार", "empty": "कोई अनुपालन रिकॉर्ड नहीं मिला"},
    "kn-IN": {"resetSubject": "ನಿಮ್ಮ ಪಾಸ್‌ವರ್ಡ್ ಮರುಹೊಂದಿಸಿ", "reset": "ಒಂದು ಗಂಟೆಯೊಳಗೆ ಈ ಏಕ-ಬಳಕೆಯ ಲಿಂಕ್ ಬಳಸಿ. ನೀವು ವಿನಂತಿಸದಿದ್ದರೆ ಈ ಇಮೇಲ್ ನಿರ್ಲಕ್ಷಿಸಿ.", "inviteSubject": "ನಿಮ್ಮ ಕಾರ್ಯಕ್ಷೇತ್ರದ ಆಹ್ವಾನ", "invite": "ನಿಮ್ಮ ಅನುಸರಣೆ ಕಾರ್ಯಕ್ಷೇತ್ರಕ್ಕೆ ನಿಮ್ಮನ್ನು ಆಹ್ವಾನಿಸಲಾಗಿದೆ.", "deadlineSubject": "ಅನುಸರಣೆ ಗಡುವಿನ ನೆನಪಿನ ಸಂದೇಶ", "deadline": "ನಿಮ್ಮ ಅನುಸರಣೆ ಗಡುವು ಸಮೀಪಿಸುತ್ತಿದೆ.", "report": "ಅನುಸರಣೆ ಸ್ಥಿತಿ ವರದಿ", "client": "ಗ್ರಾಹಕ ಎನ್‌ಜಿಒ", "generated": "ರಚಿಸಲಾಗಿದೆ", "provider": "ಸೇವಾ ಪೂರೈಕೆದಾರ", "code": "ಕೋಡ್", "compliance": "ಅನುಸರಣೆ", "deadlineHeader": "ಗಡುವು", "status": "ಸ್ಥಿತಿ", "progress": "ಪ್ರಗತಿ", "owner": "ಜವಾಬ್ದಾರರು", "empty": "ಯಾವುದೇ ಅನುಸರಣೆ ದಾಖಲೆಗಳು ಕಂಡುಬಂದಿಲ್ಲ"},
    "mr-IN": {"resetSubject": "तुमचा पासवर्ड रीसेट करा", "reset": "एका तासाच्या आत ही एकदा वापरण्याची लिंक वापरा. तुम्ही विनंती केली नसल्यास हा ईमेल दुर्लक्षित करा.", "inviteSubject": "तुमचे कार्यक्षेत्र आमंत्रण", "invite": "तुम्हाला अनुपालन कार्यक्षेत्रात आमंत्रित केले आहे.", "deadlineSubject": "अनुपालन मुदत स्मरणपत्र", "deadline": "तुमची अनुपालन मुदत जवळ येत आहे.", "report": "अनुपालन स्थिती अहवाल", "client": "ग्राहक एनजीओ", "generated": "तयार केले", "provider": "सेवा प्रदाता", "code": "कोड", "compliance": "अनुपालन", "deadlineHeader": "मुदत", "status": "स्थिती", "progress": "प्रगती", "owner": "जबाबदार", "empty": "अनुपालन नोंदी आढळल्या नाहीत"},
}
REPORT_FIELDS = {
    "en-IN": {"organization": "Organization", "applicability": "Applicability", "tasks": "Tasks and checklist", "evidence": "Evidence coverage", "workflow": "Review, approval, filing and proof", "completion": "Completion and audit timeline", "completed": "Completed", "open": "Open", "priority": "Priority", "filing": "Filing", "noProof": "No proof file", "required": "required", "optional": "optional", "complianceEvidence": "compliance", "taskEvidence": "task", "filingEvidence": "filing"},
    "hi-IN": {"organization": "संगठन", "applicability": "लागू होने की स्थिति", "tasks": "कार्य और जाँच-सूची", "evidence": "साक्ष्य कवरेज", "workflow": "समीक्षा, अनुमोदन, फाइलिंग और प्रमाण", "completion": "पूर्णता और ऑडिट समयरेखा", "completed": "पूर्ण", "open": "खुला", "priority": "प्राथमिकता", "filing": "फाइलिंग", "noProof": "कोई प्रमाण फ़ाइल नहीं", "required": "आवश्यक", "optional": "वैकल्पिक", "complianceEvidence": "अनुपालन", "taskEvidence": "कार्य", "filingEvidence": "फाइलिंग"},
    "kn-IN": {"organization": "ಸಂಸ್ಥೆ", "applicability": "ಅನ್ವಯಿಸುವಿಕೆ", "tasks": "ಕಾರ್ಯಗಳು ಮತ್ತು ಪರಿಶೀಲನಾ ಪಟ್ಟಿ", "evidence": "ಸಾಕ್ಷ್ಯ ವ್ಯಾಪ್ತಿ", "workflow": "ಪರಿಶೀಲನೆ, ಅನುಮೋದನೆ, ಸಲ್ಲಿಕೆ ಮತ್ತು ಪುರಾವೆ", "completion": "ಪೂರ್ಣತೆ ಮತ್ತು ಆಡಿಟ್ ಕಾಲರೇಖೆ", "completed": "ಪೂರ್ಣಗೊಂಡಿದೆ", "open": "ತೆರೆದಿದೆ", "priority": "ಆದ್ಯತೆ", "filing": "ಸಲ್ಲಿಕೆ", "noProof": "ಪುರಾವೆ ಕಡತವಿಲ್ಲ", "required": "ಅಗತ್ಯ", "optional": "ಐಚ್ಛಿಕ", "complianceEvidence": "ಅನುಸರಣೆ", "taskEvidence": "ಕಾರ್ಯ", "filingEvidence": "ಸಲ್ಲಿಕೆ"},
    "mr-IN": {"organization": "संस्था", "applicability": "लागू स्थिती", "tasks": "कामे आणि तपासणी सूची", "evidence": "पुरावा व्याप्ती", "workflow": "पुनरावलोकन, मंजुरी, दाखल आणि पुरावा", "completion": "पूर्णता आणि ऑडिट कालरेषा", "completed": "पूर्ण", "open": "उघडे", "priority": "प्राधान्य", "filing": "दाखल", "noProof": "पुरावा फाइल नाही", "required": "आवश्यक", "optional": "ऐच्छिक", "complianceEvidence": "अनुपालन", "taskEvidence": "काम", "filingEvidence": "दाखल"},
}
REPORT_DECISIONS = {
    "en-IN": {"review": "Review", "approval": "Approval"},
    "hi-IN": {"review": "समीक्षा", "approval": "अनुमोदन"},
    "kn-IN": {"review": "ಪರಿಶೀಲನೆ", "approval": "ಅನುಮೋದನೆ"},
    "mr-IN": {"review": "पुनरावलोकन", "approval": "मंजुरी"},
}
STATUSES = {
    "en-IN": {"NOT_STARTED": "Not started", "IN_PROGRESS": "In progress", "UNDER_REVIEW": "Under review", "READY_TO_FILE": "Ready to file", "FILED": "Filed", "COMPLETED": "Completed", "ON_HOLD": "On hold", "OVERDUE": "Overdue"},
    "hi-IN": {"NOT_STARTED": "शुरू नहीं हुआ", "IN_PROGRESS": "प्रगति में", "UNDER_REVIEW": "समीक्षा में", "READY_TO_FILE": "दाखिल करने के लिए तैयार", "FILED": "दाखिल", "COMPLETED": "पूर्ण", "ON_HOLD": "रुका हुआ", "OVERDUE": "अतिदेय"},
    "kn-IN": {"NOT_STARTED": "ಆರಂಭವಾಗಿಲ್ಲ", "IN_PROGRESS": "ಪ್ರಗತಿಯಲ್ಲಿದೆ", "UNDER_REVIEW": "ಪರಿಶೀಲನೆಯಲ್ಲಿದೆ", "READY_TO_FILE": "ಸಲ್ಲಿಕೆಗೆ ಸಿದ್ಧ", "FILED": "ಸಲ್ಲಿಸಲಾಗಿದೆ", "COMPLETED": "ಪೂರ್ಣಗೊಂಡಿದೆ", "ON_HOLD": "ತಡೆಹಿಡಿಯಲಾಗಿದೆ", "OVERDUE": "ಬಾಕಿಯಾಗಿದೆ"},
    "mr-IN": {"NOT_STARTED": "सुरू नाही", "IN_PROGRESS": "प्रगतीत", "UNDER_REVIEW": "पुनरावलोकनात", "READY_TO_FILE": "दाखल करण्यास तयार", "FILED": "दाखल", "COMPLETED": "पूर्ण", "ON_HOLD": "स्थगित", "OVERDUE": "मुदत उलटलेली"},
}


# Shared translated closed-state labels.
for _locale, _labels in {'en-IN': {'CANCELLED': 'Cancelled', 'NOT_APPLICABLE': 'Not applicable'}, 'hi-IN': {'CANCELLED': 'रद्द', 'NOT_APPLICABLE': 'लागू नहीं'}, 'kn-IN': {'CANCELLED': 'ರದ್ದಾಗಿದೆ', 'NOT_APPLICABLE': 'ಅನ್ವಯಿಸುವುದಿಲ್ಲ'}, 'mr-IN': {'CANCELLED': 'रद्द', 'NOT_APPLICABLE': 'लागू नाही'}}.items():
    STATUSES[_locale].update(_labels)

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
def compliance_print_report(
    db: DB,
    tenant_id: Tenant,
    user: CurrentUser,
    organization_id: str | None = None,
    locale: str | None = None,
    category: str | None = None,
    status: str | None = None,
    owner: str | None = None,
    priority: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
):
    if not can_use_feature(db, tenant_id, "advanced_reporting"):
        raise HTTPException(403, "UPGRADE_REQUIRED:advanced_reporting")
    organizations = reporting_organizations(db, tenant_id, user, organization_id)
    rows = compliance_report_rows(
        db, tenant_id, user, organization_id=organization_id, category=category,
        status=status, owner=owner, priority=priority, date_from=date_from,
        date_to=date_to, limit=500,
    )
    preference = db.get(UserPreference, user.id)
    locale = output_locale(db, tenant_id, preference.locale if preference and preference.locale else locale)
    content = CONTENT[locale]
    fields = REPORT_FIELDS[locale]
    decisions = REPORT_DECISIONS[locale]
    brand = resolve_tenant_branding(db, tenant_id, locale)
    configuration = output_configuration(db, tenant_id)
    generated = format_datetime(datetime.now(timezone.utc), format="long", tzinfo=ZoneInfo(preference.timezone if preference else "Asia/Kolkata"), locale=locale.replace("-", "_"))
    esc = html.escape
    logo = brand["assets"].get("REPORT_LOGO") or brand["assets"].get("PRIMARY_LOGO")
    logo_html = f'<img src="{esc(logo, quote=True)}" alt="{esc(brand["brand_name"], quote=True)}"/>' if logo else ""
    org_names = ", ".join(org.name for org in organizations)
    markup = f'<!doctype html><html lang="{locale}" dir="ltr"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/><title>{esc(brand["product_name"])} | {esc(content["report"])}</title><style>body{{font:13px system-ui,sans-serif;color:#243746;max-width:1500px;margin:24px auto;padding:24px}}header{{border-bottom:3px solid {brand["light"]["primary"]};padding-bottom:16px}}header img{{max-width:180px;max-height:70px;object-fit:contain}}h1{{font-size:24px}}table{{width:100%;border-collapse:collapse;margin:24px 0}}th,td{{padding:7px;border:1px solid #dce3e8;text-align:start;vertical-align:top;overflow-wrap:anywhere}}th{{background:#f5f7f9}}ul{{margin:0;padding-left:16px}}li{{margin:0 0 4px}}footer{{border-top:1px solid #dce3e8;padding-top:16px;color:#657584}}button{{padding:12px;cursor:pointer}}@page{{size:A4 landscape;margin:12mm}}@media print{{body{{margin:0;padding:0;max-width:none}}.print-actions{{display:none}}thead{{display:table-header-group}}tr{{break-inside:avoid}}footer{{position:running(footer)}}}}@media(max-width:700px){{body{{padding:12px}}.table-wrap{{overflow-x:auto}}table{{min-width:1100px}}}}</style></head><body><div class="print-actions"><button onclick="window.print()">PDF / Print</button></div><header>{logo_html}<p>{esc(content["provider"])}: {esc(brand["brand_name"])}</p><h1>{esc(content["report"])}</h1><p>{esc(fields["organization"])}: {esc(org_names)}</p><p>{esc(content["generated"])}: {esc(generated)}</p></header><div class="table-wrap"><table><thead><tr><th>{esc(fields["organization"])}</th><th>{esc(content["compliance"])}</th><th>{esc(fields["applicability"])} / {esc(content["owner"])} / {esc(content["deadlineHeader"])} / {esc(content["status"])} / {esc(fields["priority"])}</th><th>{esc(fields["tasks"])}</th><th>{esc(fields["evidence"])}</th><th>{esc(fields["workflow"])}</th><th>{esc(fields["completion"])}</th></tr></thead><tbody>'
    for row in rows:
        tasks = [f'{entry["title"]} · {entry["status"]} · {entry["due_date"] or "—"} · {entry["owner"]} · {entry["priority"]}' for entry in row["tasks"]]
        tasks.extend(f'{entry["title"] or entry["task_id"]} · {entry["status"]} · {fields["required"] if entry["required"] else fields["optional"]}' for entry in row["checklist"])
        evidence = [f'{entry["category"]}: {entry["name"]} v{entry["version"]} ({fields.get(entry["source"] + "Evidence", entry["source"])})' for entry in row["evidence"]]
        evidence.extend(f'{entry["document_type"]}: {entry["covered_count"]}/{entry["minimum_count"]}' for entry in row["evidence_coverage"]["requirements"])
        workflow = [f'{decisions["review"]} r{entry["revision"]}: {entry["decision"]} · {entry["submitted_by"]} · {entry["submitted_at"]}' for entry in row["reviews"]]
        workflow.extend(f'{decisions["approval"]} r{entry["revision"]}: {entry["decision"]} · {entry["approved_by"] or entry["requested_by"]} · {entry["decided_at"] or entry["requested_at"]}' for entry in row["approvals"])
        if row["filing"]:
            filing = row["filing"]
            workflow.append(f'{fields["filing"]} {filing["reference"]} · {filing["proof_type"]} · {filing["proof_name"] or fields["noProof"]} · {filing["proof_version"] or "—"} · {filing["filed_at"] or "—"}')
        timeline = [f'{entry["occurred_at"]} · {entry["actor"]} · {entry["action"]}: {entry["summary"]}' for entry in row["audit_timeline"]]
        def listing(values):
            return "<ul>" + "".join(f"<li>{esc(value)}</li>" for value in values) + "</ul>" if values else "—"
        applicability = row["applicability"]
        metadata = f'{row["owner"]}<br/>{format_date(date.fromisoformat(row["deadline"]), format="long", locale=locale.replace("-", "_"))}<br/>{STATUSES.get(locale, {}).get(row["status"]) or STATUSES["en-IN"].get(row["status"]) or row["status"]}<br/>{row["priority"]}'
        completion = f'{format_percent(row["completion"]["progress"] / 100, locale=locale.replace("-", "_"))} · {fields["completed"] if row["completion"]["completed"] else fields["open"]}'
        markup += f'<tr><td>{esc(row["organization_name"])}</td><td>{esc(row["code"])}<br/>{esc(row["title"])}<br/>{esc(row["category"])} · {esc(row["period"])}</td><td>{esc(applicability)}<br/>{metadata}</td><td>{listing(tasks)}</td><td>{listing(evidence)}</td><td>{listing(workflow)}</td><td>{esc(completion)}<br/>{listing(timeline)}</td></tr>'
    if not rows:
        markup += f'<tr><td colspan="7">{esc(content["empty"])}</td></tr>'
    markup += f'</tbody></table></div><footer>{esc(configuration.report_footer or configuration.footer_text or brand["brand_name"])}<br/>{esc(configuration.support_email)} {esc(configuration.support_phone)}'
    if configuration.report_generated_by:
        markup += f'<p>{esc(content["generated"])}: {esc(user.name)}</p>'
    markup += "</footer></body></html>"
    return Response(markup, media_type="text/html", headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; script-src 'unsafe-inline'"})
