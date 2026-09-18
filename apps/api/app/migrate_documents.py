import argparse
from sqlalchemy import inspect
from .database import engine
from .document_models import DocumentBlob,DocumentCurrent,DocumentEvidenceLink,DocumentUploadReceipt
from .integration_models import IntegrationSchemaVersion
VERSION="20260918_private_document_files_v1"
def apply(target=engine):
    if not all(inspect(target).has_table(n) for n in ("documents","document_versions","submissions","compliance_tasks")):raise RuntimeError("Initialize the existing document schema first")
    with target.begin() as c:
        for model in (DocumentBlob,DocumentCurrent,DocumentEvidenceLink,DocumentUploadReceipt,IntegrationSchemaVersion):model.__table__.create(c,checkfirst=True)
        ledger=IntegrationSchemaVersion.__table__
        if not c.execute(ledger.select().where(ledger.c.version==VERSION)).first():c.execute(ledger.insert().values(version=VERSION))
    return VERSION
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--apply",action="store_true");args=p.parse_args();print(apply() if args.apply else VERSION+" ? additive; run --apply after review")
