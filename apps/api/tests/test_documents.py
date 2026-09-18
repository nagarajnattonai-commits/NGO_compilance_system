import hashlib
import json
from datetime import date,timedelta
from io import BytesIO
from uuid import uuid4
import pytest
from PIL import Image
from sqlalchemy import create_engine,select
from app.database import Base,SessionLocal
from app.models import AuditEvent,Compliance,Document,DocumentVersion,Organization,Submission,User
from app.auth import digest
from app.auth_models import SessionContext
from app.document_models import DocumentBlob,DocumentCurrent,DocumentEvidenceLink,DocumentUploadReceipt
from app.document_service import configure_scanner,genuine_file
from app.document_storage import DocumentStorage
from test_compliance_master import create,platform_client,publish

def image_bytes(color="green"):
    output=BytesIO();Image.new("RGB",(32,32),color).save(output,"PNG");return output.getvalue()
def upload_original(client,content=None,**fields):
    metadata={"request_id":str(uuid4()),"organization_id":"org-udaan","name":"Sample proof.png","category":"Sample evidence",**fields}
    return client.post("/api/v1/documents/upload",data={"metadata":json.dumps(metadata)},files={"file":("Sample proof.png",content if content is not None else image_bytes(),"image/png")})

def test_original_bytes_checksum_idempotency_renewal_selection_and_archive(monkeypatch):
    with platform_client(monkeypatch) as client:
        request_id=str(uuid4());first=upload_original(client,request_id=request_id,expiry_at="2030-01-01")
        assert first.status_code==201,first.text
        data=first.json();doc=data["document"];version=data["file"]
        assert version["checksum"]==hashlib.sha256(image_bytes()).hexdigest() and version["scan_status"]=="NOT_SCANNED"
        assert upload_original(client,request_id=request_id,expiry_at="2030-01-01").json()["replayed"]
        assert upload_original(client,content=image_bytes("red"),request_id=request_id,expiry_at="2030-01-01").status_code==409
        response=client.get(f"/api/v1/documents/{doc['id']}/content")
        assert response.status_code==200 and response.content==image_bytes() and "attachment" in response.headers["content-disposition"]
        assert client.get(f"/api/v1/documents/{doc['id']}/content?preview=true").headers["content-type"].startswith("image/png")
        renewed=upload_original(client,content=image_bytes("red"),document_id=doc["id"],expected_version=1,expiry_at="2031-01-01")
        assert renewed.status_code==201,renewed.text
        assert renewed.json()["document"]["version"]==2
        assert client.get(f"/api/v1/documents/{doc['id']}/content?version_id={version['version_id']}").content==image_bytes()
        assert upload_original(client,document_id=doc["id"],expected_version=1).status_code==409
        assert client.post(f"/api/v1/documents/{doc['id']}/versions",json={"file_type":"PDF","uploaded_by":"Spoof"}).status_code==409
        selected=client.post(f"/api/v1/documents/{doc['id']}/current-file",json={"version_id":version["version_id"]})
        assert selected.status_code==200 and selected.json()["version"]==2 and selected.json()["expiry_at"]=="2030-01-01"
        assert client.patch(f"/api/v1/documents/{doc['id']}/archive",json={"archived":True}).json()["storage_status"]=="ARCHIVED"
        assert client.get(f"/api/v1/documents/{doc['id']}/content").status_code==404
        assert client.get(f"/api/v1/documents/{doc['id']}/content?version_id={version['version_id']}").content==image_bytes()
        assert len(client.get(f"/api/v1/documents/{doc['id']}/files").json()["files"])==2
        assert client.patch(f"/api/v1/documents/{doc['id']}/archive",json={"archived":False}).status_code==200
        with SessionLocal() as db:
            assert len(db.scalars(select(DocumentBlob)).all())==2 and len(db.scalars(select(DocumentUploadReceipt)).all())==2
            assert db.scalar(select(AuditEvent).where(AuditEvent.action=="DOCUMENT_DOWNLOADED"))

@pytest.mark.parametrize("name,mime,content",[("script.svg","image/svg+xml",b"<svg/>"),("file.pdf","application/pdf",b"not a PDF"),("proof.png","application/pdf",b"%PDF-1.4\n%%EOF"),("proof.png","image/png",b""),("file.pdf","application/pdf",b"%PDF-1.4\n/JavaScript()\n%%EOF")])
def test_upload_validates_format_and_mime_on_server(monkeypatch,name,mime,content):
    with platform_client(monkeypatch) as client:
        metadata={"request_id":str(uuid4()),"organization_id":"org-udaan","name":"Invalid sample","category":"Sample"}
        assert client.post("/api/v1/documents/upload",data={"metadata":json.dumps(metadata)},files={"file":(name,content,mime)}).status_code==422
        with SessionLocal() as db:assert db.scalars(select(DocumentBlob)).all()==[]

