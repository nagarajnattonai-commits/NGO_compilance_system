import os

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["APP_ENV"] = "development"
os.environ["APP_ORIGIN"] = "http://localhost:3000"

import pytest
from app.database import Base, engine


@pytest.fixture(autouse=True)
def isolated_database():
    # The suite must never reset the user's on-disk development database.
    assert str(engine.url) == "sqlite:///:memory:"
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture(autouse=True)
def isolated_document_storage(monkeypatch,tmp_path):
    monkeypatch.setenv("DOCUMENT_FILE_DIR",str(tmp_path/"private-files"))
    from app.document_service import configure_scanner
    configure_scanner(None)
    yield
    configure_scanner(None)
