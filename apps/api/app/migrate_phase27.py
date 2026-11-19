"""Additive Phase 27 two-step verification tables. Existing auth tables are unchanged."""
import argparse

from .database import engine
from .integration_models import IntegrationSchemaVersion
from .mfa import MfaFactor, MfaRecoveryCode, MfaSessionVerification

VERSION = "20261119_two_step_verification_v1"


def apply(target=engine):
    with target.begin() as connection:
        for table in (MfaFactor.__table__, MfaRecoveryCode.__table__, MfaSessionVerification.__table__):
            table.create(connection, checkfirst=True)
        IntegrationSchemaVersion.__table__.create(connection, checkfirst=True)
        ledger = IntegrationSchemaVersion.__table__
        if not connection.execute(ledger.select().where(ledger.c.version == VERSION)).first():
            connection.execute(ledger.insert().values(version=VERSION))
    return VERSION


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    print(apply() if parser.parse_args().apply else VERSION + " - additive; run --apply after backup review")
