"""LangGraph agent: guard -> answer -> plan action -> [human approval] -> execute."""
import json
import re
import time
import uuid
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app import audit, rag
from app.config import get_settings


class State(TypedDict, total=False):
    question: str
    user: str
    result: dict
    action: dict | None
    approval: dict | None
    outcome: str


# ---- tools (side-effecting, therefore gated) --------------------------------
def tool_save_summary(question: str, result: dict) -> str:
    out = Path(get_settings().outputs_dir)
    out.mkdir(parents=True, exist_ok=True)
    p = out / f"summary_{int(time.time())}.md"
    cites = "\n".join(f"- {c['source']} p.{c['page']}" for c in result["citations"])
    p.write_text(f"# {question}\n\n{result['answer']}\n\nSources:\n{cites}\n", encoding="utf-8")
    return f"saved {p}"


def tool_escalate(question: str, result: dict) -> str:
    out = Path(get_settings().outputs_dir)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "escalations.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"question": question, "answer": result["answer"], "ts": time.time()}) + "\n")
    return "escalated to human reviewer queue"


TOOLS = {"save_summary": tool_save_summary, "escalate_to_reviewer": tool_escalate}


def plan_action(question: str) -> dict | None:
    q = question.lower()
    if re.search(r"\b(escalate|flag|notify|email)\b", q):
        return {"tool": "escalate_to_reviewer"}
    if re.search(r"\b(save|export)\b", q):
        return {"tool": "save_summary"}
    return None


# ---- nodes ------------------------------------------------------------------
def n_answer(s: State) -> State:
    return {"result": rag.answer(s["question"], s["user"])}


def n_plan(s: State) -> State:
    action = None if s["result"]["refused"] else plan_action(s["question"])
    return {"action": action}


def route(s: State) -> str:
    return "approval" if s.get("action") else END


def n_approval(s: State) -> State:
    audit.record("approval_requested", s["user"], action=s["action"], question=s["question"])
    decision = interrupt({"action": s["action"], "question": s["question"], "answer": s["result"]["answer"]})
    audit.record("approval_decision", decision.get("approver", "unknown"), approved=bool(decision.get("approved")),
                 action=s["action"], requested_by=s["user"])
    return {"approval": decision}


def n_execute(s: State) -> State:
    if not (s.get("approval") or {}).get("approved"):
        return {"outcome": "action rejected by approver; nothing executed"}
    msg = TOOLS[s["action"]["tool"]](s["question"], s["result"])
    audit.record("action_executed", s["user"], tool=s["action"]["tool"], detail=msg)
    return {"outcome": msg}


def build_agent():
    g = StateGraph(State)
    g.add_node("answer", n_answer)
    g.add_node("plan", n_plan)
    g.add_node("approval", n_approval)
    g.add_node("execute", n_execute)
    g.add_edge(START, "answer")
    g.add_edge("answer", "plan")
    g.add_conditional_edges("plan", route, {"approval": "approval", END: END})
    g.add_edge("approval", "execute")
    g.add_edge("execute", END)
    # MemorySaver is per-process. For multi-instance deployments use a persistent checkpointer.
    return g.compile(checkpointer=MemorySaver())


class AgentRunner:
    def __init__(self):
        self.graph = build_agent()

    def _view(self, cfg, tid):
        st = self.graph.get_state(cfg)
        vals = st.values
        pending = bool(st.next)
        out = {"thread_id": tid, "status": "pending_approval" if pending else "completed",
               "answer": vals.get("result", {}).get("answer"),
               "citations": vals.get("result", {}).get("citations", []),
               "refused": vals.get("result", {}).get("refused"),
               "proposed_action": vals.get("action"), "outcome": vals.get("outcome")}
        return out

    def run(self, question: str, user: str) -> dict:
        tid = uuid.uuid4().hex
        cfg = {"configurable": {"thread_id": tid}}
        self.graph.invoke({"question": question, "user": user}, cfg)
        return self._view(cfg, tid)

    def resume(self, tid: str, approved: bool, approver: str) -> dict:
        cfg = {"configurable": {"thread_id": tid}}
        if not self.graph.get_state(cfg).next:
            raise KeyError(tid)
        self.graph.invoke(Command(resume={"approved": approved, "approver": approver}), cfg)
        return self._view(cfg, tid)
