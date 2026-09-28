"""Additive Phase 13 migration for personal saved views."""
import argparse

from sqlalchemy import inspect

from .database import engine
from .integration_models import IntegrationSchemaVersion
from .phase13_models import SavedView

VERSION = "20260928_global_search_saved_views_v1"


def apply(target=engine):
    inspector = inspect(target)
    if not all(inspector.has_table(name) for name in ("workspaces", "auth_users")):
        raise RuntimeError("Apply the existing authentication schema first")
    with target.begin() as connection:
        SavedView.__table__.create(connection, checkfirst=True)
        IntegrationSchemaVersion.__table__.create(connection, checkfirst=True)
        ledger = IntegrationSchemaVersion.__table__
        if not connection.execute(ledger.select().where(ledger.c.version == VERSION)).first():
            connection.execute(ledger.insert().values(version=VERSION))
    return VERSION


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    print(apply() if parser.parse_args().apply else VERSION + " - additive; run --apply after backup review")
