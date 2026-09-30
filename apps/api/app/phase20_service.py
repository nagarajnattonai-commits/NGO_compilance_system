"""Safe parsing, dry-run validation and row-atomic execution for Phase 20 imports."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from pathlib import PurePath
from xml.etree import ElementTree

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, or_, select

from .auth_models import WorkspaceAccess
from .features import require_active_subscription, subscription_usage
from .models import AuditEvent, Membership, Notification, Organization, Task, User
from .onboarding_models import OrganizationOnboarding
from .organization_access import accessible_organization_ids
from .organization_models import OrganizationDetails, OrganizationRegistration
from .organization_profile import DetailsInput, RegistrationInput
from .phase20_models import ImportJob, ImportRowResult, utcnow
from .phase8_api import notify_task
from .phase8_models import OrganizationAccess
from .schemas import MembershipCreate, OrganizationCreate

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 1_000
MAX_COLUMNS = 50
MAX_CELL_CHARS = 2_000
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

FIELDS = {
    "ORGANIZATIONS": {
        "required": ("name", "legal_type", "registration_number", "city"),
        "optional": ("pan", "fcra_active", "tan", "address_line_1", "address_line_2", "district", "state",
                     "postal_code", "contact_name", "contact_email", "contact_phone", "website",
                     "registration_kind", "registration_status", "registration_identifier", "registration_expiry_date",
                     "responsible_consultant_email"),
    },
    "REGISTRATIONS": {
        "required": ("organization_id", "kind", "status"),
        "optional": ("number", "registration_date", "effective_date", "expiry_date", "renewal_status"),
    },
    "INVITATIONS": {
        "required": ("organization_id", "name", "email", "role"),
        "optional": (),
    },
    "TASK_ASSIGNMENTS": {
        "required": ("task_id", "assignee_email"),
        "optional": (),
    },
}


def supported_fields(import_type: str) -> tuple[str, ...]:
    schema = FIELDS.get(import_type)
    if not schema:
        raise HTTPException(422, "Unsupported import type")
    return schema["required"] + schema["optional"]


def safe_filename(filename: str | None) -> str:
    name = PurePath((filename or "import").replace("\\", "/")).name
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip(" .")
    return (name or "import")[:200]


def _bounded_text(value: object) -> str:
    text = "" if value is None else str(value).strip()
    if len(text) > MAX_CELL_CHARS:
        raise ValueError("Cell exceeds the 2000 character limit")
    return text


def _matrix_to_rows(matrix: list[list[str]]) -> tuple[list[str], list[dict[str, str]]]:
    if not matrix:
        raise HTTPException(422, "The import file is empty")
    headers = [_bounded_text(value) for value in matrix[0]]
    while headers and not headers[-1]:
        headers.pop()
    if not headers or len(headers) > MAX_COLUMNS or any(not value for value in headers):
        raise HTTPException(422, "The header row is missing, blank, or exceeds the column limit")
    if len({value.casefold() for value in headers}) != len(headers):
        raise HTTPException(422, "Column headers must be unique")
    rows = []
    for values in matrix[1:]:
        values = values[:len(headers)] + [""] * max(0, len(headers) - len(values))
        normalized = [_bounded_text(value) for value in values]
        if any(normalized):
            rows.append(dict(zip(headers, normalized)))
    if not rows:
        raise HTTPException(422, "The import file contains no data rows")
    if len(rows) > MAX_ROWS:
        raise HTTPException(413, f"Imports are limited to {MAX_ROWS} rows")
    return headers, rows


def parse_csv(data: bytes) -> tuple[list[str], list[dict[str, str]]]:
    try:
        text = data.decode("utf-8-sig", errors="strict")
        matrix = [row for row in csv.reader(io.StringIO(text, newline=""))]
    except (UnicodeDecodeError, csv.Error) as error:
        raise HTTPException(422, "Malformed UTF-8 CSV file") from error
    if any(len(row) > MAX_COLUMNS for row in matrix):
        raise HTTPException(422, f"Imports are limited to {MAX_COLUMNS} columns")
    return _matrix_to_rows(matrix)


def _xlsx_cell_value(cell, shared: list[str], namespace: str) -> str:
    if cell.find(f"{namespace}f") is not None:
        raise HTTPException(422, "Spreadsheet formulas are not allowed")
    kind = cell.attrib.get("t", "")
    if kind == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(f".//{namespace}t"))
    value = cell.find(f"{namespace}v")
    raw = value.text if value is not None and value.text is not None else ""
    if kind == "s" and raw:
        try:
            return shared[int(raw)]
        except (ValueError, IndexError) as error:
            raise HTTPException(422, "Malformed shared string reference") from error
    if kind == "b":
        return "true" if raw == "1" else "false"
    return raw


def parse_xlsx(data: bytes) -> tuple[list[str], list[dict[str, str]]]:
    if not data.startswith(b"PK"):
        raise HTTPException(422, "Malformed XLSX file")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
            if len(names) > 200 or any(name.lower().endswith("vbaproject.bin") or "externallinks/" in name.lower() for name in names):
                raise HTTPException(422, "Macros and external workbook links are not allowed")
            if sum(item.file_size for item in archive.infolist()) > 20 * 1024 * 1024:
                raise HTTPException(413, "Expanded workbook exceeds the safety limit")
            shared: list[str] = []
            if "xl/sharedStrings.xml" in names:
                root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
                namespace = "{" + root.tag.split("}")[0].lstrip("{") + "}" if "}" in root.tag else ""
                shared = ["".join(node.text or "" for node in item.findall(f".//{namespace}t")) for item in root]
            sheets = sorted(name for name in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name))
            if not sheets:
                raise HTTPException(422, "Workbook contains no readable worksheet")
            root = ElementTree.fromstring(archive.read(sheets[0]))
            namespace = "{" + root.tag.split("}")[0].lstrip("{") + "}" if "}" in root.tag else ""
            matrix: list[list[str]] = []
            for row in root.findall(f".//{namespace}row"):
                values: dict[int, str] = {}
                for cell in row.findall(f"{namespace}c"):
                    reference = cell.attrib.get("r", "A1")
                    letters = re.match(r"[A-Z]+", reference.upper())
                    if not letters:
                        raise HTTPException(422, "Malformed workbook cell reference")
                    index = 0
                    for letter in letters.group(0):
                        index = index * 26 + ord(letter) - 64
                    if index > MAX_COLUMNS:
                        raise HTTPException(422, f"Imports are limited to {MAX_COLUMNS} columns")
                    values[index - 1] = _xlsx_cell_value(cell, shared, namespace)
                matrix.append([values.get(index, "") for index in range(max(values, default=-1) + 1)])
                if len(matrix) > MAX_ROWS + 1:
                    raise HTTPException(413, f"Imports are limited to {MAX_ROWS} rows")
            return _matrix_to_rows(matrix)
    except HTTPException:
        raise
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as error:
        raise HTTPException(422, "Malformed XLSX file") from error


def parse_upload(filename: str | None, content_type: str | None, data: bytes):
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(413, "Import files are limited to 5 MB")
    name = safe_filename(filename)
    extension = PurePath(name).suffix.lower()
    allowed_types = {
        ".csv": {"text/csv", "application/csv", "text/plain", "application/vnd.ms-excel", "application/octet-stream", ""},
        ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/octet-stream", ""},
    }
    if extension not in allowed_types or (content_type or "").lower() not in allowed_types[extension]:
        raise HTTPException(415, "Only CSV and XLSX imports are supported")
    headers, rows = parse_csv(data) if extension == ".csv" else parse_xlsx(data)
    return name, extension.lstrip(".").upper(), headers, rows, hashlib.sha256(data).hexdigest()


def suggested_mapping(headers: list[str], import_type: str) -> dict[str, str]:
    normalized = {re.sub(r"[^a-z0-9]", "", value.casefold()): value for value in headers}
    suggestions = {}
    for field in supported_fields(import_type):
        key = re.sub(r"[^a-z0-9]", "", field.casefold())
        if key in normalized:
            suggestions[field] = normalized[key]
    return suggestions


def template_csv(import_type: str) -> str:
    fields = supported_fields(import_type)
    examples = {
        "ORGANIZATIONS": ("Example Foundation", "TRUST", "REG-EXAMPLE-001", "Bengaluru"),
        "REGISTRATIONS": ("organization-id", "80G", "ACTIVE"),
        "INVITATIONS": ("organization-id", "Client User", "client@example.test", "VIEWER"),
        "TASK_ASSIGNMENTS": ("task-id", "consultant@example.test"),
    }
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(fields)
    example = list(examples[import_type]) + [""] * (len(fields) - len(examples[import_type]))
    writer.writerow(example)
    return output.getvalue()


def csv_safe(value: object) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_PREFIXES) else text


def _field_errors(error: ValidationError) -> list[dict]:
    return [{"field": ".".join(str(part) for part in item["loc"]), "message": item["msg"]} for item in error.errors()]


def _registration_payload(values: dict[str, str]) -> dict:
    return {
        "kind": values.get("kind") or values.get("registration_kind"),
        "status": values.get("status") or values.get("registration_status") or "UNKNOWN",
        "number": values.get("number") or values.get("registration_identifier") or "",
        "registration_date": values.get("registration_date") or None,
        "effective_date": values.get("effective_date") or None,
        "expiry_date": values.get("expiry_date") or values.get("registration_expiry_date") or None,
        "renewal_status": values.get("renewal_status") or "UNKNOWN",
    }


def job_payload(job: ImportJob) -> dict:
    return {
        "id": job.id, "import_type": job.import_type, "status": job.status, "filename": job.filename,
        "file_format": job.file_format, "headers": json.loads(job.headers_json), "mapping": json.loads(job.mapping_json),
        "total_rows": job.total_rows, "valid_rows": job.valid_rows, "invalid_rows": job.invalid_rows,
        "warnings": job.warning_count, "created": job.created_count, "mapped": job.mapped_count,
        "skipped": job.skipped_count, "failed": job.failed_count, "revision": job.revision,
        "created_at": job.created_at, "updated_at": job.updated_at, "completed_at": job.completed_at,
    }


def row_payload(row: ImportRowResult) -> dict:
    return {
        "row_number": row.row_number, "status": row.status, "resolution": row.resolution,
        "existing_organization_id": row.existing_organization_id, "created_entity_id": row.created_entity_id,
        "errors": json.loads(row.errors_json), "warnings": json.loads(row.warnings_json),
    }


def authorized_job(db, tenant_id: str, job_id: str, *, lock: bool = False) -> ImportJob:
    statement = select(ImportJob).where(ImportJob.id == job_id, ImportJob.tenant_id == tenant_id)
    if lock:
        statement = statement.with_for_update()
    job = db.scalar(statement)
    if not job:
        raise HTTPException(404, "Import job not found")
    return job


def _accessible_ids(db, tenant_id: str, actor) -> set[str] | None:
    allowed = accessible_organization_ids(db, tenant_id, actor.id)
    return allowed


def _organization_lookup(db, tenant_id: str, actor):
    statement = select(Organization).where(Organization.tenant_id == tenant_id, Organization.status != "ARCHIVED")
    allowed = _accessible_ids(db, tenant_id, actor)
    if allowed is not None:
        statement = statement.where(Organization.id.in_(allowed))
    rows = list(db.scalars(statement).all())
    return rows, {row.id: row for row in rows}


def _workspace_users(db, tenant_id: str) -> dict[str, User]:
    own = list(db.scalars(select(User).where(User.tenant_id == tenant_id, User.status == "ACTIVE")).all())
    joined = list(db.scalars(select(User).join(WorkspaceAccess, WorkspaceAccess.user_id == User.id).where(
        WorkspaceAccess.tenant_id == tenant_id, WorkspaceAccess.active.is_(True), User.status == "ACTIVE",
    )).all())
    return {user.email.casefold(): user for user in own + joined}


def _eligible_user_ids(db, tenant_id: str, organization_ids: set[str], users: dict[str, User]) -> dict[str, set[str]]:
    user_ids = {user.id for user in users.values()}
    roles = {user.id: user.role for user in users.values() if user.tenant_id == tenant_id}
    roles.update(dict(db.execute(select(WorkspaceAccess.user_id, WorkspaceAccess.role).where(
        WorkspaceAccess.tenant_id == tenant_id, WorkspaceAccess.active.is_(True),
        WorkspaceAccess.user_id.in_(user_ids),
    )).all()))
    has_explicit_access = bool(db.scalar(select(OrganizationAccess.id).where(
        OrganizationAccess.tenant_id == tenant_id,
    ).limit(1)))
    access = set(db.execute(select(OrganizationAccess.organization_id, OrganizationAccess.user_id).where(
        OrganizationAccess.tenant_id == tenant_id, OrganizationAccess.organization_id.in_(organization_ids),
        OrganizationAccess.user_id.in_(user_ids), OrganizationAccess.status == "ACTIVE",
    )).all()) if has_explicit_access else set()
    return {organization_id: {
        user_id for user_id, role in roles.items()
        if role != "VIEWER" and (role == "ADMIN" or not has_explicit_access or (organization_id, user_id) in access)
    } for organization_id in organization_ids}


def validate_job(db, tenant_id: str, actor, job: ImportJob, mapping: dict[str, str], resolutions: dict[str, dict]) -> dict:
    if job.status in {"IMPORTING", "COMPLETED", "COMPLETED_WITH_ERRORS", "CANCELLED"}:
        raise HTTPException(409, "This import can no longer be validated")
    supported = set(supported_fields(job.import_type))
    headers = set(json.loads(job.headers_json))
    if set(mapping) - supported or set(mapping.values()) - headers or len(set(mapping.values())) != len(mapping):
        raise HTTPException(422, "Field mapping contains unsupported, unknown, or duplicate columns")
    missing = set(FIELDS[job.import_type]["required"]) - set(mapping)
    if missing:
        raise HTTPException(422, "Missing required field mappings: " + ", ".join(sorted(missing)))
    organizations, organizations_by_id = _organization_lookup(db, tenant_id, actor)
    users = _workspace_users(db, tenant_id)
    by_registration = {row.registration_number.casefold(): row for row in organizations if row.registration_number}
    by_pan = {row.pan.casefold(): row for row in organizations if row.pan}
    by_name: dict[str, list[Organization]] = {}
    for organization in organizations:
        by_name.setdefault(" ".join(organization.name.casefold().split()), []).append(organization)
    source_rows = list(db.scalars(select(ImportRowResult).where(
        ImportRowResult.job_id == job.id, ImportRowResult.tenant_id == tenant_id,
    ).order_by(ImportRowResult.row_number)).all())
    task_ids = {json.loads(row.source_json).get(mapping.get("task_id", ""), "") for row in source_rows}
    tasks = {task.id: task for task in db.scalars(select(Task).where(
        Task.tenant_id == tenant_id, Task.id.in_(task_ids), Task.archived_at.is_(None),
    )).all()} if task_ids else {}
    eligible_by_organization = _eligible_user_ids(db, tenant_id, {task.organization_id for task in tasks.values()}, users)
    existing_registration_keys = set(db.execute(select(
        OrganizationRegistration.organization_id, OrganizationRegistration.kind,
    ).where(OrganizationRegistration.tenant_id == tenant_id,
            OrganizationRegistration.organization_id.in_(organizations_by_id))).all())
    existing_members = set(db.scalars(select(func.lower(Membership.email)).where(
        Membership.tenant_id == tenant_id, Membership.status != "INACTIVE",
    )).all())
    seen_identifiers: set[tuple[str, str]] = set()
    valid_count = invalid_count = warning_count = 0
    for row in source_rows:
        source = json.loads(row.source_json)
        values = {field: source[column].strip() for field, column in mapping.items()}
        errors: list[dict] = []
        warnings: list[dict] = []
        resolution = resolutions.get(str(row.row_number), {})
        action = str(resolution.get("action", "")).upper()
        existing_id = resolution.get("organization_id")
        try:
            if any(value.startswith(FORMULA_PREFIXES) for value in values.values() if value):
                raise ValueError("Formula-like cell values are not allowed")
            if job.import_type == "ORGANIZATIONS":
                core = OrganizationCreate.model_validate({
                    "name": values.get("name"), "legal_type": values.get("legal_type"),
                    "registration_number": values.get("registration_number"), "city": values.get("city"),
                    "pan": values.get("pan", ""), "fcra_active": values.get("fcra_active", "").casefold() in {"true", "yes", "1"},
                    "generate_compliance_plan": False,
                })
                detail_values = {field: values[field] for field in DetailsInput.model_fields if values.get(field)}
                if detail_values:
                    DetailsInput.model_validate(detail_values)
                if values.get("registration_kind"):
                    RegistrationInput.model_validate(_registration_payload(values))
                consultant_email = values.get("responsible_consultant_email", "").casefold()
                if consultant_email and consultant_email not in users:
                    errors.append({"field": "responsible_consultant_email", "message": "Unknown workspace consultant"})
                candidate = by_registration.get(core.registration_number.casefold()) or (by_pan.get(core.pan.casefold()) if core.pan else None)
                ambiguous = by_name.get(" ".join(core.name.casefold().split()), [])
                if candidate or ambiguous:
                    candidates = [candidate] if candidate else ambiguous
                    warnings.append({"field": "duplicate", "message": "Existing organization candidate requires explicit resolution",
                                     "candidates": [{"id": item.id, "name": item.name} for item in candidates if item]})
                    if action not in ({"MAP", "SKIP"} if candidate else {"MAP", "SKIP", "CREATE"}):
                        errors.append({"field": "resolution", "message": "Choose map, skip, or an explicitly allowed create action"})
                    elif action == "MAP" and existing_id not in {item.id for item in candidates if item}:
                        errors.append({"field": "resolution.organization_id", "message": "Mapped organization is not an authorized duplicate candidate"})
                elif action and action not in {"CREATE", "SKIP"}:
                    errors.append({"field": "resolution", "message": "This row can only be created or skipped"})
                identifier = (core.registration_number.casefold(), core.pan.casefold())
                if identifier in seen_identifiers:
                    errors.append({"field": "registration_number", "message": "Duplicate organization identifier within this file"})
                seen_identifiers.add(identifier)
                if not detail_values:
                    warnings.append({"field": "profile", "message": "Applicability remains review-required until onboarding facts are completed"})
            elif job.import_type == "REGISTRATIONS":
                organization = organizations_by_id.get(values.get("organization_id", ""))
                if not organization:
                    errors.append({"field": "organization_id", "message": "Organization is not available in the authorized workspace scope"})
                RegistrationInput.model_validate(_registration_payload(values))
                if organization and (organization.id, values.get("kind")) in existing_registration_keys:
                    warnings.append({"field": "kind", "message": "Registration already exists and will be mapped without overwrite"})
            elif job.import_type == "INVITATIONS":
                organization = organizations_by_id.get(values.get("organization_id", ""))
                if not organization:
                    errors.append({"field": "organization_id", "message": "Organization is not available in the authorized workspace scope"})
                invitation = MembershipCreate.model_validate(values)
                if invitation.email.casefold() in existing_members:
                    errors.append({"field": "email", "message": "An active or pending membership already exists"})
            else:
                task = tasks.get(values.get("task_id", ""))
                assignee = users.get(values.get("assignee_email", "").casefold())
                if not task or task.organization_id not in organizations_by_id:
                    errors.append({"field": "task_id", "message": "Task is not available in the authorized workspace scope"})
                if not assignee:
                    errors.append({"field": "assignee_email", "message": "Unknown workspace assignee"})
                elif task and assignee.id not in eligible_by_organization.get(task.organization_id, set()):
                    errors.append({"field": "assignee_email", "message": "Assignee is not authorized for the task organization"})
        except ValidationError as error:
            errors.extend(_field_errors(error))
        except (ValueError, TypeError) as error:
            errors.append({"field": "row", "message": str(error)})
        row.normalized_json = json.dumps(values, separators=(",", ":"))
        row.resolution = action
        row.existing_organization_id = str(existing_id) if existing_id else None
        row.errors_json = json.dumps(errors, separators=(",", ":"))
        row.warnings_json = json.dumps(warnings, separators=(",", ":"))
        row.status = "INVALID" if errors else "VALID"
        row.updated_at = utcnow()
        valid_count += not errors
        invalid_count += bool(errors)
        warning_count += len(warnings)
    job.mapping_json = json.dumps(mapping, separators=(",", ":"))
    job.valid_rows, job.invalid_rows, job.warning_count = valid_count, invalid_count, warning_count
    job.status = "READY" if not invalid_count else "VALIDATION_FAILED"
    job.revision += 1
    job.updated_at = utcnow()
    db.add(AuditEvent(tenant_id=tenant_id, actor_name=actor.name, action="IMPORT_VALIDATION_COMPLETED",
                      entity_type="ImportJob", entity_id=job.id,
                      summary=f"Validated {job.total_rows} rows: {valid_count} valid, {invalid_count} invalid, {warning_count} warnings"))
    db.commit()
    return {**job_payload(job), "rows": [row_payload(row) for row in source_rows]}


def enforce_batch_capacity(db, tenant_id: str, import_type: str, count: int) -> None:
    subscription = require_active_subscription(db, tenant_id)
    if not subscription:
        return
    resource = "organizations" if import_type == "ORGANIZATIONS" else "users" if import_type == "INVITATIONS" else None
    if not resource:
        return
    used = int(subscription_usage(db, tenant_id)[resource])
    limit = subscription.organization_limit if resource == "organizations" else subscription.user_limit
    if used + count > limit:
        raise HTTPException(403, f"PLAN_LIMIT_REACHED:{resource}")


def _create_organization(db, tenant_id: str, actor, row: ImportRowResult, values: dict,
                         users: dict[str, User]) -> tuple[str, str]:
    if row.resolution == "SKIP":
        return "SKIPPED", ""
    if row.resolution == "MAP":
        return "MAPPED", row.existing_organization_id or ""
    core = OrganizationCreate.model_validate({
        "name": values["name"], "legal_type": values["legal_type"], "registration_number": values["registration_number"],
        "city": values["city"], "pan": values.get("pan", ""),
        "fcra_active": values.get("fcra_active", "").casefold() in {"true", "yes", "1"}, "generate_compliance_plan": False,
    })
    duplicate_checks = [func.lower(Organization.registration_number) == core.registration_number.lower()]
    if core.pan:
        duplicate_checks.append(func.lower(Organization.pan) == core.pan.lower())
    if db.scalar(select(Organization.id).where(Organization.tenant_id == tenant_id, or_(*duplicate_checks)).limit(1)):
        raise ValueError("Organization identifiers became duplicate after validation; validate again")
    organization = Organization(tenant_id=tenant_id, status="ACTIVE", **core.model_dump(exclude={"generate_compliance_plan"}))
    db.add(organization); db.flush()
    detail_values = {field: values[field] for field in DetailsInput.model_fields if values.get(field)}
    db.add(OrganizationDetails(organization_id=organization.id, tenant_id=tenant_id, revision=0,
                               facts=DetailsInput.model_validate(detail_values).model_dump_json(), updated_by=actor.id))
    if values.get("registration_kind"):
        registration = RegistrationInput.model_validate(_registration_payload(values))
        db.add(OrganizationRegistration(tenant_id=tenant_id, organization_id=organization.id, **registration.model_dump()))
        if registration.kind == "FCRA" and registration.status != "UNKNOWN":
            organization.fcra_active = registration.status == "ACTIVE"
    db.add(OrganizationOnboarding(organization_id=organization.id, tenant_id=tenant_id, current_step="basics",
                                  completed_steps='["welcome"]', status="IN_PROGRESS", updated_by=actor.id))
    consultant = users.get(values.get("responsible_consultant_email", "").casefold())
    if consultant:
        db.add(OrganizationAccess(tenant_id=tenant_id, organization_id=organization.id, user_id=consultant.id,
                                  access_role="MANAGER", status="ACTIVE", granted_by=actor.id))
    db.add(AuditEvent(tenant_id=tenant_id, actor_name=actor.name, action="ORGANIZATION_CREATED",
                      entity_type="Organization", entity_id=organization.id,
                      summary=f"Created {organization.name} through import {row.job_id}"))
    db.add(AuditEvent(tenant_id=tenant_id, actor_name=actor.name, action="ONBOARDING_STARTED",
                      entity_type="Organization", entity_id=organization.id,
                      summary="Started organization onboarding from validated import"))
    return "CREATED", organization.id


def _apply_row(db, tenant_id: str, actor, job: ImportJob, row: ImportRowResult,
               users: dict[str, User], authorized_organization_ids: set[str],
               eligible_by_organization: dict[str, set[str]]) -> tuple[str, str]:
    values = json.loads(row.normalized_json)
    if job.import_type == "ORGANIZATIONS":
        return _create_organization(db, tenant_id, actor, row, values, users)
    if job.import_type == "REGISTRATIONS":
        if values["organization_id"] not in authorized_organization_ids:
            raise ValueError("Organization is no longer available in the authorized workspace scope")
        existing = db.scalar(select(OrganizationRegistration).where(
            OrganizationRegistration.tenant_id == tenant_id,
            OrganizationRegistration.organization_id == values["organization_id"],
            OrganizationRegistration.kind == values["kind"],
        ))
        if existing:
            return "MAPPED", existing.id
        registration = RegistrationInput.model_validate(_registration_payload(values))
        entity = OrganizationRegistration(tenant_id=tenant_id, organization_id=values["organization_id"], **registration.model_dump())
        db.add(entity); db.flush()
        return "CREATED", entity.id
    if job.import_type == "INVITATIONS":
        payload = MembershipCreate.model_validate(values)
        if not payload.organization_id or payload.organization_id not in authorized_organization_ids:
            raise ValueError("Organization is no longer available in the authorized workspace scope")
        if db.scalar(select(Membership.id).where(
            Membership.tenant_id == tenant_id, func.lower(Membership.email) == payload.email.lower(),
            Membership.status != "INACTIVE",
        )):
            raise ValueError("An active or pending membership now exists; validate again")
        entity = Membership(tenant_id=tenant_id, **payload.model_dump(), status="INVITED")
        db.add(entity); db.flush()
        return "CREATED", entity.id
    task = db.scalar(select(Task).where(Task.id == values["task_id"], Task.tenant_id == tenant_id).with_for_update())
    assignee = users.get(values["assignee_email"].casefold())
    if not task or not assignee:
        raise ValueError("Task or assignee is no longer available")
    if task.organization_id not in authorized_organization_ids or assignee.id not in eligible_by_organization.get(task.organization_id, set()):
        raise ValueError("Task assignment authorization changed; validate again")
    task.assignee_user_id, task.assignee_name = assignee.id, assignee.name
    task.assignee_initials = "".join(part[0] for part in assignee.name.split())[:2].upper()
    task.assigned_by, task.assigned_at, task.updated_at = actor.id, utcnow(), utcnow()
    notify_task(db, task, event_type="TASK_REASSIGNED", title="Task reassigned",
                message=f"{task.title} is now assigned to you.", user_ids=[assignee.id])
    return "MAPPED", task.id


def execute_job(db, tenant_id: str, actor, job: ImportJob) -> dict:
    if job.status in {"COMPLETED", "COMPLETED_WITH_ERRORS"}:
        rows = list(db.scalars(select(ImportRowResult).where(ImportRowResult.job_id == job.id).order_by(ImportRowResult.row_number)).all())
        return {**job_payload(job), "rows": [row_payload(row) for row in rows], "already_completed": True}
    if job.status != "READY" or job.invalid_rows:
        raise HTTPException(409, "Import must have a successful dry run before confirmation")
    rows = list(db.scalars(select(ImportRowResult).where(
        ImportRowResult.job_id == job.id, ImportRowResult.tenant_id == tenant_id,
    ).order_by(ImportRowResult.row_number)).all())
    create_count = sum(row.resolution not in {"MAP", "SKIP"} for row in rows)
    enforce_batch_capacity(db, tenant_id, job.import_type, create_count)
    job.status, job.confirmed_at, job.updated_at = "IMPORTING", utcnow(), utcnow()
    db.add(AuditEvent(tenant_id=tenant_id, actor_name=actor.name, action="IMPORT_CONFIRMED",
                      entity_type="ImportJob", entity_id=job.id, summary=f"Confirmed import of {job.total_rows} validated rows"))
    db.commit()
    counts = {"CREATED": 0, "MAPPED": 0, "SKIPPED": 0, "FAILED": 0}
    users = _workspace_users(db, tenant_id)
    organizations, _ = _organization_lookup(db, tenant_id, actor)
    authorized_organization_ids = {organization.id for organization in organizations}
    task_ids = {json.loads(row.normalized_json).get("task_id", "") for row in rows} if job.import_type == "TASK_ASSIGNMENTS" else set()
    task_organizations = set(db.scalars(select(Task.organization_id).where(
        Task.tenant_id == tenant_id, Task.id.in_(task_ids), Task.archived_at.is_(None),
    )).all()) if task_ids else set()
    eligible_by_organization = _eligible_user_ids(db, tenant_id, task_organizations, users)
    for pending in rows:
        row = db.scalar(select(ImportRowResult).where(ImportRowResult.id == pending.id, ImportRowResult.tenant_id == tenant_id))
        if row.status in {"CREATED", "MAPPED", "SKIPPED"}:
            counts[row.status] += 1
            continue
        try:
            result, entity_id = _apply_row(db, tenant_id, actor, job, row, users,
                                           authorized_organization_ids, eligible_by_organization)
            row.status, row.created_entity_id, row.updated_at = result, entity_id or None, utcnow()
            db.add(AuditEvent(tenant_id=tenant_id, actor_name=actor.name,
                              action="IMPORT_ROW_" + result, entity_type=job.import_type, entity_id=entity_id or job.id,
                              summary=f"Import {job.id} row {row.row_number}: {result.lower()}"))
            db.commit()
            counts[result] += 1
        except Exception as error:
            db.rollback()
            row = db.get(ImportRowResult, pending.id)
            if isinstance(error, ValidationError):
                message = "; ".join(item["msg"] for item in error.errors())
            elif isinstance(error, ValueError):
                message = str(error)
            else:
                message = "Row could not be imported safely"
            row.status, row.errors_json, row.updated_at = "FAILED", json.dumps([{
                "field": "row", "message": message,
            }]), utcnow()
            db.commit()
            counts["FAILED"] += 1
    job = authorized_job(db, tenant_id, job.id, lock=True)
    job.created_count, job.mapped_count = counts["CREATED"], counts["MAPPED"]
    job.skipped_count, job.failed_count = counts["SKIPPED"], counts["FAILED"]
    job.status = "COMPLETED_WITH_ERRORS" if counts["FAILED"] else "COMPLETED"
    job.completed_at = job.updated_at = utcnow()
    db.add(AuditEvent(tenant_id=tenant_id, actor_name=actor.name, action="IMPORT_COMPLETED" if not counts["FAILED"] else "IMPORT_FAILED",
                      entity_type="ImportJob", entity_id=job.id,
                      summary=f"Import completed: {counts['CREATED']} created, {counts['MAPPED']} mapped, {counts['SKIPPED']} skipped, {counts['FAILED']} failed"))
    db.add(Notification(tenant_id=tenant_id, title="Bulk import completed",
                        message=f"{job.filename}: {counts['CREATED']} created, {counts['FAILED']} failed.",
                        kind="WARNING" if counts["FAILED"] else "SUCCESS"))
    db.commit()
    completed_rows = list(db.scalars(select(ImportRowResult).where(ImportRowResult.job_id == job.id).order_by(ImportRowResult.row_number)).all())
    return {**job_payload(job), "rows": [row_payload(row) for row in completed_rows], "already_completed": False}
