import json
from typing import Annotated,Literal
from urllib.parse import quote
from fastapi import APIRouter,File,Form,HTTPException,UploadFile
from fastapi.responses import StreamingResponse
from pydantic import Field,ValidationError
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool
from .auth import CurrentUser
from .organization_profile import DB,Tenant,Strict,owned_org
from .models import Compliance,Document,DocumentVersion,Submission,Task
from .schemas import DocumentOut
from .document_models import DocumentBlob,DocumentCurrent,DocumentEvidenceLink
from .document_storage import DocumentStorage,maximum_bytes
from .document_validation import MIMES
from . import document_service as service
router=APIRouter(prefix="/api/v1",tags=["Private document evidence"])
@router.get("/documents/storage-policy")
def storage_policy(tenant:Tenant):
    return {"maximum_bytes":maximum_bytes(),"mime_types":list(MIMES.values()),"scanning_required":service.scan_required(),"scanner_configured":service.scanner_configured()}
@router.post("/documents/upload",status_code=201)
async def upload_file(db:DB,tenant:Tenant,actor:CurrentUser,file:Annotated[UploadFile,File()],metadata:Annotated[str,Form()]):
    try:values=service.UploadMetadata.model_validate_json(metadata)
    except ValidationError:raise HTTPException(422,"Invalid upload metadata") from None
    data=bytearray()
    while chunk:=await file.read(64*1024):
        data.extend(chunk)
        if len(data)>maximum_bytes():raise HTTPException(413,"Document exceeds the configured upload limit")
    try:return await run_in_threadpool(service.upload,db,tenant,actor,values,file.filename,file.content_type,bytes(data))
    except ValueError as e:raise HTTPException(422,str(e)) from None
    except RuntimeError:raise HTTPException(503,"Private document storage is not configured or unavailable") from None
@router.get("/documents/{document_id}/files")
def files(document_id:str,db:DB,tenant:Tenant):
    doc=service.owned_document(db,tenant,document_id)
    blobs=db.scalars(select(DocumentBlob).where(DocumentBlob.document_id==doc.id,DocumentBlob.tenant_id==tenant).order_by(DocumentBlob.version_number.desc())).all()
    return {"document":DocumentOut.model_validate(doc).model_dump(),"files":[service.file_data(b) for b in blobs],"links":[{"id":l.id,"version_id":l.version_id,"compliance_id":l.compliance_id,"task_id":l.task_id,"submission_id":l.submission_id,"active":l.active} for l in db.scalars(select(DocumentEvidenceLink).where(DocumentEvidenceLink.document_id==doc.id,DocumentEvidenceLink.tenant_id==tenant)).all()]}
@router.get("/documents/{document_id}/content")
def content(document_id:str,db:DB,tenant:Tenant,actor:CurrentUser,version_id:str|None=None,preview:bool=False):
    import hashlib
    doc=service.owned_document(db,tenant,document_id)
    blob=db.scalar(select(DocumentBlob).where(DocumentBlob.version_id==version_id,DocumentBlob.document_id==doc.id,DocumentBlob.tenant_id==tenant,DocumentBlob.organization_id==doc.organization_id)) if version_id else service.current_blob(db,doc)
    if not blob:raise HTTPException(404,"Original file is not available for this document record")
    if blob.status!="AVAILABLE":raise HTTPException(409,"File is processing, quarantined or unavailable")
    if preview and not blob.mime_type.startswith("image/"):raise HTTPException(415,"Preview is supported for validated images; download other formats")
    try:
        data=DocumentStorage(db,tenant,json.loads(blob.locator)).get(blob.storage_key,blob.size_bytes)
        if len(data)!=blob.size_bytes or hashlib.sha256(data).hexdigest()!=blob.checksum:raise RuntimeError()
    except Exception:raise HTTPException(503,"Original file storage is unavailable or integrity verification failed") from None
    service.audit(db,tenant,actor,"DOCUMENT_PREVIEWED" if preview else "DOCUMENT_DOWNLOADED",doc,f"Accessed immutable file version {blob.version_number}");db.commit()
    headers={"Content-Disposition":("inline" if preview else "attachment")+"; filename*=UTF-8''"+quote(blob.original_filename,safe=""),"X-Content-Type-Options":"nosniff","Content-Security-Policy":"sandbox; default-src 'none'; img-src 'self'","Cache-Control":"no-store","Content-Length":str(len(data))}
    return StreamingResponse((data[i:i+65536] for i in range(0,len(data),65536)),media_type=blob.mime_type if preview else "application/octet-stream",headers=headers)
