import os
import tempfile
from pathlib import Path

import pytest

TMP = tempfile.mkdtemp()
os.environ.update(
    STORE="local", LLM_PROVIDER="extractive", JWT_SECRET="test-secret",
    INDEX_PATH=f"{TMP}/index.json", AUDIT_PATH=f"{TMP}/audit.jsonl", OUTPUTS_DIR=f"{TMP}/out",
)


@pytest.fixture(scope="session", autouse=True)
def indexed():
    from app.ingest import ingest_path
    from app.store import get_store

    s = get_store()
    s.reset()
    s.add(ingest_path(Path(__file__).resolve().parent.parent / "data" / "docs"))


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


def token(client, user, pw):
    r = client.post("/token", json={"username": user, "password": pw})
    return {"Authorization": "Bearer " + r.json()["access_token"]}
