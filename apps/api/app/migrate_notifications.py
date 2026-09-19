"""Additive Phase 7 notification automation migration."""
import argparse

from sqlalchemy import inspect

from .database import engine
from .integration_models import IntegrationSchemaVersion
from .notification_models import (
    NotificationContext,
    NotificationDelivery,
    NotificationRecipient,
    UserNotificationPreference,
    WorkspaceNotificationPolicy,
)

VERSION = "20260919_notification_automation_v1"


def apply(target=engine):
    if not all(inspect(target).has_table(name) for name in ("workspaces", "auth_users", "notifications", "scheduled_jobs")):
        raise RuntimeError("Apply the existing auth, application and scheduler schemas first")
    tables = (NotificationContext, NotificationRecipient, NotificationDelivery, UserNotificationPreference, WorkspaceNotificationPolicy)
    with target.begin() as connection:
        for model in tables:
            model.__table__.create(connection, checkfirst=True)
        IntegrationSchemaVersion.__table__.create(connection, checkfirst=True)
        ledger = IntegrationSchemaVersion.__table__
        if not connection.execute(ledger.select().where(ledger.c.version == VERSION)).first():
            connection.execute(ledger.insert().values(version=VERSION))
    return VERSION


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    print(apply() if parser.parse_args().apply else VERSION + " - additive; run --apply after backup review")
