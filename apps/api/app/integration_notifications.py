"""Notification services call the resolver; business modules never touch credentials."""
import os
import time
from sqlalchemy import select
from .integration_models import ConnectionSettings
from .integration_providers import SMTPAdapter
from .integration_security import IntegrationError
from .integration_service import resolve_integration, log_operation
from .models import IntegrationConnection

def email_available(db):
    return bool(os.getenv("INTEGRATION_LEGACY_EMAIL_FALLBACK","1")=="1" and os.getenv("SMTP_HOST") and os.getenv("SMTP_FROM")) or bool(db.scalar(select(IntegrationConnection.id)
        .join(ConnectionSettings,ConnectionSettings.connection_id==IntegrationConnection.id)
        .where(IntegrationConnection.category=="EMAIL",IntegrationConnection.status=="CONNECTED").limit(1)))

def deliver_email(db,tenant_id,recipient,subject,text,html=None,sender_name="",reply_to=""):
    connection=None
    try:
        connection,state,adapter=resolve_integration(db,tenant_id,"EMAIL","email.send")
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
        adapter.send_email(recipient,subject,text,html,sender_name,reply_to)
    except IntegrationError as error:
        if connection:log_operation(db,connection,"email.send","FAILED",(time.perf_counter()-started)*1000,error.code)
        raise
    if connection:log_operation(db,connection,"email.send","SUCCESS",(time.perf_counter()-started)*1000)
