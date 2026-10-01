"""Additive Phase 24 provider delivery identity migration."""
import argparse

from sqlalchemy import inspect, text

from .database import engine
from .integration_models import IntegrationSchemaVersion

VERSION = "20261001_communication_operations_v1"


def apply(target=engine):
    inspector = inspect(target)
    if not inspector.has_table("notification_deliveries"):
        raise RuntimeError("Apply the existing notification schema first")
    existing = {column["name"] for column in inspector.get_columns("notification_deliveries")}
    additions = {
        "provider_key": "VARCHAR(80) NOT NULL DEFAULT ''",
        "provider_connection_id": "VARCHAR(36)",
        "provider_status_at": "DATETIME",
    }
    with target.begin() as connection:
        for name, definition in additions.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE notification_deliveries ADD COLUMN {name} {definition}"))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_notification_deliveries_provider_identity "
            "ON notification_deliveries (provider_connection_id, provider_message_id)"
        ))
        IntegrationSchemaVersion.__table__.create(connection, checkfirst=True)
        ledger = IntegrationSchemaVersion.__table__
        if not connection.execute(ledger.select().where(ledger.c.version == VERSION)).first():
            connection.execute(ledger.insert().values(version=VERSION))
    return VERSION


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    print(apply() if parser.parse_args().apply else VERSION + " - additive; run --apply after backup review")
