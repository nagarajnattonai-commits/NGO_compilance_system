"""Provider-specific behavior lives here, never in UI or compliance modules."""
import json
import os
import re
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol
from urllib.parse import quote
from pydantic import BaseModel, ConfigDict, Field
from .integration_security import IntegrationError, safe_http, require_success

class Configuration(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

class SMTPConfiguration(Configuration):
    host: str = Field(pattern=r"^[a-zA-Z0-9.-]{1,253}$")
    port: int = Field(default=465, ge=465, le=465)
    username: str = Field(min_length=1,max_length=200)
    from_address: str = Field(pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$",max_length=200)

class WhatsAppConfiguration(Configuration):
    phone_number_id: str = Field(pattern=r"^[0-9]{1,40}$")
    business_account_id: str = Field(pattern=r"^[0-9]{1,40}$")
    api_version: str = Field(pattern=r"^v[0-9]{1,2}\.0$")

class CalendarConfiguration(Configuration):
    calendar_id: str = Field(min_length=1,max_length=200)

class S3Configuration(Configuration):
    bucket: str = Field(pattern=r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
    region: str = Field(pattern=r"^[a-z]{2}(?:-[a-z]+){1,3}-[0-9]$")
    prefix: str = Field(default="",max_length=200,pattern=r"^[A-Za-z0-9/_-]*$")

class Provider(Protocol):
    def test_connection(self) -> None: ...
    def get_health(self) -> str: ...

class EmailProvider(Provider, Protocol):
    def send_email(self,recipient,subject,text,html=None,sender_name="",reply_to=""): ...
class WhatsAppProvider(Provider, Protocol):
    def send_message(self,recipient,text): ...
    def send_template(self,recipient,template,language,components=None): ...
class CalendarProvider(Provider, Protocol):
    def create_event(self,event_id,payload): ...
    def update_event(self,event_id,payload): ...
    def cancel_event(self,event_id): ...
class StorageProvider(Provider, Protocol):
    def upload(self,key,data): ...
    def download(self,key): ...
    def delete(self,key): ...

class BaseAdapter:
    def __init__(self, configuration, secret):
        self.config,self.secret = configuration,secret
    def get_health(self):
        self.test_connection()
        return "OPERATIONAL"

class SMTPAdapter(BaseAdapter):
    def _client(self):
        # SMTP is restricted to deployment-approved hosts; prevent tenant SSRF.
        approved = {value.strip().lower() for value in os.getenv("INTEGRATION_SMTP_HOSTS","").split(",") if value.strip()}
        if os.getenv("SMTP_HOST"):approved.add(os.environ["SMTP_HOST"].lower())
        if self.config["host"].lower() not in approved:
            raise IntegrationError("INVALID_CONFIGURATION")
        return smtplib.SMTP_SSL(self.config["host"],self.config.get("port",465),timeout=10,context=ssl.create_default_context())
    def test_connection(self):
        try:
            with self._client() as client:
                if self.config["username"]:client.login(self.config["username"],self.secret)
                code,_ = client.noop()
                if code != 250:
                    raise IntegrationError("PROVIDER_UNAVAILABLE")
        except smtplib.SMTPAuthenticationError:
            raise IntegrationError("AUTHENTICATION_FAILED") from None
        except (OSError,smtplib.SMTPException):
            raise IntegrationError("PROVIDER_UNAVAILABLE") from None
    def send_email(self, recipient, subject, text, html=None, sender_name="", reply_to=""):
        from email.utils import formataddr
        message = EmailMessage()
        message["From"] = formataddr((sender_name,self.config["from_address"]))
        message["To"],message["Subject"] = recipient,subject
        if reply_to:
            message["Reply-To"] = reply_to
        message.set_content(text)
        if html:
            message.add_alternative(html,subtype="html")
        try:
            with self._client() as client:
                if self.config["username"]:client.login(self.config["username"],self.secret)
                client.send_message(message)
        except smtplib.SMTPAuthenticationError:
            raise IntegrationError("AUTHENTICATION_FAILED") from None
        except (OSError,smtplib.SMTPException):
            raise IntegrationError("PROVIDER_UNAVAILABLE") from None

class WhatsAppAdapter(BaseAdapter):
    def _url(self):
        return "https://graph.facebook.com/" + self.config["api_version"] + "/" + self.config["phone_number_id"]
    def test_connection(self):
        require_success(*safe_http(self._url(),headers={"Authorization":"Bearer "+self.secret}))
    def send_template(self, recipient, template, language, components=None):
        payload = {"messaging_product":"whatsapp","to":recipient,"type":"template",
                   "template":{"name":template,"language":{"code":language},"components":components or []}}
        require_success(*safe_http(self._url()+"/messages","POST",{"Authorization":"Bearer "+self.secret,"Content-Type":"application/json"},json.dumps(payload).encode()))
    def send_message(self, recipient, text):
        payload={"messaging_product":"whatsapp","to":recipient,"type":"text","text":{"body":text}}
        require_success(*safe_http(self._url()+"/messages","POST",{"Authorization":"Bearer "+self.secret,"Content-Type":"application/json"},json.dumps(payload).encode()))

class GoogleCalendarAdapter(BaseAdapter):
    def _url(self):
        return "https://www.googleapis.com/calendar/v3/calendars/" + quote(self.config["calendar_id"],safe="")
    def test_connection(self):
        require_success(*safe_http(self._url(),headers={"Authorization":"Bearer "+self.secret}))
    def create_event(self, event_id, payload):
        if not re.fullmatch(r"[a-v0-9]{5,1024}",event_id):
            raise IntegrationError("INVALID_CONFIGURATION")
        body = dict(payload,id=event_id)
        require_success(*safe_http(self._url()+"/events","POST",{"Authorization":"Bearer "+self.secret,"Content-Type":"application/json"},json.dumps(body).encode()))
    def update_event(self, event_id, payload):
        require_success(*safe_http(self._url()+"/events/"+quote(event_id,safe=""),"PATCH",{"Authorization":"Bearer "+self.secret,"Content-Type":"application/json"},json.dumps(payload).encode()))
    def cancel_event(self, event_id):
        require_success(*safe_http(self._url()+"/events/"+quote(event_id,safe=""),"DELETE",{"Authorization":"Bearer "+self.secret}))

class S3Adapter(BaseAdapter):
    def _client(self):
        import boto3
        from botocore.config import Config
        try:
            credentials=json.loads(self.secret)
            if set(credentials) != {"access_key_id","secret_access_key"}:
                raise ValueError()
            return boto3.client("s3",region_name=self.config["region"],aws_access_key_id=credentials["access_key_id"],aws_secret_access_key=credentials["secret_access_key"],
                                config=Config(connect_timeout=5,read_timeout=10,retries={"max_attempts":2}))
        except Exception:
            raise IntegrationError("INVALID_CONFIGURATION") from None
    def _key(self, key):
        if not re.fullmatch(r"[A-Za-z0-9/_-]{1,500}",key) or key.startswith("/"):
            raise IntegrationError("INVALID_CONFIGURATION")
        return self.config["prefix"] + key
    def _run(self, operation, **kwargs):
        try:
            return getattr(self._client(),operation)(Bucket=self.config["bucket"],**kwargs)
        except IntegrationError:
            raise
        except Exception:
            raise IntegrationError("PROVIDER_UNAVAILABLE") from None
    def test_connection(self):
        self._run("head_bucket")
    def upload(self,key,data):
        return self._run("put_object",Key=self._key(key),Body=data,ServerSideEncryption="AES256")
    def download(self,key):
        return self._run("get_object",Key=self._key(key))["Body"]
    def delete(self,key):
        self._run("delete_object",Key=self._key(key))
    def assert_private(self):
        block=self._run("get_public_access_block")["PublicAccessBlockConfiguration"]
        if not all(block.get(k) for k in ("BlockPublicAcls","IgnorePublicAcls","BlockPublicPolicy","RestrictPublicBuckets")):
            raise IntegrationError("INVALID_CONFIGURATION")
    def upload_private(self,key,data,mime):
        import hashlib
        return self._run("put_object",Key=self._key(key),Body=data,ContentType=mime,ServerSideEncryption="AES256",IfNoneMatch="*",Metadata={"sha256":hashlib.sha256(data).hexdigest()})
    def head(self,key):
        return self._run("head_object",Key=self._key(key))


@dataclass(frozen=True)
class ProviderDefinition:
    key: str
    category: str
    tenant_configurable: bool
    entitlement_key: str
    capabilities: tuple[str,...]
    configuration_schema: type[Configuration]
    adapter: type[BaseAdapter]
    platform_configurable: bool = True

REGISTRY = {
    item.key:item for item in (
        ProviderDefinition("smtp","EMAIL",True,"custom_email",("email.send",),SMTPConfiguration,SMTPAdapter),
        ProviderDefinition("meta_whatsapp","WHATSAPP",True,"whatsapp_integration",("whatsapp.send",),WhatsAppConfiguration,WhatsAppAdapter),
        ProviderDefinition("google_calendar","CALENDAR",True,"google_calendar_integration",("calendar.events",),CalendarConfiguration,GoogleCalendarAdapter),
        ProviderDefinition("aws_s3","STORAGE",True,"custom_storage",("storage.objects",),S3Configuration,S3Adapter),
    )
}
CATEGORIES = ("EMAIL","WHATSAPP","CALENDAR","STORAGE","AI","OCR","TRANSLATION","PAYMENT","ANALYTICS","OTHER")
def get_provider(key):
    if key not in REGISTRY:
        raise IntegrationError("INVALID_CONFIGURATION")
    return REGISTRY[key]
