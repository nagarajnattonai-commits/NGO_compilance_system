"""Authorization, idempotent file uploads and genuine evidence for existing documents."""
import hashlib
import json
from datetime import date,timedelta
from typing import Protocol
from uuid import UUID
from pathlib import PurePath
from fastapi import HTTPException
from pydantic import Field
from sqlalchemy import func,select,update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import object_session
from .organization_profile import Strict,owned_org
from .models import AuditEvent,Compliance,Document,DocumentVersion,Submission,Subscription,Task,uid
from .schemas import DocumentOut
from .document_models import DocumentBlob,DocumentCurrent,DocumentEvidenceLink,DocumentUploadReceipt
from .document_storage import DocumentStorage,maximum_bytes
from .document_validation import validate_file

FILE_STATES={"UPLOADING","PROCESSING","AVAILABLE","QUARANTINED","FAILED"}
class Scanner(Protocol):
    def scan(self,content:bytes,mime:str)->str: ...
_scanner:Scanner|None=None

def configure_scanner(scanner:Scanner|None):
    global _scanner
    _scanner=scanner

def scan_required():
    import os
    return os.getenv("DOCUMENT_SCAN_REQUIRED","false").lower()=="true"
def scanner_configured():return _scanner is not None

def audit(db,tenant,actor,action,doc,summary):
    db.add(AuditEvent(tenant_id=tenant,actor_name=actor.name,action=action,entity_type="Document",entity_id=doc.id,summary=summary))
def owned_document(db,tenant,id):
    doc=db.scalar(select(Document).where(Document.id==id,Document.tenant_id==tenant))
    if not doc:raise HTTPException(404,"Document not found in this workspace")
    owned_org(db,tenant,doc.organization_id);return doc
def current_blob(db,doc):
    cache=db.info.setdefault("document_current_cache",{})
    if doc.id not in cache:cache[doc.id]=db.get(DocumentCurrent,doc.id)
    current=cache[doc.id]
    if not current or current.tenant_id!=doc.tenant_id or current.archived or not current.version_id:return None
    blobs=db.info.setdefault("document_blob_cache",{})
    if current.version_id not in blobs:blobs[current.version_id]=db.get(DocumentBlob,current.version_id)
    blob=blobs[current.version_id]
    return blob if blob and blob.tenant_id==doc.tenant_id and blob.organization_id==doc.organization_id and blob.document_id==doc.id else None
def genuine_file(db,doc,reference_date=None,must_be_valid=False):
    blob=current_blob(db,doc)
    if not blob or blob.status!="AVAILABLE":return None
    if must_be_valid and (blob.effective_at and blob.effective_at>date.today() or blob.expiry_at and blob.expiry_at<max(reference_date or date.today(),date.today())):return None
    try:
        if not DocumentStorage(db,doc.tenant_id,json.loads(blob.locator)).verify(blob.storage_key,blob.size_bytes,blob.checksum):return None
    except Exception:return None
    return blob
def document_summary(doc):
    db=object_session(doc);blob=current_blob(db,doc) if db else None;current=db.info.get("document_current_cache",{}).get(doc.id) if db else None
    return {"storage_status":"ARCHIVED" if current and current.archived else blob.status if blob else "METADATA_ONLY","current_version_id":blob.version_id if blob else None,"effective_at":blob.effective_at if blob else None,"expiry_status":"METADATA_ONLY" if not blob else "NO_EXPIRY" if not blob.expiry_at else "EXPIRED" if blob.expiry_at<date.today() else "EXPIRING_SOON" if blob.expiry_at<=date.today()+timedelta(days=30) else "VALID"}
def file_data(blob):
    db=object_session(blob);version=db.get(DocumentVersion,blob.version_id) if db else None
    return {"version_id":blob.version_id,"document_id":blob.document_id,"version":blob.version_number,"original_filename":blob.original_filename,"mime_type":blob.mime_type,"size_bytes":blob.size_bytes,"checksum":blob.checksum,"uploaded_by":blob.uploaded_by,"uploader_name":version.uploaded_by if version else "","uploaded_at":blob.uploaded_at,"effective_at":blob.effective_at,"expiry_at":blob.expiry_at,"status":blob.status,"scan_status":blob.scan_status}
