"""Read-only management reporting API."""
from datetime import date
import csv
import io
import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response

from .auth import CurrentUser
from .features import can_use_feature
from .organization_profile import DB, Tenant
from .reporting_service import compliance_report_count, compliance_report_rows, management_analytics

router = APIRouter(prefix="/api/v1/reports", tags=["Management reporting"])


def _report_rows(db, tenant, user, organization_id, category, status, owner, priority,
                 date_from, date_to, limit, offset):
    return compliance_report_rows(
        db, tenant, user, organization_id=organization_id, category=category,
        status=status, owner=owner, priority=priority, date_from=date_from,
        date_to=date_to, limit=limit, offset=offset,
    )


def _csv_value(value) -> str:
    if isinstance(value, (list, dict)):
        value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


@router.get("/analytics")
def analytics(
    db: DB,
    tenant: Tenant,
    user: CurrentUser,
    organization_id: str | None = None,
    category: str | None = Query(default=None, max_length=60),
    status: str | None = Query(default=None, max_length=30),
    owner: str | None = Query(default=None, max_length=120),
    priority: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    horizon_days: Literal["7", "30", "60", "90"] = "30",
):
    return management_analytics(
        db, tenant, user, organization_id=organization_id, category=category,
        status=status, owner=owner, priority=priority, date_from=date_from,
        date_to=date_to, horizon_days=int(horizon_days),
    )


@router.get("/compliance")
def compliance_report(
    db: DB,
    tenant: Tenant,
    user: CurrentUser,
    organization_id: str | None = None,
    category: str | None = Query(default=None, max_length=60),
    status: str | None = Query(default=None, max_length=30),
    owner: str | None = Query(default=None, max_length=120),
    priority: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    rows = _report_rows(db, tenant, user, organization_id, category, status, owner,
                        priority, date_from, date_to, limit, offset)
    total = compliance_report_count(
        db, tenant, user, organization_id=organization_id, category=category,
        status=status, owner=owner, priority=priority, date_from=date_from, date_to=date_to,
    )
    return {"rows": rows, "total": total, "limit": limit, "offset": offset}


@router.get("/compliance.csv")
def compliance_csv(
    db: DB,
    tenant: Tenant,
    user: CurrentUser,
    organization_id: str | None = None,
    category: str | None = Query(default=None, max_length=60),
    status: str | None = Query(default=None, max_length=30),
    owner: str | None = Query(default=None, max_length=120),
    priority: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
):
    if not can_use_feature(db, tenant, "advanced_reporting"):
        raise HTTPException(403, "UPGRADE_REQUIRED:advanced_reporting")
    rows = []
    offset = 0
    while True:
        batch = _report_rows(db, tenant, user, organization_id, category, status, owner,
                             priority, date_from, date_to, 500, offset)
        rows.extend(batch)
        if len(batch) < 500:
            break
        offset += len(batch)
    fields = (
        "organization_name", "code", "title", "category", "period", "applicability",
        "owner", "deadline", "internal_target", "priority", "status", "tasks",
        "checklist", "evidence_coverage", "evidence", "reviews", "approvals",
        "filing", "completion", "audit_timeline",
    )
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(fields)
    for row in rows:
        writer.writerow([_csv_value(row.get(field)) for field in fields])
    return Response(
        output.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="setu-compliance-report.csv"',
                 "X-Content-Type-Options": "nosniff"},
    )
