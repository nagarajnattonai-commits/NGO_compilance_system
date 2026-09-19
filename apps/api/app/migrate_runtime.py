"""Non-destructive runtime migration; no existing row is rewritten."""
import argparse
from sqlalchemy import inspect
from .database import engine
from .runtime_models import ComplianceOwnership,OrganizationEventFact,ApplicabilityOverride,ApplicabilityDecision,NextCycleGeneration
from .integration_models import IntegrationSchemaVersion
VERSION="20260918_compliance_runtime_v1"
def apply(target=engine):
    if not all(inspect(target).has_table(n) for n in ("compliance_instances","compliance_master","auth_workspace_access")):
        raise RuntimeError("Initialize the existing compliance/auth schema first")
    with target.begin() as c:
        for model in (ComplianceOwnership,OrganizationEventFact,ApplicabilityOverride,ApplicabilityDecision,NextCycleGeneration,IntegrationSchemaVersion):
            model.__table__.create(c,checkfirst=True)
        ledger=IntegrationSchemaVersion.__table__
        if not c.execute(ledger.select().where(ledger.c.version==VERSION)).first():
            c.execute(ledger.insert().values(version=VERSION))
    return VERSION
if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--apply",action="store_true")
    print(apply() if parser.parse_args().apply else VERSION+" ? additive; use --apply")
