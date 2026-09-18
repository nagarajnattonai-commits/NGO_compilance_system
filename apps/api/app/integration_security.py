"""Credential storage and a DNS-pinned HTTPS transport. Never log request bodies."""
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
from typing import Protocol
from urllib.parse import urlsplit
from fastapi import HTTPException
from botocore.config import Config

ERROR_MESSAGES = {
    "INTEGRATION_NOT_CONFIGURED": "Configure server-side credentials before testing.",
    "AUTHENTICATION_FAILED": "Authentication failed. Replace credentials or reconnect the account.",
    "RATE_LIMITED": "The provider rate limit was reached. Please try again later.",
    "PROVIDER_UNAVAILABLE": "The provider is unavailable. Please try again later.",
    "TIMEOUT": "The provider did not respond in time.",
    "INVALID_CONFIGURATION": "Check the provider configuration.",
    "PERMISSION_DENIED": "This integration is not available to this account.",
    "SECRET_STORE_UNAVAILABLE": "The server secret store is unavailable or read-only.",
}
class IntegrationError(Exception):
    def __init__(self, code, retry_after=60):
        self.code = code if code in ERROR_MESSAGES else "PROVIDER_UNAVAILABLE"
        self.retry_after = max(30, min(int(retry_after), 3600))
        super().__init__(ERROR_MESSAGES[self.code])

class SecretStore(Protocol):
    writable: bool
    def reference(self, tenant_id: str, resource_id: str) -> str: ...
    def get_secret_for_server_use(self, reference: str) -> str: ...
    def create_secret(self, reference: str, value: str) -> None: ...
    def update_secret(self, reference: str, value: str) -> None: ...
    def delete_secret(self, reference: str) -> None: ...

class EnvironmentSecretStore:
    """Development only. Operators inject per-resource values; no API writes to env."""
    writable = False
    def reference(self, tenant_id, resource_id):
        return "env://SETU_SECRET_" + resource_id.replace("-", "").upper()
    def get_secret_for_server_use(self, reference):
        if not re.fullmatch(r"env://SETU_SECRET_[A-F0-9]{32}", reference):
            raise IntegrationError("INVALID_CONFIGURATION")
        value = os.getenv(reference[6:])
        if not value:
            raise IntegrationError("INTEGRATION_NOT_CONFIGURED")
        return value
    def create_secret(self, reference, value):
        raise IntegrationError("SECRET_STORE_UNAVAILABLE")
    update_secret = create_secret
    def delete_secret(self, reference):
        raise IntegrationError("SECRET_STORE_UNAVAILABLE")

class AwsSecretStore:
    writable = True
    def __init__(self):
        import boto3
        self.prefix = os.getenv("INTEGRATION_SECRET_PREFIX", "setu/integrations").strip("/")
        if not re.fullmatch(r"[A-Za-z0-9/_-]{1,100}", self.prefix):
            raise IntegrationError("INVALID_CONFIGURATION")
        self.client = boto3.client("secretsmanager", config=Config(connect_timeout=5, read_timeout=8, retries={"max_attempts": 2}))
    def reference(self, tenant_id, resource_id):
        import hashlib
        owner = hashlib.sha256(tenant_id.encode()).hexdigest()[:24]
        return "aws://" + self.prefix + "/" + owner + "/" + resource_id
    def _id(self, reference):
        if not reference.startswith("aws://" + self.prefix + "/"):
            raise IntegrationError("PERMISSION_DENIED")
        return reference[6:]
    def get_secret_for_server_use(self, reference):
        try:
            return self.client.get_secret_value(SecretId=self._id(reference))["SecretString"]
        except IntegrationError:
            raise
        except Exception:
            raise IntegrationError("SECRET_STORE_UNAVAILABLE") from None
    def create_secret(self, reference, value):
        try:
            values={"Name":self._id(reference),"SecretString":value}
            if os.getenv("INTEGRATION_SECRET_KMS_KEY_ID"):values["KmsKeyId"]=os.environ["INTEGRATION_SECRET_KMS_KEY_ID"]
            self.client.create_secret(**values)
        except self.client.exceptions.ResourceExistsException:
            self.update_secret(reference, value)
        except Exception:
            raise IntegrationError("SECRET_STORE_UNAVAILABLE") from None
    def update_secret(self, reference, value):
        try:
            self.client.put_secret_value(SecretId=self._id(reference), SecretString=value)
        except self.client.exceptions.ResourceNotFoundException:
            self.create_secret(reference, value)
        except self.client.exceptions.InvalidRequestException:
            try:
                metadata=self.client.describe_secret(SecretId=self._id(reference))
                if not metadata.get("DeletedDate"):
                    raise IntegrationError("SECRET_STORE_UNAVAILABLE")
                self.client.restore_secret(SecretId=self._id(reference))
                self.client.put_secret_value(SecretId=self._id(reference),SecretString=value)
            except Exception:
                raise IntegrationError("SECRET_STORE_UNAVAILABLE") from None
        except Exception:
            raise IntegrationError("SECRET_STORE_UNAVAILABLE") from None
    def delete_secret(self, reference):
        try:
            self.client.delete_secret(SecretId=self._id(reference), RecoveryWindowInDays=7)
        except self.client.exceptions.ResourceNotFoundException:
            pass
        except Exception:
            raise IntegrationError("SECRET_STORE_UNAVAILABLE") from None

