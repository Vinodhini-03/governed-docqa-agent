import os

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from app import audit, auth, rag
from app.agent import AgentRunner

if os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"):
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor()
    except Exception:  # noqa: BLE001
        pass

app = FastAPI(title="Governed Document Q&A Agent", version="1.0.0")
_runner: AgentRunner | None = None


def runner() -> AgentRunner:
    global _runner
    if _runner is None:
        _runner = AgentRunner()
    return _runner


class Login(BaseModel):
    username: str
    password: str


class Ask(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class Decision(BaseModel):
    approved: bool


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/token")
def token(body: Login):
    t = auth.login(body.username, body.password)
    if not t:
        audit.record("login_failed", body.username)
        raise HTTPException(401, "Bad credentials")
    return {"access_token": t, "token_type": "bearer"}


@app.post("/ask")
def ask(body: Ask, user: dict = Depends(auth.require_role("reader"))):
    res = rag.answer(body.question, user["sub"])
    res.pop("retrieved", None)
    return res


@app.post("/agent/run")
def agent_run(body: Ask, user: dict = Depends(auth.require_role("reader"))):
    return runner().run(body.question, user["sub"])


@app.post("/agent/approve/{thread_id}")
def agent_approve(thread_id: str, body: Decision, user: dict = Depends(auth.require_role("approver"))):
    try:
        return runner().resume(thread_id, body.approved, user["sub"])
    except KeyError:
        raise HTTPException(404, "No pending approval for this thread") from None


@app.get("/audit")
def audit_log(n: int = 50, user: dict = Depends(auth.require_role("admin"))):
    return audit.tail(min(n, 500))
