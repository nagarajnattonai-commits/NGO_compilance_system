"""Additive Phase 28 migration: registration verification, profile history and reminder lead time.

Adds nullable or defaulted columns and one new table. Existing rows keep their values;
nothing is dropped or rewritten. Safe to run more than once.
"""
import argparse

from sqlalchemy import inspect, text

from .database import engine
from .integration_models import IntegrationSchemaVersion
from .organization_models import OrganizationProfileChange

VERSION = "20261121_profile_registration_reminders_v1"


def _timestamp(target) -> str:
    return "TIMESTAMP WITH TIME ZONE" if target.dialect.name == "postgresql" else "DATETIME"


def apply(target=engine):
    inspector = inspect(target)
    for table in ("organization_registrations", "user_notification_preferences"):
        if not inspector.has_table(table):
            raise RuntimeError(f"Apply the existing schema first: {table} is missing")
    additions = {
        "organization_registrations": {
            "issuing_authority": "VARCHAR(160) NOT NULL DEFAULT ''",
            "verification_status": "VARCHAR(24) NOT NULL DEFAULT 'UNVERIFIED'",
            "verified_by": "VARCHAR(120) NOT NULL DEFAULT ''",
            "verified_at": _timestamp(target),
            "responsible_user_id": "VARCHAR(36)",
        },
        "user_notification_preferences": {
            "default_lead_days": "INTEGER NOT NULL DEFAULT 7",
        },
    }
    with target.begin() as connection:
        for table, columns in additions.items():
            existing = {column["name"] for column in inspect(connection).get_columns(table)}
            for name, definition in columns.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))
        OrganizationProfileChange.__table__.create(connection, checkfirst=True)
        IntegrationSchemaVersion.__table__.create(connection, checkfirst=True)
        ledger = IntegrationSchemaVersion.__table__
        if not connection.execute(ledger.select().where(ledger.c.version == VERSION)).first():
            connection.execute(ledger.insert().values(version=VERSION))
    return VERSION


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    print(apply() if parser.parse_args().apply else VERSION + " - additive; run --apply after backup review")