def attach_link(db,tenant,org,doc,blob,actor,target_type,target_id):
    if target_type=="compliance":target=db.scalar(select(Compliance).where(Compliance.id==target_id,Compliance.tenant_id==tenant,Compliance.organization_id==org))
    elif target_type=="task":target=db.scalar(select(Task).where(Task.id==target_id,Task.tenant_id==tenant,Task.organization_id==org))
    elif target_type=="submission":target=db.scalar(select(Submission).join(Compliance,Compliance.id==Submission.compliance_id).where(Submission.id==target_id,Submission.tenant_id==tenant,Compliance.tenant_id==tenant,Compliance.organization_id==org))
    else:raise HTTPException(422,"Unsupported evidence link")
    if not target:raise HTTPException(404,"Evidence target not found in this organization")
    column={"compliance":"compliance_id","task":"task_id","submission":"submission_id"}[target_type]
    existing=db.scalar(select(DocumentEvidenceLink).where(DocumentEvidenceLink.tenant_id==tenant,DocumentEvidenceLink.version_id==blob.version_id,getattr(DocumentEvidenceLink,column)==target_id,DocumentEvidenceLink.active.is_(True)))
    if existing:return existing
    link=DocumentEvidenceLink(tenant_id=tenant,organization_id=org,document_id=doc.id,version_id=blob.version_id,linked_by=actor.id,**{column:target_id});db.add(link)
    if target_type=="compliance":doc.compliance_id=target_id
    if target_type=="submission":target.proof_document_id=doc.id
    audit(db,tenant,actor,"DOCUMENT_EVIDENCE_LINKED",doc,"Linked immutable file version to "+target_type);return link
class UploadMetadata(Strict):
    request_id:UUID
    organization_id:str=Field(min_length=1,max_length=36)
    name:str=Field(min_length=3,max_length=255)
    category:str=Field(min_length=1,max_length=80)
    document_id:str|None=Field(default=None,max_length=36)
    expected_version:int|None=Field(default=None,ge=1)
    compliance_id:str|None=Field(default=None,max_length=36)
    task_id:str|None=Field(default=None,max_length=36)
    effective_at:date|None=None
    expiry_at:date|None=None

