"""Additive Phase 29 migration: donation register tables (phase A of the NGO operations design).

Creates new tables only; existing tables are untouched. Safe to run more than once.
Run explicitly in production after a backup: python -m app.migrate_phase29 --apply
"""
import argparse

from sqlalchemy import inspect

from .database import engine
from .donation_models import Donation, DonationBankAccount, DonationReceipt, DonationStatement, Donor, DonorCertificate
from .integration_models import IntegrationSchemaVersion

VERSION = "20261121_donation_register_v1"
TABLES = (DonationBankAccount, Donor, Donation, DonationReceipt, DonationStatement, DonorCertificate)


def apply(target=engine):
    inspector = inspect(target)
    for table in ("organizations", "documents"):
        if not inspector.has_table(table):
            raise RuntimeError(f"Apply the existing schema first: {table} is missing")
    with target.begin() as connection:
        for model in TABLES:
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
