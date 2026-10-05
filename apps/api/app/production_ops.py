"""Read-only production schema and integrity diagnostics."""
import argparse
import json

from sqlalchemy import func, inspect, select

from .automation_models import ScheduledJob
from .database import Base, SessionLocal, engine
from .document_models import DocumentBlob
from .models import Organization, Workspace
from .production_security import build_metadata, ready_database, validate_production_schema
from . import main as _main  # register the complete application model metadata

JOB_STATES = {"PENDING", "RUNNING", "RETRY", "SUCCEEDED", "FAILED", "DEAD_LETTER", "CANCELLED"}


def report(target=engine) -> dict:
    tables = set(inspect(target).get_table_names())
    missing = sorted(set(Base.metadata.tables) - tables)
    result = {"ready": ready_database(target), "schema_current": not missing, "missing_table_count": len(missing),
              "invalid_job_states": 0, "orphan_organizations": 0, "orphan_document_blobs": 0,
              "build": build_metadata()}
    if missing:
        return result
    validate_production_schema(target, Base.metadata)
    with SessionLocal(bind=target) as db:
        result["invalid_job_states"] = db.scalar(select(func.count()).select_from(ScheduledJob).where(
            ScheduledJob.status.not_in(JOB_STATES))) or 0
        result["orphan_organizations"] = db.scalar(select(func.count()).select_from(Organization).outerjoin(
            Workspace, Workspace.id == Organization.tenant_id).where(Workspace.id.is_(None))) or 0
        result["orphan_document_blobs"] = db.scalar(select(func.count()).select_from(DocumentBlob).where(
            ~DocumentBlob.tenant_id.in_(select(Workspace.id)))) or 0
    return result


def healthy(result: dict) -> bool:
    return bool(result["ready"] and result["schema_current"] and not any(
        result[key] for key in ("invalid_job_states", "orphan_organizations", "orphan_document_blobs")))


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only production database diagnostics")
    parser.add_argument("--check", action="store_true", help="exit non-zero when schema, database, or integrity checks fail")
    args = parser.parse_args()
    result = report()
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    if args.check and not healthy(result):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