def upload(db,tenant,actor,metadata,filename,mime,content):
    original,safe=validate_file(filename,mime,content)
    if len(content)>maximum_bytes():raise HTTPException(413,"Document exceeds the configured upload limit")
    if metadata.effective_at and metadata.expiry_at and metadata.expiry_at<metadata.effective_at:raise HTTPException(422,"Expiry cannot precede the effective date")
    org=owned_org(db,tenant,metadata.organization_id)
    if org.status!="ACTIVE":raise HTTPException(409,"Upload evidence to an active organization")
    if actor.role=="VIEWER":raise HTTPException(403,"Read-only accounts cannot upload evidence")
    if metadata.compliance_id and not db.scalar(select(Compliance.id).where(Compliance.id==metadata.compliance_id,Compliance.tenant_id==tenant,Compliance.organization_id==org.id)):raise HTTPException(404,"Compliance not found in this organization")
    if metadata.task_id and not db.scalar(select(Task.id).where(Task.id==metadata.task_id,Task.tenant_id==tenant,Task.organization_id==org.id)):raise HTTPException(404,"Task not found in this organization")
    checksum=hashlib.sha256(content).hexdigest()
    fingerprint=hashlib.sha256(json.dumps({**metadata.model_dump(mode="json"),"checksum":checksum,"filename":original,"mime":mime},sort_keys=True).encode()).hexdigest()
    def replay(receipt):
        if not receipt or receipt.fingerprint!=fingerprint:raise HTTPException(409,"Upload request ID has already been used for different content")
        blob=db.get(DocumentBlob,receipt.version_id)
        if not blob:raise HTTPException(409,"Upload is still in progress; retry shortly")
        return {"document":DocumentOut.model_validate(owned_document(db,tenant,blob.document_id)).model_dump(),"file":file_data(blob),"replayed":True}
    receipt=db.scalar(select(DocumentUploadReceipt).where(DocumentUploadReceipt.tenant_id==tenant,DocumentUploadReceipt.request_id==str(metadata.request_id)))
    if receipt:return replay(receipt)
    receipt=DocumentUploadReceipt(tenant_id=tenant,request_id=str(metadata.request_id),fingerprint=fingerprint);db.add(receipt)
    try:db.flush()
    except IntegrityError:
        db.rollback();return replay(db.scalar(select(DocumentUploadReceipt).where(DocumentUploadReceipt.tenant_id==tenant,DocumentUploadReceipt.request_id==str(metadata.request_id))))
    subscription=db.scalar(select(Subscription).where(Subscription.tenant_id==tenant).with_for_update())
    used=db.scalar(select(func.coalesce(func.sum(DocumentBlob.size_bytes),0)).where(DocumentBlob.tenant_id==tenant)) or 0
    if subscription and used+len(content)>subscription.storage_limit_gb*1024**3:raise HTTPException(403,"Workspace storage limit reached")
    if scan_required() and _scanner is None:raise HTTPException(503,"Document scanning is required but no scanner is configured")
    status="AVAILABLE";scan="NOT_SCANNED"
    if _scanner:
        try:verdict=_scanner.scan(content,mime)
        except Exception:raise HTTPException(503,"Document scanner is unavailable") from None
        if verdict not in {"CLEAN","QUARANTINED","PROCESSING","FAILED"}:raise HTTPException(503,"Document scanner returned an invalid result")
        status="AVAILABLE" if verdict=="CLEAN" else verdict;scan="SCANNED_CLEAN" if verdict=="CLEAN" else verdict
    doc=owned_document(db,tenant,metadata.document_id) if metadata.document_id else None
    if doc and doc.organization_id!=org.id:raise HTTPException(404,"Document not found in this organization")
    if doc and doc.category!=metadata.category:raise HTTPException(422,"Replacement category must match the existing document")
    if doc:
        if metadata.expected_version is None:raise HTTPException(422,"Expected version is required for replacement uploads")
        current=db.get(DocumentCurrent,doc.id)
        if current and current.archived:raise HTTPException(409,"Restore the archived document before renewal")
        claimed=db.execute(update(Document).where(Document.id==doc.id,Document.tenant_id==tenant,Document.version==metadata.expected_version).values(version=Document.version+1).execution_options(synchronize_session=False))
        if claimed.rowcount!=1:raise HTTPException(409,"Document changed; reload before uploading a new version")
        version_number=metadata.expected_version+1
    else:
        doc=Document(id=uid(),tenant_id=tenant,organization_id=org.id,name=metadata.name,category=metadata.category,uploaded_by=actor.name,version=1);db.add(doc);db.flush();version_number=1
    version=DocumentVersion(id=uid(),tenant_id=tenant,document_id=doc.id,version=version_number,file_type=PurePath(original).suffix[1:].upper(),size_label=f"{len(content)} bytes",uploaded_by=actor.name);db.add(version);db.flush()
    try:storage=DocumentStorage(db,tenant)
    except Exception:raise HTTPException(503,"Private document storage is not configured or unavailable") from None
    key=f"tenants/{tenant}/organizations/{org.id}/documents/{doc.id}/versions/{version.id}/content"
    wrote=False
    try:
        storage.put(key,content,mime);wrote=True
        if not storage.verify(key,len(content),checksum):raise RuntimeError("Stored upload failed verification")
        blob=DocumentBlob(version_id=version.id,tenant_id=tenant,organization_id=org.id,document_id=doc.id,version_number=version_number,provider=storage.provider,locator=json.dumps(storage.locator),storage_key=key,original_filename=original,safe_filename=safe,mime_type=mime,size_bytes=len(content),checksum=checksum,uploaded_by=actor.id,effective_at=metadata.effective_at,expiry_at=metadata.expiry_at,status=status,scan_status=scan);db.add(blob);db.flush()
        current=db.get(DocumentCurrent,doc.id) or DocumentCurrent(document_id=doc.id,tenant_id=tenant)
        if status=="AVAILABLE" or not current.version_id:current.version_id=blob.version_id
        db.add(current)
        if status=="AVAILABLE":doc.file_type=version.file_type;doc.size_label=version.size_label;doc.expiry_at=blob.expiry_at;doc.uploaded_by=actor.name
        receipt.version_id=version.id
        if status=="AVAILABLE":
            if metadata.compliance_id:attach_link(db,tenant,org.id,doc,blob,actor,"compliance",metadata.compliance_id)
            if metadata.task_id:attach_link(db,tenant,org.id,doc,blob,actor,"task",metadata.task_id)
        audit(db,tenant,actor,"DOCUMENT_RENEWED" if version_number>1 else "DOCUMENT_UPLOADED",doc,f"Stored immutable version {version_number}; {status}; {scan}")
        db.commit();db.refresh(doc)
        return {"document":DocumentOut.model_validate(doc).model_dump(),"file":file_data(blob),"replayed":False}
    except Exception:
        db.rollback()
        if wrote:
            try:storage.discard_uncommitted(key)
            except Exception:pass
        raise HTTPException(503,"Private document storage is unavailable; retry the upload") from None
