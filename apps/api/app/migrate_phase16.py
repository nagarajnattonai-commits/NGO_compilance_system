"""Idempotent Phase 16 schema migration for secure AI and RAG metadata."""
from __future__ import annotations

import argparse

from sqlalchemy import inspect

from .ai_models import AiProviderConfiguration, DocumentChunk, DocumentExtraction
from .database import engine
from .integration_models import IntegrationSchemaVersion

VERSION = "phase16_secure_ai_rag_v1"
TABLES = (
    AiProviderConfiguration.__table__,
    DocumentExtraction.__table__,
    DocumentChunk.__table__,
)


def apply(target=engine) -> str:
    inspector = inspect(target)
    required = {"workspaces", "organizations", "documents", "document_file_versions", "integration_schema_versions"}
    missing = required - set(inspector.get_table_names())
    if missing:
        raise RuntimeError(f"Phase 16 prerequisites are missing: {', '.join(sorted(missing))}")
    with target.begin() as connection:
        for table in TABLES:
            table.create(bind=connection, checkfirst=True)
        ledger = IntegrationSchemaVersion.__table__
        if not connection.execute(ledger.select().where(ledger.c.version == VERSION)).first():
            connection.execute(ledger.insert().values(version=VERSION))
    return VERSION


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    print(apply() if parser.parse_args().apply else VERSION + " - additive; run --apply after backup review")
