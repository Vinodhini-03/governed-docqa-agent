from pathlib import Path

from tests.conftest import token


def test_requires_auth(client):
    assert client.post("/ask", json={"question": "hi"}).status_code == 401


def test_ask_with_citations(client):
    h = token(client, "alice", "alice-pass")
    r = client.post("/ask", json={"question": "When must the post-incident review be held?"}, headers=h)
    assert r.status_code == 200 and r.json()["citations"] and "retrieved" not in r.json()


def test_rbac(client):
    reader = token(client, "alice", "alice-pass")
    assert client.get("/audit", headers=reader).status_code == 403
    assert client.get("/audit", headers=token(client, "admin", "admin-pass")).status_code == 200
    assert client.post("/token", json={"username": "alice", "password": "x"}).status_code == 401


def test_agent_approval_flow(client, tmp_path):
    alice, bob = token(client, "alice", "alice-pass"), token(client, "bob", "bob-pass")
    r = client.post("/agent/run", json={"question": "How long are access logs retained? Please save this answer."},
                    headers=alice).json()
    assert r["status"] == "pending_approval" and r["proposed_action"]["tool"] == "save_summary"
    # a reader cannot approve
    assert client.post(f"/agent/approve/{r['thread_id']}", json={"approved": True}, headers=alice).status_code == 403
    done = client.post(f"/agent/approve/{r['thread_id']}", json={"approved": True}, headers=bob).json()
    assert done["status"] == "completed" and done["outcome"].startswith("saved")
    assert Path(done["outcome"].split(" ", 1)[1]).exists()


def test_agent_rejection_executes_nothing(client):
    alice, bob = token(client, "alice", "alice-pass"), token(client, "bob", "bob-pass")
    r = client.post("/agent/run", json={"question": "How long is email retained? Escalate this."}, headers=alice).json()
    done = client.post(f"/agent/approve/{r['thread_id']}", json={"approved": False}, headers=bob).json()
    assert "rejected" in done["outcome"]


def test_audit_records_approval(client):
    events = client.get("/audit?n=200", headers=token(client, "admin", "admin-pass")).json()
    kinds = {e["event"] for e in events}
    assert {"answer", "approval_requested", "approval_decision"} <= kinds
