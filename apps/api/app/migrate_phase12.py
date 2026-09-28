"""Add Phase 12 subscription period, integration limit and cancellation fields."""
import argparse

from sqlalchemy import inspect, text

from .database import engine
from .integration_models import IntegrationSchemaVersion

VERSION = "20260926_subscription_plans_entitlements_v1"


def apply(target=engine):
    inspector = inspect(target)
    if not inspector.has_table("subscriptions"):
        raise RuntimeError("Create the existing subscription schema before applying Phase 12")
    columns = {item["name"] for item in inspector.get_columns("subscriptions")}
    added_integration_limit = "integration_limit" not in columns
    with target.begin() as connection:
        if "period_start" not in columns:
            connection.exec_driver_sql("ALTER TABLE subscriptions ADD COLUMN period_start DATE")
        if added_integration_limit:
            connection.exec_driver_sql("ALTER TABLE subscriptions ADD COLUMN integration_limit INTEGER NOT NULL DEFAULT 10")
            connection.execute(text("""
                UPDATE subscriptions SET integration_limit = CASE upper(plan_name)
                    WHEN 'STARTER' THEN 1
                    WHEN 'PROFESSIONAL' THEN 5
                    WHEN 'BUSINESS' THEN 10
                    WHEN 'ENTERPRISE' THEN 50
                    ELSE integration_limit
                END
            """))
        if "cancel_at_period_end" not in columns:
            false_default = "FALSE" if target.dialect.name == "postgresql" else "0"
            connection.exec_driver_sql(
                "ALTER TABLE subscriptions ADD COLUMN cancel_at_period_end BOOLEAN NOT NULL DEFAULT " + false_default
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