"""Golden-set evaluation. Exits 1 if any threshold is missed (used as a CI gate).

Metrics
- recall@k:         an expected-source chunk containing the expected phrase is in the top-k retrieved.
- citation accuracy: of answered in-scope questions, share whose cited chunks include the expected phrase.
- faithfulness:     LEXICAL PROXY - share of answer sentences whose content words are >=60% present in the
                    cited text. Swap in an LLM judge (e.g. Ragas/DeepEval) for a stronger signal.
- refusal accuracy: out-of-scope / unsafe questions must be refused.
"""
import json
import os
import re
import statistics
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("STORE", "local")
os.environ["INDEX_PATH"] = str(Path(tempfile.mkdtemp()) / "eval_index.json")
os.environ["AUDIT_PATH"] = str(Path(tempfile.mkdtemp()) / "audit.jsonl")

from app import rag
from app.ingest import ingest_path
from app.store import get_store
from app.textutil import tokens

THRESH = {"recall_at_5": 0.85, "faithfulness": 0.85, "citation_accuracy": 0.90, "refusal_accuracy": 0.90}


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


def main() -> int:
    store = get_store()
    store.reset()
    store.add(ingest_path(ROOT / "data" / "docs"))
    rows = [json.loads(x) for x in (ROOT / "eval" / "golden.jsonl").read_text().splitlines() if x.strip()]
    rec, cit, fth, ref, lat, fails = [], [], [], [], [], []
    for r in rows:
        res = rag.answer(r["question"], "eval")
        lat.append(res["latency_ms"])
        if not r["in_scope"]:
            ref.append(res["refused"])
            if not res["refused"]:
                fails.append({"q": r["question"], "why": "should have refused"})
            continue
        phrase = r["phrase"].lower()
        hit = any(h["source"] == r["source"] and phrase in h["text"].lower() for h in res["retrieved"][:5])
        rec.append(hit)
        if res["refused"]:
            fails.append({"q": r["question"], "why": "wrongly refused"})
            continue
        good = any(phrase in c["text"].lower() for c in res["citations"])
        cit.append(good)
        fth.append(faithful(res["answer"], res["citations"]))
        if not (hit and good):
            fails.append({"q": r["question"], "why": f"recall={hit} citation={good}"})
    def avg(v):
        return round(sum(v) / len(v), 3) if v else 0.0

    m = {"recall_at_5": avg(rec), "citation_accuracy": avg(cit), "faithfulness": avg(fth),
         "refusal_accuracy": avg(ref), "latency_p50_ms": round(statistics.median(lat), 1),
         "latency_p95_ms": pct(lat, 95), "n_questions": len(rows)}
    (ROOT / "eval" / "results.json").write_text(json.dumps({"metrics": m, "failures": fails}, indent=2))
    print(json.dumps(m, indent=2))
    for f in fails:
        print("FAIL:", f)
    bad = {k: (m[k], t) for k, t in THRESH.items() if m[k] < t}
    if bad:
        print("THRESHOLDS MISSED:", bad)
        return 1
    print("All thresholds met.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
