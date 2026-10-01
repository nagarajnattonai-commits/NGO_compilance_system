"""Additive and idempotent Phase 22 CSR partner-management migration."""
import argparse
from sqlalchemy import inspect
from .csr_models import (CsrChecklistTemplate, CsrChecklistTemplateItem, CsrDueDiligenceItem,
                         CsrDueDiligenceReview, CsrEvidenceLink, CsrPartnerCollaborator,
                         CsrPartnerRelationship, CsrProject, CsrTaskLink)
from .database import engine
from .integration_models import IntegrationSchemaVersion

VERSION = "20261001_csr_partner_management_v1"
TABLES = (CsrPartnerRelationship.__table__, CsrPartnerCollaborator.__table__, CsrProject.__table__,
          CsrChecklistTemplate.__table__, CsrChecklistTemplateItem.__table__, CsrDueDiligenceReview.__table__,
          CsrDueDiligenceItem.__table__, CsrEvidenceLink.__table__, CsrTaskLink.__table__)


def apply(target=engine):
    required = {"workspaces", "auth_users", "organizations", "documents", "document_file_versions",
                "compliance_tasks", "integration_schema_versions"}
    missing = required - set(inspect(target).get_table_names())
    if missing:
        raise RuntimeError("Phase 22 prerequisites are missing: " + ", ".join(sorted(missing)))
    with target.begin() as connection:
        for table in TABLES:
            table.create(connection, checkfirst=True)
        ledger = IntegrationSchemaVersion.__table__
        if not connection.execute(ledger.select().where(ledger.c.version == VERSION)).first():
            connection.execute(ledger.insert().values(version=VERSION))
    return VERSION


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--apply", action="store_true")
    print(apply() if parser.parse_args().apply else VERSION + " - additive; run --apply after backup review")
