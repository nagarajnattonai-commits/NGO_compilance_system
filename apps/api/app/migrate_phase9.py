"""Additive Phase 9 migration for review, approval and immutable filing history."""
import argparse

from sqlalchemy import inspect

from .database import engine
from .integration_models import IntegrationSchemaVersion
from .phase9_models import ComplianceApproval, ComplianceReview

VERSION = "20260925_reviews_approvals_filing_v1"


def apply(target=engine):
    inspector = inspect(target)
    required = ("workspaces", "auth_users", "organizations", "compliance_instances", "submissions")
    if not all(inspector.has_table(name) for name in required):
        raise RuntimeError("Apply the existing auth and runtime schemas first")
    existing = {column["name"] for column in inspector.get_columns("submissions")}
    timestamp_type = "TIMESTAMP WITH TIME ZONE" if target.dialect.name == "postgresql" else "DATETIME"
    additions = {
        "proof_version_id": "VARCHAR(36) REFERENCES document_versions(id)",
        "proof_type": "VARCHAR(40) DEFAULT 'ACKNOWLEDGEMENT'",
        "filing_channel": "VARCHAR(80) DEFAULT 'PORTAL'",
        "notes": "TEXT DEFAULT ''",
        "filed_by": "VARCHAR(36) REFERENCES auth_users(id)",
        "filed_at": timestamp_type,
    }
    with target.begin() as connection:
        for name, sql_type in additions.items():
            if name not in existing:
                connection.exec_driver_sql(f"ALTER TABLE submissions ADD COLUMN {name} {sql_type}")
        connection.exec_driver_sql("UPDATE submissions SET proof_type = 'ACKNOWLEDGEMENT' WHERE proof_type IS NULL")
        connection.exec_driver_sql("UPDATE submissions SET filing_channel = 'PORTAL' WHERE filing_channel IS NULL")
        connection.exec_driver_sql("UPDATE submissions SET notes = '' WHERE notes IS NULL")
        connection.exec_driver_sql("UPDATE submissions SET filed_at = submitted_at WHERE filed_at IS NULL")
        ComplianceReview.__table__.create(connection, checkfirst=True)
        ComplianceApproval.__table__.create(connection, checkfirst=True)
        approval_columns = {column["name"] for column in inspect(target).get_columns("compliance_approvals")}
        if "target_status" not in approval_columns:
            connection.exec_driver_sql("ALTER TABLE compliance_approvals ADD COLUMN target_status VARCHAR(30) DEFAULT 'READY_TO_FILE'")
        IntegrationSchemaVersion.__table__.create(connection, checkfirst=True)
        ledger = IntegrationSchemaVersion.__table__
        if not connection.execute(ledger.select().where(ledger.c.version == VERSION)).first():
            connection.execute(ledger.insert().values(version=VERSION))
    return VERSION


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    print(apply() if parser.parse_args().apply else VERSION + " - additive; run --apply after backup review")
