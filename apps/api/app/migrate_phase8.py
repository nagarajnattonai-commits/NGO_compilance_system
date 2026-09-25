"""Additive Phase 8 migration for organization access and task collaboration."""
import argparse

from sqlalchemy import inspect

from .database import engine
from .integration_models import IntegrationSchemaVersion
from .phase8_models import OrganizationAccess, TaskComment

VERSION = "20260924_tasks_organization_access_v1"

def apply(target=engine):
    inspector = inspect(target)
    required = ("workspaces", "auth_users", "organizations", "compliance_tasks", "documents")
    if not all(inspector.has_table(name) for name in required):
        raise RuntimeError("Apply the existing auth, runtime and document schemas first")
    existing = {column["name"] for column in inspector.get_columns("compliance_tasks")}
    existing_indexes = {index["name"] for index in inspector.get_indexes("compliance_tasks")}
    timestamp_type = "TIMESTAMP WITH TIME ZONE" if target.dialect.name == "postgresql" else "DATETIME"
    task_columns = {
        "assignee_user_id": "VARCHAR(36) REFERENCES auth_users(id)",
        "assigned_by": "VARCHAR(36) REFERENCES auth_users(id)",
        "assigned_at": timestamp_type,
        "updated_at": timestamp_type,
        "archived_at": timestamp_type,
    }
    with target.begin() as connection:
        for name, sql_type in task_columns.items():
            if name not in existing:
                connection.exec_driver_sql(f"ALTER TABLE compliance_tasks ADD COLUMN {name} {sql_type}")
        connection.exec_driver_sql(
            "UPDATE compliance_tasks SET updated_at = created_at WHERE updated_at IS NULL"
        )
        OrganizationAccess.__table__.create(connection, checkfirst=True)
        TaskComment.__table__.create(connection, checkfirst=True)
        if "ix_compliance_tasks_assignee_user_id" not in existing_indexes:
            connection.exec_driver_sql(
                "CREATE INDEX ix_compliance_tasks_assignee_user_id ON compliance_tasks (assignee_user_id)"
            )
        IntegrationSchemaVersion.__table__.create(connection, checkfirst=True)
        ledger = IntegrationSchemaVersion.__table__
        if not connection.execute(ledger.select().where(ledger.c.version == VERSION)).first():
            connection.execute(ledger.insert().values(version=VERSION))
    return VERSION


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    print(apply() if parser.parse_args().apply else VERSION + " - additive; run --apply after backup review")
