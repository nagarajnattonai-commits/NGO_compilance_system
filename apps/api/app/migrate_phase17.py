"""Idempotent Phase 17 schema migration for assistant conversations."""
from __future__ import annotations

import argparse

from sqlalchemy import inspect

from .ai_assistant_models import AiConversation, AiMessage
from .database import engine
from .integration_models import IntegrationSchemaVersion

VERSION = "phase17_grounded_ai_assistant_v1"
TABLES = (AiConversation.__table__, AiMessage.__table__)


def apply(target=engine) -> str:
    required = {"workspaces", "organizations", "auth_users", "ai_provider_configurations", "integration_schema_versions"}
    missing = required - set(inspect(target).get_table_names())
    if missing:
        raise RuntimeError(f"Phase 17 prerequisites are missing: {', '.join(sorted(missing))}")
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
