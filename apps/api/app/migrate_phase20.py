"""Additive Phase 20 migration for durable bulk import jobs."""
import argparse

from sqlalchemy import inspect

from .database import engine
from .integration_models import IntegrationSchemaVersion
from .phase20_models import ImportJob, ImportRowResult

VERSION = "20260930_bulk_onboarding_imports_v1"


def apply(target=engine):
    if not all(inspect(target).has_table(name) for name in ("workspaces", "auth_users", "organizations")):
        raise RuntimeError("Apply the existing authentication and organization schemas first")
    with target.begin() as connection:
        ImportJob.__table__.create(connection, checkfirst=True)
        ImportRowResult.__table__.create(connection, checkfirst=True)
        IntegrationSchemaVersion.__table__.create(connection, checkfirst=True)
        ledger = IntegrationSchemaVersion.__table__
        if not connection.execute(ledger.select().where(ledger.c.version == VERSION)).first():
            connection.execute(ledger.insert().values(version=VERSION))
    return VERSION


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    print(apply() if parser.parse_args().apply else VERSION + " - additive; run --apply after backup review")