def test_server_size_limit_and_storage_failure_retry_do_not_create_fake_evidence(monkeypatch):
    with platform_client(monkeypatch) as client:
        monkeypatch.setenv("DOCUMENT_MAX_SIZE_MB","1")
        assert upload_original(client,content=b"x"*(1024*1024+1)).status_code==413
        original=DocumentStorage.put
        monkeypatch.setattr(DocumentStorage,"put",lambda *args:(_ for _ in ()).throw(OSError("unavailable")))
        request_id=str(uuid4());response=upload_original(client,request_id=request_id)
        assert response.status_code==503
        with SessionLocal() as db:assert db.scalars(select(DocumentBlob)).all()==[] and db.scalars(select(DocumentUploadReceipt)).all()==[]
        monkeypatch.setattr(DocumentStorage,"put",original)
        assert upload_original(client,request_id=request_id).status_code==201

def test_required_document_coverage_rejects_metadata_expiry_and_missing_bytes(monkeypatch):
    with platform_client(monkeypatch) as client:
        row=publish(client,create(client))
        instance=next(r for r in client.post("/api/v1/organizations/org-udaan/generate-plan").json() if r["code"]==row["code"])
        root=f"/api/v1/compliances/{instance['id']}"
        for task in client.get("/api/v1/tasks").json():
            if task["compliance_id"]==instance["id"]:assert client.patch(f"/api/v1/tasks/{task['id']}",json={"status":"DONE"}).status_code==200
        assert client.post(root+"/transitions",json={"target_status":"IN_PROGRESS"}).status_code==200
        client.post("/api/v1/documents",json={"organization_id":"org-udaan","name":"Metadata only","category":"Sample evidence"})
        assert client.post(root+"/transitions",json={"target_status":"COMPLETED"}).status_code==422
        expired=upload_original(client,expiry_at=(date.today()-timedelta(days=1)).isoformat()).json()
        assert client.post(root+"/transitions",json={"target_status":"COMPLETED"}).status_code==422
        valid=upload_original(client,document_id=expired["document"]["id"],expected_version=1,expiry_at="2031-01-01").json()
        with SessionLocal() as db:
            doc=db.get(Document,valid["document"]["id"]);blob=genuine_file(db,doc);storage=DocumentStorage(db,doc.tenant_id,json.loads(blob.locator));path=storage.path(blob.storage_key);original=path.read_bytes();path.write_bytes(b"corrupted")
        assert client.post(root+"/transitions",json={"target_status":"COMPLETED"}).status_code==422
        path.write_bytes(original)
        assert client.post(root+"/transitions",json={"target_status":"COMPLETED"}).status_code==200

def test_filing_proof_pins_original_version_and_links_task(monkeypatch):
    with platform_client(monkeypatch) as client:
        compliance=client.post("/api/v1/compliances",json={"organization_id":"org-udaan","code":"FILE-QA","title":"Sample filing","category":"Sample","period":"QA","statutory_deadline":"2030-01-01","owner_name":"Sample"}).json()
        task=client.post("/api/v1/tasks",json={"organization_id":"org-udaan","compliance_id":compliance["id"],"title":"Proof task","due_at":"2030-01-01","assignee_name":"Sample"}).json()
        for state in ("IN_PROGRESS","UNDER_REVIEW","READY_TO_FILE"):assert client.post(f"/api/v1/compliances/{compliance['id']}/transitions",json={"target_status":state}).status_code==200
        metadata=client.post("/api/v1/documents",json={"organization_id":"org-udaan","name":"Metadata proof","category":"Sample evidence"}).json()
        assert client.post(f"/api/v1/compliances/{compliance['id']}/transitions",json={"target_status":"FILED","proof_document_id":metadata["id"]}).status_code==422
        proof=upload_original(client,compliance_id=compliance["id"],task_id=task["id"]).json()
        assert client.post(f"/api/v1/compliances/{compliance['id']}/transitions",json={"target_status":"FILED","proof_document_id":proof["document"]["id"]}).status_code==200
        assert upload_original(client,document_id=proof["document"]["id"],expected_version=1).status_code==201
        links=client.get(f"/api/v1/documents/{proof['document']['id']}/files").json()["links"]
        assert any(l["submission_id"] and l["version_id"]==proof["file"]["version_id"] for l in links)
        assert any(l["task_id"]==task["id"] for l in links)

