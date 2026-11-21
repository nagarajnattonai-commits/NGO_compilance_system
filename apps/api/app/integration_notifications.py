"""Notification services call the resolver; business modules never touch credentials."""
import html as html_escape
import os
import time
from sqlalchemy import select
from .integration_models import ConnectionSettings
from .integration_providers import SMTPAdapter
from .integration_security import IntegrationError
from .integration_service import resolve_integration, log_operation
from .models import IntegrationConnection

def dev_outbox_dir():
    """Development only: write emails to files instead of sending them. Never honoured in production."""
    if os.getenv("APP_ENV", "development") == "production":
        return None
    return os.getenv("DEV_EMAIL_OUTBOX_DIR", "").strip() or None


def write_dev_outbox(recipient, subject, text, html):
    import re
    from datetime import datetime, timezone
    from pathlib import Path
    folder = Path(dev_outbox_dir())
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", recipient)[:80]
    esc = html_escape.escape
    body = html or "<pre>" + esc(text) + "</pre>"
    header = (f"<p style='font:13px sans-serif;background:#fff6d6;padding:8px'>Development outbox - not sent. "
              f"To: {esc(recipient)} | Subject: {esc(subject)}</p>")
    path = folder / f"{stamp}-{safe}.html"
    path.write_text(header + body, encoding="utf-8")
    return path.name


def email_available(db):
    if dev_outbox_dir():
        return True
    return bool(os.getenv("INTEGRATION_LEGACY_EMAIL_FALLBACK","1")=="1" and os.getenv("SMTP_HOST") and os.getenv("SMTP_FROM")) or bool(db.scalar(select(IntegrationConnection.id)
        .join(ConnectionSettings,ConnectionSettings.connection_id==IntegrationConnection.id)
        .where(IntegrationConnection.category=="EMAIL",IntegrationConnection.status=="CONNECTED").limit(1)))

def deliver_email(db,tenant_id,recipient,subject,text,html=None,sender_name="",reply_to="",organization_id=None,idempotency_key=""):
    if dev_outbox_dir():
        return {"provider_message_id":write_dev_outbox(recipient,subject,text,html),"provider_key":"dev_outbox","connection_id":None}
    connection=None
    try:
        connection,state,adapter=resolve_integration(db,tenant_id,"EMAIL","email.send",organization_id=organization_id)
    except IntegrationError:
        # Backward-compatible platform deployment bridge. Only operators can set these env variables.
        # SMTP_FROM remains verified; a tenant's unavailable integration cannot supply a sender.
        managed_platform=db.scalar(select(IntegrationConnection.id).join(ConnectionSettings,ConnectionSettings.connection_id==IntegrationConnection.id)
            .where(ConnectionSettings.scope=="PLATFORM",IntegrationConnection.category=="EMAIL").limit(1))
        if managed_platform or os.getenv("INTEGRATION_LEGACY_EMAIL_FALLBACK","1")!="1" or not os.getenv("SMTP_HOST") or not os.getenv("SMTP_FROM"):
            raise IntegrationError("INTEGRATION_NOT_CONFIGURED") from None
        adapter=SMTPAdapter({"host":os.environ["SMTP_HOST"],"port":int(os.getenv("SMTP_PORT","465")),
            "username":os.getenv("SMTP_USER",""),"from_address":os.environ["SMTP_FROM"]},os.getenv("SMTP_PASSWORD",""))
    started=time.perf_counter()
    try:
        message_id=adapter.send_email(recipient,subject,text,html,sender_name,reply_to,idempotency_key)
    except IntegrationError as error:
        if connection:log_operation(db,connection,"email.send","FAILED",(time.perf_counter()-started)*1000,error.code)
        raise
    if connection:log_operation(db,connection,"email.send","SUCCESS",(time.perf_counter()-started)*1000)
    return {"provider_message_id":message_id or "","provider_key":connection.provider if connection else "legacy_smtp",
            "connection_id":connection.id if connection else None}

def deliver_whatsapp(db,tenant_id,recipient,text,template="",locale="en-IN",organization_id=None,idempotency_key=""):
    connection,state,adapter=resolve_integration(db,tenant_id,"WHATSAPP","whatsapp.send",organization_id=organization_id)
    started=time.perf_counter()
    try:
        if template:
            message_id=adapter.send_template(recipient,template,locale.replace("-","_"),idempotency_key=idempotency_key)
        else:
            message_id=adapter.send_message(recipient,text,idempotency_key=idempotency_key)
    except IntegrationError as error:
        log_operation(db,connection,"whatsapp.send","FAILED",(time.perf_counter()-started)*1000,error.code)
        raise
    log_operation(db,connection,"whatsapp.send","SUCCESS",(time.perf_counter()-started)*1000)
    return {"provider_message_id":message_id,"provider_key":connection.provider,"connection_id":connection.id}
