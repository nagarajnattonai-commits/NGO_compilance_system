"""Explicit additive migration. Never alter/drop the existing connection register."""
import argparse
from sqlalchemy import inspect
from .database import Base, engine
from . import models, integration_models
VERSION="20260918_integrations_v1"

def apply(target=engine):
    inspector=inspect(target)
    if not inspector.has_table("integration_connections"):
        raise RuntimeError("Initialize the existing application schema first; the integration register is reused.")
    tables=[table for table in Base.metadata.sorted_tables if table.name in {table.name for table in integration_models.Base.metadata.tables.values()
        if table.name.startswith(("integration_","webhook_","api_"))} and table.name!="integration_connections"]
    with target.begin() as connection:
        for table in tables:table.create(connection,checkfirst=True)
        ledger=integration_models.IntegrationSchemaVersion.__table__
        if not connection.execute(ledger.select().where(ledger.c.version==VERSION)).first():
            connection.execute(ledger.insert().values(version=VERSION))
    return [table.name for table in tables]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--apply",action="store_true",help="Create only additive integration tables and record the migration")
    args=parser.parse_args()
    if args.apply:
        print("Applied "+VERSION+": "+", ".join(apply()))
    else:
        print("Dialect: "+engine.dialect.name)
        print("Integration migration: "+VERSION+"; rerun with --apply after a reviewed backup.")
if __name__=="__main__":main()
