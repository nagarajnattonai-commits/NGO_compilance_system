"""Additive, idempotent Phase 21 document intelligence migration."""
import argparse
from sqlalchemy import inspect
from .database import engine
from .document_intelligence_models import DocumentIntelligenceRun, ExtractedDocumentFact
from .integration_models import IntegrationSchemaVersion

VERSION = "20260930_document_intelligence_v1"


def apply(target=engine):
    required = {"workspaces", "auth_users", "organizations", "documents", "document_file_versions", "integration_schema_versions"}
    missing = required - set(inspect(target).get_table_names())
    if missing:
        raise RuntimeError("Phase 21 prerequisites are missing: " + ", ".join(sorted(missing)))
    with target.begin() as connection:
        DocumentIntelligenceRun.__table__.create(connection, checkfirst=True)
        ExtractedDocumentFact.__table__.create(connection, checkfirst=True)
        ledger = IntegrationSchemaVersion.__table__
        if not connection.execute(ledger.select().where(ledger.c.version == VERSION)).first():
            connection.execute(ledger.insert().values(version=VERSION))
    return VERSION


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    print(apply() if parser.parse_args().apply else VERSION + " - additive; run --apply after backup review")
