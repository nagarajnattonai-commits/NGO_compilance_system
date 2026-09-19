"""Additive Phase 6 migration. Existing runtime and integration tables are untouched."""
import argparse

from sqlalchemy import inspect

from .automation_models import ScheduledJob
from .database import engine
from .integration_models import IntegrationSchemaVersion

VERSION = "20260919_scheduler_automation_v1"


def apply(target=engine):
    if not all(inspect(target).has_table(name) for name in ("workspaces", "compliance_instances", "compliance_reminder_schedule")):
        raise RuntimeError("Apply the existing auth and compliance runtime schemas first")
    with target.begin() as connection:
        ScheduledJob.__table__.create(connection, checkfirst=True)
        IntegrationSchemaVersion.__table__.create(connection, checkfirst=True)
        ledger = IntegrationSchemaVersion.__table__
        if not connection.execute(ledger.select().where(ledger.c.version == VERSION)).first():
            connection.execute(ledger.insert().values(version=VERSION))
    return VERSION


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    print(apply() if parser.parse_args().apply else VERSION + " - additive; run --apply after backup review")
