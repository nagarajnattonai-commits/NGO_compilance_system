"""Add organization scope to existing managed integrations and webhooks."""
import argparse
from sqlalchemy import inspect
from .database import engine
from .integration_models import IntegrationSchemaVersion

VERSION = "20260929_secure_integrations_webhooks_v1"


def apply(target=engine):
    inspector = inspect(target)
    for table in ("integration_connection_settings", "webhook_subscriptions"):
        if not inspector.has_table(table):
            raise RuntimeError("Apply the existing integration migration first")
    with target.begin() as connection:
        for table in ("integration_connection_settings", "webhook_subscriptions"):
            if "organization_id" not in {column["name"] for column in inspect(connection).get_columns(table)}:
                connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN organization_id VARCHAR(36)")
        for table in ("integration_connection_settings", "webhook_subscriptions"):
            index = next(item for item in IntegrationSchemaVersion.metadata.tables[table].indexes
                         if item.name == f"ix_{table}_organization_id")
            index.create(connection, checkfirst=True)
        IntegrationSchemaVersion.__table__.create(connection, checkfirst=True)
        ledger = IntegrationSchemaVersion.__table__
        if not connection.execute(ledger.select().where(ledger.c.version == VERSION)).first():
            connection.execute(ledger.insert().values(version=VERSION))
    return VERSION


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--apply", action="store_true")
    print(apply() if parser.parse_args().apply else VERSION + " - additive; run --apply after backup review")