def secret_store():
    backend = os.getenv("INTEGRATION_SECRET_BACKEND", "environment")
    if backend == "aws":
        try:
            return AwsSecretStore()
        except IntegrationError:
            raise
        except Exception:
            raise IntegrationError("SECRET_STORE_UNAVAILABLE") from None
    if backend == "environment" and os.getenv("APP_ENV") != "production":
        return EnvironmentSecretStore()
    raise IntegrationError("SECRET_STORE_UNAVAILABLE")

def validate_url(url: str, resolve=True):
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        if parsed.scheme != "https" or not host or parsed.username or parsed.password or parsed.fragment or parsed.query or parsed.port not in (None,443):
            raise ValueError()
        if len(url) > 2000 or any(ord(char) < 33 or ord(char) > 126 for char in url) or "\\" in url or "%" in host:
            raise ValueError()
        host = host.lower().rstrip(".")
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")) or "." not in host:
            raise ValueError()
        try:
            address = ipaddress.ip_address(host)
            if not address.is_global:
                raise ValueError()
        except ValueError:
            if re.fullmatch(r"[0-9.:]+",host):
                raise ValueError()
        addresses = list({entry[4][0] for entry in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)}) if resolve else []
        if resolve and (not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses)):
            raise ValueError()
        return host, parsed.path or "/", addresses
    except (ValueError, OSError):
        raise IntegrationError("INVALID_CONFIGURATION") from None

class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, hostname, address):
        super().__init__(hostname, timeout=10, context=ssl.create_default_context())
        self.address = address
    def connect(self):
        sock = socket.create_connection((self.address,443),timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise

def safe_http(url, method="GET", headers=None, body=None):
    host,path,addresses = validate_url(url)
    connection = PinnedHTTPSConnection(host, addresses[0])
    try:
        connection.request(method,path,body=body,headers=headers or {})
        response = connection.getresponse()
        # Ignore response body. Do not follow redirects or re-resolve the hostname.
        response.read(4096)
        retry = response.getheader("Retry-After","60")
        retry = int(retry) if retry.isdigit() else 60
        return response.status, min(retry,3600)
    except (TimeoutError, socket.timeout):
        raise IntegrationError("TIMEOUT") from None
    except (OSError, http.client.HTTPException):
        raise IntegrationError("PROVIDER_UNAVAILABLE") from None
    finally:
        connection.close()

def require_success(status, retry_after=60):
    if status in (401,403):
        raise IntegrationError("AUTHENTICATION_FAILED")
    if status == 429:
        raise IntegrationError("RATE_LIMITED", retry_after)
    if not 200 <= status < 300:
        raise IntegrationError("PROVIDER_UNAVAILABLE" if status >=500 else "INVALID_CONFIGURATION")

def public_error(error):
    raise HTTPException(503, ERROR_MESSAGES[error.code]) from None
