"""Additive Phase 14 migration for configurable automation workflows."""
import argparse
from sqlalchemy import inspect
from .automation_models import ScheduledJob
from .database import engine
from .integration_models import IntegrationSchemaVersion
from .phase14_models import AutomationActionExecution, AutomationDefinition, AutomationExecution

VERSION = "20260928_configurable_automation_workflows_v1"


def apply(target=engine):
    if not all(inspect(target).has_table(name) for name in ("workspaces", "auth_users", "organizations", "scheduled_jobs")):
        raise RuntimeError("Apply the existing authentication and scheduler schemas first")
    with target.begin() as connection:
        AutomationDefinition.__table__.create(connection, checkfirst=True)
        AutomationExecution.__table__.create(connection, checkfirst=True)
        AutomationActionExecution.__table__.create(connection, checkfirst=True)
        IntegrationSchemaVersion.__table__.create(connection, checkfirst=True)
        ledger = IntegrationSchemaVersion.__table__
        if not connection.execute(ledger.select().where(ledger.c.version == VERSION)).first():
            connection.execute(ledger.insert().values(version=VERSION))
    return VERSION


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--apply", action="store_true")
    print(apply() if parser.parse_args().apply else VERSION + " - additive; run --apply after backup review")