class SelectFile(Strict):version_id:str=Field(max_length=36)
@router.post("/documents/{document_id}/current-file")
def select_file(document_id:str,payload:SelectFile,db:DB,tenant:Tenant,actor:CurrentUser):
    if actor.role!="ADMIN":raise HTTPException(403,"Administrator access is required")
    doc=service.owned_document(db,tenant,document_id);blob=db.scalar(select(DocumentBlob).where(DocumentBlob.version_id==payload.version_id,DocumentBlob.document_id==doc.id,DocumentBlob.tenant_id==tenant,DocumentBlob.status=="AVAILABLE"))
    if not blob:raise HTTPException(404,"Available file version not found")
    try:
        if not DocumentStorage(db,tenant,json.loads(blob.locator)).verify(blob.storage_key,blob.size_bytes,blob.checksum):raise RuntimeError()
    except Exception:raise HTTPException(503,"File storage verification failed") from None
    current=db.get(DocumentCurrent,doc.id)
    if not current or current.archived:raise HTTPException(409,"Restore the document before selecting a version")
    version=db.get(DocumentVersion,blob.version_id)
    current.version_id=blob.version_id;doc.expiry_at=blob.expiry_at;doc.file_type=version.file_type;doc.size_label=version.size_label
    service.audit(db,tenant,actor,"DOCUMENT_CURRENT_VERSION_SELECTED",doc,f"Selected immutable version {blob.version_number}");db.commit();return DocumentOut.model_validate(doc)
class ArchiveFile(Strict):archived:bool
@router.patch("/documents/{document_id}/archive")
def archive(document_id:str,payload:ArchiveFile,db:DB,tenant:Tenant,actor:CurrentUser):
    if actor.role!="ADMIN":raise HTTPException(403,"Administrator access is required")
    doc=service.owned_document(db,tenant,document_id);current=db.get(DocumentCurrent,doc.id) or DocumentCurrent(document_id=doc.id,tenant_id=tenant)
    current.archived=payload.archived;db.add(current);service.audit(db,tenant,actor,"DOCUMENT_ARCHIVED" if payload.archived else "DOCUMENT_RESTORED",doc,"Changed evidence archive status");db.commit();return DocumentOut.model_validate(doc)
class LinkInput(Strict):
    target_type:Literal["compliance","task","submission"]
    target_id:str=Field(min_length=1,max_length=36)
@router.post("/documents/{document_id}/links",status_code=201)
def link(document_id:str,payload:LinkInput,db:DB,tenant:Tenant,actor:CurrentUser):
    doc=service.owned_document(db,tenant,document_id);blob=service.genuine_file(db,doc)
    if not blob:raise HTTPException(422,"Evidence requires an available stored file version")
    row=service.attach_link(db,tenant,doc.organization_id,doc,blob,actor,payload.target_type,payload.target_id);db.commit();return {"id":row.id,"version_id":row.version_id}
@router.patch("/documents/{document_id}/links/{link_id}/archive")
def unlink(document_id:str,link_id:str,db:DB,tenant:Tenant,actor:CurrentUser):
    if actor.role!="ADMIN":raise HTTPException(403,"Administrator access is required")
    doc=service.owned_document(db,tenant,document_id);row=db.scalar(select(DocumentEvidenceLink).where(DocumentEvidenceLink.id==link_id,DocumentEvidenceLink.document_id==doc.id,DocumentEvidenceLink.tenant_id==tenant))
    if not row:raise HTTPException(404,"Evidence link not found")
    row.active=False;service.audit(db,tenant,actor,"DOCUMENT_EVIDENCE_UNLINKED",doc,"Archived relationship; retained immutable file history");db.commit();return {"id":row.id,"active":False}

@router.get("/documents/link-targets")
def link_targets(organization_id:str,db:DB,tenant:Tenant):
    owned_org(db,tenant,organization_id)
    return {"compliance":[{"id":r.id,"label":r.title} for r in db.scalars(select(Compliance).where(Compliance.tenant_id==tenant,Compliance.organization_id==organization_id)).all()],
        "task":[{"id":r.id,"label":r.title} for r in db.scalars(select(Task).where(Task.tenant_id==tenant,Task.organization_id==organization_id)).all()],
        "submission":[{"id":r.id,"label":r.acknowledgement_ref} for r in db.scalars(select(Submission).join(Compliance,Submission.compliance_id==Compliance.id).where(Submission.tenant_id==tenant,Compliance.tenant_id==tenant,Compliance.organization_id==organization_id)).all()]}
