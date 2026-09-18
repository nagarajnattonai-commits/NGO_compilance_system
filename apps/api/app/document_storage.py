"""Private document providers; credentials reuse the existing integration secret store."""
import hashlib
import os
from pathlib import Path
import boto3
from botocore.config import Config
from .database import DATA_DIR
from .integration_security import IntegrationError, secret_store
from .integration_providers import S3Adapter
from .integration_service import resolve_integration
from .models import IntegrationConnection
from sqlalchemy import select

def maximum_bytes():
    try:value=int(os.getenv("DOCUMENT_MAX_SIZE_MB","25"))
    except ValueError:raise RuntimeError("DOCUMENT_MAX_SIZE_MB must be an integer") from None
    if not 1<=value<=100:raise RuntimeError("DOCUMENT_MAX_SIZE_MB must be between 1 and 100")
    return value*1024*1024

class DocumentStorage:
    def __init__(self,db,tenant,locator=None):
        self.adapter=None;self.client=None
        if locator is None:
            try:
                connection,state,adapter=resolve_integration(db,tenant,"STORAGE","storage.objects")
                locator={"provider":"managed_s3","configuration":adapter.config,"credential_reference":state.credential_reference}
                self.adapter=adapter
            except IntegrationError:
                if db.scalar(select(IntegrationConnection.id).where(IntegrationConnection.tenant_id==tenant,IntegrationConnection.provider=="aws_s3",IntegrationConnection.status=="CONNECTED")):
                    raise RuntimeError("Configured document storage is unavailable") from None
                bucket=os.getenv("DOCUMENT_S3_BUCKET","")
                locator={"provider":"s3","bucket":bucket,"region":os.getenv("AWS_REGION","ap-south-1"),"endpoint":os.getenv("DOCUMENT_S3_ENDPOINT","")} if bucket else {"provider":"local"}
        self.locator=locator;self.provider=locator["provider"]
        self.directory=Path(os.getenv("DOCUMENT_FILE_DIR",str(DATA_DIR/"private-documents"))).resolve()
        if self.provider=="local":
            if os.getenv("APP_ENV")=="production":raise RuntimeError("Production compliance documents require private S3 storage")
        elif self.provider=="managed_s3":
            if not self.adapter:self.adapter=S3Adapter(locator["configuration"],secret_store().get_secret_for_server_use(locator["credential_reference"]))
        elif self.provider=="s3":
            if locator.get("endpoint") and not locator["endpoint"].startswith("https://"):raise RuntimeError("Document S3 endpoint must use HTTPS")
            self.client=boto3.client("s3",endpoint_url=locator.get("endpoint") or None,region_name=locator["region"],config=Config(connect_timeout=5,read_timeout=15,retries={"max_attempts":2}))
        else:raise RuntimeError("Unknown document storage provider")
    def path(self,key):
        target=(self.directory/key).resolve()
        if not target.is_relative_to(self.directory) or target==self.directory:raise ValueError("Invalid storage reference")
        return target
    def private_bucket(self):
        if self.adapter:self.adapter.assert_private()
        elif self.client:
            block=self.client.get_public_access_block(Bucket=self.locator["bucket"])["PublicAccessBlockConfiguration"]
            if not all(block.get(k) for k in ("BlockPublicAcls","IgnorePublicAcls","BlockPublicPolicy","RestrictPublicBuckets")):
                raise RuntimeError("Document bucket must block public access")
    def put(self,key,content,mime):
        self.private_bucket()
        if self.adapter:self.adapter.upload_private(key,content,mime)
        elif self.client:self.client.put_object(Bucket=self.locator["bucket"],Key=key,Body=content,ContentType=mime,ServerSideEncryption="AES256",IfNoneMatch="*",Metadata={"sha256":hashlib.sha256(content).hexdigest()})
        else:
            target=self.path(key);target.parent.mkdir(parents=True,exist_ok=True)
            with target.open("xb") as file:file.write(content)
    def get(self,key,limit):
        if self.adapter:body=self.adapter.download(key)
        elif self.client:body=self.client.get_object(Bucket=self.locator["bucket"],Key=key)["Body"]
        else:
            with self.path(key).open("rb") as file:return file.read(limit+1)
        try:return body.read(limit+1)
        finally:body.close()
    def verify(self,key,size,checksum):
        if self.adapter:
            data=self.adapter.head(key)
            return data["ContentLength"]==size and data.get("Metadata",{}).get("sha256")==checksum
        if self.client:
            data=self.client.head_object(Bucket=self.locator["bucket"],Key=key)
            return data["ContentLength"]==size and data.get("Metadata",{}).get("sha256")==checksum
        content=self.get(key,size)
        return len(content)==size and hashlib.sha256(content).hexdigest()==checksum
    def discard_uncommitted(self,key):
        if self.adapter:self.adapter.delete(key)
        elif self.client:self.client.delete_object(Bucket=self.locator["bucket"],Key=key)
        else:self.path(key).unlink(missing_ok=True)
