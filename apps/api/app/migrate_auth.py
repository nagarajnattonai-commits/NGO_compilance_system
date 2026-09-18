"""Reviewed, additive authentication migration. No existing columns/rows are changed."""
import argparse
from sqlalchemy import inspect
from .database import Base,engine
from . import models,auth_models
from .integration_models import IntegrationSchemaVersion
VERSION="20260918_authentication_v1"
NAMES={value.__table__.name for value in vars(auth_models).values() if isinstance(value,type) and value.__module__==auth_models.__name__ and hasattr(value,"__table__")}

def apply(target=engine):
    inspector=inspect(target)
    if not all(inspector.has_table(name) for name in ("auth_users","auth_sessions","auth_tokens")):
        raise RuntimeError("Initialize the existing auth schema before applying this additive migration")
    with target.begin() as connection:
        for table in Base.metadata.sorted_tables:
            if table.name in NAMES:table.create(connection,checkfirst=True)
        ledger=IntegrationSchemaVersion.__table__;ledger.create(connection,checkfirst=True)
        if not connection.execute(ledger.select().where(ledger.c.version==VERSION)).first():
            connection.execute(ledger.insert().values(version=VERSION))
    return sorted(NAMES)

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--apply",action="store_true");args=parser.parse_args()
    print("Applied "+VERSION+": "+", ".join(apply()) if args.apply else "Additive migration "+VERSION+"; review backup and run --apply")
