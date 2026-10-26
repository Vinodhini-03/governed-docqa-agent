"""Golden-set evaluation. Exits 1 if any threshold is missed (used as a CI gate).

Metrics
- recall@k:          an expected-source chunk containing the expected phrase is in the top-k retrieved.
- citation accuracy: of answered in-scope questions, share whose cited chunks include the expected phrase.
- faithfulness:      LEXICAL PROXY - share of answer sentences whose content words are >=60% present in the
                     cited text. Swap in an LLM judge (e.g. Ragas/DeepEval) for a stronger signal.
- refusal accuracy:  out-of-scope / unsafe questions must be refused.

By default it runs on data/docs with eval/golden.jsonl (this is what CI uses). To evaluate other documents:
    $env:EVAL_DOCS="data/real_docs"; $env:EVAL_GOLDEN="eval/golden_real.jsonl"; python eval/run_eval.py
"""
import json
import os
import re
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("STORE", "local")
os.environ["INDEX_PATH"] = str(Path(tempfile.mkdtemp()) / "eval_index.json")
os.environ["AUDIT_PATH"] = str(Path(tempfile.mkdtemp()) / "audit.jsonl")

from app import rag  # noqa: E402
from app.ingest import ingest_path  # noqa: E402
from app.store import get_store  # noqa: E402
from app.textutil import tokens  # noqa: E402

THRESH = {"recall_at_5": 0.85, "faithfulness": 0.85, "citation_accuracy": 0.90, "refusal_accuracy": 0.90}
DOCS = ROOT / os.getenv("EVAL_DOCS", "data/docs")
GOLDEN = ROOT / os.getenv("EVAL_GOLDEN", "eval/golden.jsonl")
RESULTS = ROOT / "eval" / ("results.json" if "EVAL_GOLDEN" not in os.environ else "results_custom.json")


def norm(s: str) -> str:
    return "".join(s.lower().split())


def faithful(answer: str, cites: list[dict]) -> float:
    ctx = set(tokens(" ".join(c["text"] for c in cites)))
    sents = [s for s in re.split(r"(?<=[.!?])\s+", re.sub(r"\[\d+\]", "", answer)) if len(tokens(s)) > 0]
    if not sents or not ctx:
        return 0.0
    ok = sum(len(set(tokens(s)) & ctx) / len(set(tokens(s))) >= 0.6 for s in sents)
    return ok / len(sents)


def pct(vals, p):
    vals = sorted(vals)
    return vals[min(len(vals) - 1, round(p / 100 * (len(vals) - 1)))]


def avg(v):
    return round(sum(v) / len(v), 3) if v else None


def main() -> int:
    store = get_store()
    store.reset()
    store.add(ingest_path(DOCS))
    rows = [json.loads(x) for x in GOLDEN.read_text(encoding="utf-8").splitlines() if x.strip()]
    rec, cit, fth, ref, lat, fails = [], [], [], [], [], []
    time.sleep(float(os.getenv("EVAL_DELAY", "0")))
    for r in rows:
        res = rag.answer(r["question"], "eval")
        lat.append(res["latency_ms"])
        if not r["in_scope"]:
            ref.append(res["refused"])
            if not res["refused"]:
                fails.append({"q": r["question"], "why": "should have refused"})
            continue
        phrase = norm(r["phrase"])
        hit = any(h["source"] == r["source"] and phrase in norm(h["text"]) for h in res["retrieved"][:5])
        rec.append(hit)
        if res["refused"]:
            fails.append({"q": r["question"], "why": "wrongly refused", "retrieved_ok": hit})
            continue
        good = any(phrase in norm(c["text"]) for c in res["citations"])
        cit.append(good)
        fth.append(faithful(res["answer"], res["citations"]))
        if not (hit and good):
            fails.append({"q": r["question"], "why": f"recall={hit} citation={good}"})
    m = {"recall_at_5": avg(rec), "citation_accuracy": avg(cit), "faithfulness": avg(fth),
         "refusal_accuracy": avg(ref), "latency_p50_ms": round(statistics.median(lat), 1),
         "latency_p95_ms": pct(lat, 95), "n_questions": len(rows)}
    RESULTS.write_text(json.dumps({"metrics": m, "failures": fails}, indent=2), encoding="utf-8")
    print(json.dumps(m, indent=2))
    for f in fails:
        print("FAIL:", f)
    bad = {k: (m[k], t) for k, t in THRESH.items() if m[k] is not None and m[k] < t}
    if bad:
        print("THRESHOLDS MISSED:", bad)
        return 1
    print("All thresholds met.")
    return 0


if __name__ == "__main__":
    sys.exit(main())