def test_scanner_extension_quarantines_and_required_scanner_fails_closed(monkeypatch):
    with platform_client(monkeypatch) as client:
        monkeypatch.setenv("DOCUMENT_SCAN_REQUIRED","true")
        assert upload_original(client).status_code==503
        class Quarantine:
            def scan(self,content,mime):return "QUARANTINED"
        configure_scanner(Quarantine());result=upload_original(client).json();doc=result["document"]
        assert result["file"]["status"]=="QUARANTINED" and doc["storage_status"]=="QUARANTINED"
        assert client.get(f"/api/v1/documents/{doc['id']}/content").status_code==409
        with SessionLocal() as db:assert genuine_file(db,db.get(Document,doc["id"])) is None
        configure_scanner(None)

def test_document_reads_and_mutations_enforce_tenant_and_viewer_boundaries(monkeypatch):
    with platform_client(monkeypatch) as client:
        result=upload_original(client).json();doc=result["document"]
        with SessionLocal() as db:
            db.add(Organization(id="foreign",tenant_id="other",name="Foreign",legal_type="TRUST",registration_number="Other",city="City"));db.add(Document(id="foreign-doc",tenant_id="other",organization_id="foreign",name="Other file",category="Sample",uploaded_by="Other"));db.commit()
        assert client.get("/api/v1/documents/foreign-doc/files").status_code==404
        assert client.get("/api/v1/documents/foreign-doc/content").status_code==404
        assert upload_original(client,organization_id="foreign").status_code==404
        assert client.post(f"/api/v1/documents/{doc['id']}/links",json={"target_type":"task","target_id":"foreign"}).status_code==404
        with SessionLocal() as db:
            user=db.scalar(select(User).where(User.email=="master@example.test"));user.role="VIEWER";db.get(SessionContext,digest("master-test")).audience="user";db.commit()
        assert client.get(f"/api/v1/documents/{doc['id']}/content").status_code==200
        assert upload_original(client).status_code==403
        assert client.patch(f"/api/v1/documents/{doc['id']}/archive",json={"archived":True}).status_code==403
        assert client.get(f"/api/v1/documents/{doc['id']}/files",headers={"X-Tenant-ID":"other"}).status_code==403

def test_document_migration_preserves_metadata_history(monkeypatch):
    from app.migrate_documents import apply
    with platform_client(monkeypatch) as client:
        before=client.get("/api/v1/documents").json()
        assert apply()==apply()
        assert client.get("/api/v1/documents").json()==before


def test_chunked_upload_is_bounded_before_multipart_spooling(monkeypatch):
    with platform_client(monkeypatch) as client:
        monkeypatch.setenv("DOCUMENT_MAX_SIZE_MB","1")
        boundary="setu-limit-boundary"
        metadata=json.dumps({"request_id":str(uuid4()),"organization_id":"org-udaan","name":"Oversized sample","category":"Sample"})
        prefix=("--"+boundary+"\r\nContent-Disposition: form-data; name=\"metadata\"\r\n\r\n"+metadata+"\r\n--"+boundary+"\r\nContent-Disposition: form-data; name=\"file\"; filename=\"proof.png\"\r\nContent-Type: image/png\r\n\r\n").encode()
        payload=prefix+b"x"*(2*1024*1024)+("\r\n--"+boundary+"--\r\n").encode()
        response=client.post("/api/v1/documents/upload",content=iter([payload]),headers={"Content-Type":"multipart/form-data; boundary="+boundary})
        assert response.status_code==413,response.text


def test_s3_private_upload_contract_checks_bucket_and_preserves_object_integrity():
    from app.integration_providers import S3Adapter
    from app.integration_security import IntegrationError
    adapter=S3Adapter({"bucket":"sample-private-bucket","prefix":"tenant/","region":"ap-south-1"},"unused")
    calls=[]
    def run(operation,**values):
        calls.append((operation,values))
        return {"PublicAccessBlockConfiguration":dict.fromkeys(("BlockPublicAcls","IgnorePublicAcls","BlockPublicPolicy","RestrictPublicBuckets"),True)}
    adapter._run=run;adapter.assert_private();adapter.upload_private("proof/content",b"sample","image/png")
    assert calls[-1][1]["IfNoneMatch"]=="*" and calls[-1][1]["ServerSideEncryption"]=="AES256"
    assert calls[-1][1]["Metadata"]["sha256"]==hashlib.sha256(b"sample").hexdigest()
    adapter._run=lambda *args,**kwargs:{"PublicAccessBlockConfiguration":{}}
    with pytest.raises(IntegrationError):adapter.assert_private()


def test_upload_storage_quota_and_unknown_metadata_are_enforced(monkeypatch):
    from app.models import Subscription
    with platform_client(monkeypatch) as client:
        with SessionLocal() as db:
            plan=db.scalar(select(Subscription).where(Subscription.tenant_id=="tenant-demo"));plan.storage_limit_gb=0;db.commit()
        assert upload_original(client).status_code==403
        assert upload_original(client,storage_key="../../public").status_code==422
        with SessionLocal() as db:assert db.scalars(select(DocumentBlob)).all()==[]
