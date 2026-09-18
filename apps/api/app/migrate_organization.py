"""Idempotent additive organization migration; does not update existing rows."""
import argparse
from sqlalchemy import inspect
from .database import engine
from .organization_models import OrganizationDetails, OrganizationRegistration
from .integration_models import IntegrationSchemaVersion
VERSION = "20260918_organization_profile_v1"

def apply(target=engine):
    if not all(inspect(target).has_table(name) for name in ("organizations", "auth_users", "documents")):
        raise RuntimeError("Initialize the existing core schema before applying this migration")
    with target.begin() as connection:
        for model in (OrganizationDetails, OrganizationRegistration, IntegrationSchemaVersion): model.__table__.create(connection, checkfirst=True)
        ledger = IntegrationSchemaVersion.__table__
        if not connection.execute(ledger.select().where(ledger.c.version == VERSION)).first(): connection.execute(ledger.insert().values(version=VERSION))
    return VERSION

if __name__ == "__main__":
    parser=argparse.ArgumentParser(); parser.add_argument("--apply", action="store_true"); args=parser.parse_args()
    print(apply() if args.apply else VERSION+" ? review backup, then run --apply")
