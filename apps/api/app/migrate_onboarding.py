import argparse
from sqlalchemy import inspect
from .database import engine
from .onboarding_models import OrganizationOnboarding
from .integration_models import IntegrationSchemaVersion
VERSION="20260918_onboarding_v1"
def apply(target=engine):
    if not inspect(target).has_table("organization_details"):raise RuntimeError("Apply the organization profile migration first")
    with target.begin() as c:
        OrganizationOnboarding.__table__.create(c,checkfirst=True)
        ledger=IntegrationSchemaVersion.__table__;ledger.create(c,checkfirst=True)
        if not c.execute(ledger.select().where(ledger.c.version==VERSION)).first():c.execute(ledger.insert().values(version=VERSION))
    return VERSION
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--apply",action="store_true");args=p.parse_args();print(apply() if args.apply else VERSION+" ? additive; run --apply after review")
