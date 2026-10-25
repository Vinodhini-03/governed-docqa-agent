import re
import time

from app import audit, guardrails, llm
from app.config import get_settings
from app.store import get_store
from app.textutil import coverage

REFUSAL = "I can't answer that from the indexed documents."


def retrieve(question: str, k: int | None = None):
    return get_store().search(question, k or get_settings().top_k)


def answer(question: str, user: str = "anonymous") -> dict:
    t0 = time.perf_counter()
    s = get_settings()
    ok, reason = guardrails.check_input(question)
    if not ok:
        res = {"answer": reason, "citations": [], "confidence": 0.0, "refused": True, "retrieved": []}
    else:
        hits = retrieve(question)
        conf = max((coverage(question, h.text) for h in hits), default=0.0)
        if conf < s.min_confidence:
            res = {"answer": REFUSAL, "citations": [], "confidence": round(conf, 3), "refused": True,
                   "retrieved": [h.__dict__ for h in hits]}
        else:
            ctx = hits[:4]
            text = llm.generate(question, [h.text for h in ctx])
            refused = text.lower().startswith("i don't know")
            nums = sorted({int(n) for n in re.findall(r"\[(\d+)\]", text) if 1 <= int(n) <= len(ctx)})
            if not nums and not refused:
                nums = list(range(1, len(ctx) + 1))
            cites = [{"ref": n, "id": ctx[n - 1].id, "source": ctx[n - 1].source, "page": ctx[n - 1].page,
                      "text": ctx[n - 1].text} for n in nums] if not refused else []
            res = {"answer": text, "citations": cites, "confidence": round(conf, 3), "refused": refused,
                   "retrieved": [h.__dict__ for h in hits]}
    res["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    audit.record("answer", user, question=question, refused=res["refused"], confidence=res["confidence"],
                 sources=[c["id"] for c in res["citations"]], answer=res["answer"], latency_ms=res["latency_ms"])
    return res
