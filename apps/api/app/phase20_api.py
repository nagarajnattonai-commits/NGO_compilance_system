"""Privileged APIs for staged, validated and explicitly confirmed bulk imports."""
from __future__ import annotations

import csv
import io
import json
from datetime import timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import AdminUser, get_db, tenant_context
from .models import AuditEvent
from .phase20_models import ImportJob, ImportRowResult, utcnow
from .phase20_service import (FIELDS, MAX_FILE_BYTES, authorized_job, csv_safe, execute_job,
                              job_payload, parse_upload, row_payload, suggested_mapping,
                              template_csv, validate_job)
from .production_security import limit_expensive

router = APIRouter(prefix="/api/v1/imports", tags=["Bulk onboarding imports"])
DB = Annotated[Session, Depends(get_db)]
Tenant = Annotated[str, Depends(tenant_context)]
ImportType = Literal["ORGANIZATIONS", "REGISTRATIONS", "INVITATIONS", "TASK_ASSIGNMENTS"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Resolution(Strict):
    action: Literal["CREATE", "MAP", "SKIP"]
    organization_id: str | None = Field(default=None, max_length=36)


class ValidationInput(Strict):
    expected_revision: int = Field(ge=0)
    mapping: dict[str, str] = Field(max_length=50)
    resolutions: dict[str, Resolution] = Field(default_factory=dict, max_length=1_000)

    @field_validator("resolutions")
    @classmethod
    def row_keys(cls, value):
        if any(not key.isdigit() or int(key) < 2 for key in value):
            raise ValueError("Resolution keys must be spreadsheet row numbers")
        return value


class ConfirmationInput(Strict):
    expected_revision: int = Field(ge=0)
    confirmation: Literal["CONFIRM IMPORT"]


def privileged(actor):
    if getattr(actor, "_admin_audience", False):
        raise HTTPException(403, "Platform administrator sessions cannot manage workspace imports")


def _not_expired(job: ImportJob):
    expires = job.expires_at
    if expires.tzinfo is None:
        from datetime import timezone
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= utcnow() and job.status not in {"COMPLETED", "COMPLETED_WITH_ERRORS"}:
        raise HTTPException(410, "Import job has expired; upload the file again")


@router.get("/templates/{import_type}")
def template(import_type: ImportType, actor: AdminUser):
    privileged(actor)
    content = template_csv(import_type)
    return Response(content, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="setu-{import_type.lower()}-import.csv"'})


@router.get("/schema/{import_type}")
def import_schema(import_type: ImportType, actor: AdminUser):
    privileged(actor)
    return {"import_type": import_type, "required": FIELDS[import_type]["required"],
            "optional": FIELDS[import_type]["optional"]}


@router.post("", status_code=201)
async def upload_import(db: DB, tenant_id: Tenant, actor: AdminUser,
                        import_type: ImportType = Form(...), file: UploadFile = File(...)):
    privileged(actor)
    limit_expensive(db, tenant_id, actor.id, "bulk-import-upload", 20)
    expired_ids = select(ImportJob.id).where(ImportJob.tenant_id == tenant_id, ImportJob.expires_at <= utcnow())
    db.execute(delete(ImportRowResult).where(ImportRowResult.job_id.in_(expired_ids)))
    db.execute(delete(ImportJob).where(ImportJob.tenant_id == tenant_id, ImportJob.expires_at <= utcnow()))
    db.flush()
    chunks, size = [], 0
    while chunk := await file.read(64 * 1024):
        size += len(chunk)
        if size > MAX_FILE_BYTES:
            raise HTTPException(413, "Import files are limited to 5 MB")
        chunks.append(chunk)
    filename, file_format, headers, rows, checksum = parse_upload(file.filename, file.content_type, b"".join(chunks))
    existing = db.scalar(select(ImportJob).where(
        ImportJob.tenant_id == tenant_id, ImportJob.import_type == import_type, ImportJob.file_sha256 == checksum,
    ))
    if existing:
        return {**job_payload(existing), "suggested_mapping": suggested_mapping(json.loads(existing.headers_json), import_type),
                "idempotent_replay": True}
    job = ImportJob(tenant_id=tenant_id, created_by=actor.id, import_type=import_type, status="UPLOADED",
                    filename=filename, file_format=file_format, file_sha256=checksum,
                    headers_json=json.dumps(headers), total_rows=len(rows),
                    expires_at=utcnow() + timedelta(days=7))
    db.add(job)
    try:
        db.flush()
        for number, source in enumerate(rows, start=2):
            db.add(ImportRowResult(job_id=job.id, tenant_id=tenant_id, row_number=number,
                                   source_json=json.dumps(source, separators=(",", ":"))))
        db.add(AuditEvent(tenant_id=tenant_id, actor_name=actor.name, action="IMPORT_CREATED",
                          entity_type="ImportJob", entity_id=job.id,
                          summary=f"Created {import_type.lower()} import with {len(rows)} rows from {file_format}"))
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(ImportJob).where(
            ImportJob.tenant_id == tenant_id, ImportJob.import_type == import_type, ImportJob.file_sha256 == checksum,
        ))
        if not existing:
            raise HTTPException(409, "Import upload conflicted; retry safely") from None
        job = existing
    return {**job_payload(job), "suggested_mapping": suggested_mapping(headers, import_type), "idempotent_replay": False}


@router.get("/{job_id}")
def get_import(job_id: str, db: DB, tenant_id: Tenant, actor: AdminUser):
    privileged(actor)
    job = authorized_job(db, tenant_id, job_id)
    _not_expired(job)
    return job_payload(job)


@router.post("/{job_id}/validate")
def dry_run(job_id: str, payload: ValidationInput, db: DB, tenant_id: Tenant, actor: AdminUser):
    privileged(actor)
    limit_expensive(db, tenant_id, actor.id, "bulk-import-validate", 30)
    job = authorized_job(db, tenant_id, job_id, lock=True)
    _not_expired(job)
    if job.revision != payload.expected_revision:
        raise HTTPException(409, "Import changed; reload before validating")
    return validate_job(db, tenant_id, actor, job, payload.mapping,
                        {key: value.model_dump() for key, value in payload.resolutions.items()})


@router.post("/{job_id}/confirm")
def confirm_import(job_id: str, payload: ConfirmationInput, db: DB, tenant_id: Tenant, actor: AdminUser):
    privileged(actor)
    limit_expensive(db, tenant_id, actor.id, "bulk-import-confirm", 10)
    job = authorized_job(db, tenant_id, job_id, lock=True)
    _not_expired(job)
    if job.status not in {"COMPLETED", "COMPLETED_WITH_ERRORS"} and job.revision != payload.expected_revision:
        raise HTTPException(409, "Import changed; reload before confirmation")
    return execute_job(db, tenant_id, actor, job)


@router.post("/{job_id}/cancel")
def cancel_import(job_id: str, db: DB, tenant_id: Tenant, actor: AdminUser):
    privileged(actor)
    job = authorized_job(db, tenant_id, job_id, lock=True)
    if job.status in {"IMPORTING", "COMPLETED", "COMPLETED_WITH_ERRORS"}:
        raise HTTPException(409, "This import can no longer be cancelled")
    job.status, job.updated_at = "CANCELLED", utcnow()
    db.add(AuditEvent(tenant_id=tenant_id, actor_name=actor.name, action="IMPORT_CANCELLED",
                      entity_type="ImportJob", entity_id=job.id, summary="Cancelled bulk import before execution"))
    db.commit()
    return job_payload(job)


@router.get("/{job_id}/results")
def results(job_id: str, db: DB, tenant_id: Tenant, actor: AdminUser):
    privileged(actor)
    job = authorized_job(db, tenant_id, job_id)
    rows = list(db.scalars(select(ImportRowResult).where(
        ImportRowResult.job_id == job.id, ImportRowResult.tenant_id == tenant_id,
    ).order_by(ImportRowResult.row_number)).all())
    return {**job_payload(job), "rows": [row_payload(row) for row in rows]}


@router.get("/{job_id}/results.csv")
def result_csv(job_id: str, db: DB, tenant_id: Tenant, actor: AdminUser):
    privileged(actor)
    job = authorized_job(db, tenant_id, job_id)
    rows = list(db.scalars(select(ImportRowResult).where(
        ImportRowResult.job_id == job.id, ImportRowResult.tenant_id == tenant_id,
    ).order_by(ImportRowResult.row_number)).all())
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(("row_number", "result", "errors", "warnings", "entity_id"))
    for row in rows:
        errors = "; ".join(item.get("message", "") for item in json.loads(row.errors_json))
        warnings = "; ".join(item.get("message", "") for item in json.loads(row.warnings_json))
        writer.writerow([csv_safe(value) for value in (row.row_number, row.status, errors, warnings, row.created_entity_id or row.existing_organization_id or "")])
    return Response(output.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="setu-import-{job.id}-results.csv"'})
