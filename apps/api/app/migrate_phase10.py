"""Additive Phase 10 migration for Google Calendar synchronization."""
import argparse

from sqlalchemy import inspect

from .database import engine
from .integration_models import IntegrationSchemaVersion
from .phase10_models import CalendarEventMapping, CalendarOAuthState, CalendarSyncPolicy

VERSION = "20260925_google_calendar_sync_v1"


def apply(target=engine):
    inspector = inspect(target)
    required = ("workspaces", "auth_users", "organizations", "integration_connections", "scheduled_jobs")
    if not all(inspector.has_table(name) for name in required):
        raise RuntimeError("Apply the existing auth, integration and automation schemas first")
    with target.begin() as connection:
        CalendarOAuthState.__table__.create(connection, checkfirst=True)
        CalendarSyncPolicy.__table__.create(connection, checkfirst=True)
        CalendarEventMapping.__table__.create(connection, checkfirst=True)
        IntegrationSchemaVersion.__table__.create(connection, checkfirst=True)
        ledger = IntegrationSchemaVersion.__table__
        if not connection.execute(ledger.select().where(ledger.c.version == VERSION)).first():
            connection.execute(ledger.insert().values(version=VERSION))
    return VERSION


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    print(apply() if parser.parse_args().apply else VERSION + " - additive; run --apply after backup review")
