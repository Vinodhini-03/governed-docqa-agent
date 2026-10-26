"""Shows where the expected chunk ranks for each golden question. Uses EVAL_DOCS / EVAL_GOLDEN."""
import json
import os
import tempfile
from pathlib import Path

os.environ["INDEX_PATH"] = str(Path(tempfile.mkdtemp()) / "i.json")
os.environ["AUDIT_PATH"] = str(Path(tempfile.mkdtemp()) / "a.jsonl")

from app.ingest import ingest_path  # noqa: E402
from app.store import get_store  # noqa: E402
from app.textutil import coverage  # noqa: E402


def norm(s):
    return "".join(s.lower().split())


store = get_store()
store.reset()
store.add(ingest_path(Path(os.getenv("EVAL_DOCS", "data/docs"))))
golden = Path(os.getenv("EVAL_GOLDEN", "eval/golden.jsonl"))
for line in golden.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    r = json.loads(line)
    hits = store.search(r["question"], 30)
    conf = max((coverage(r["question"], h.text) for h in hits[:5]), default=0)
    if r["in_scope"]:
        rank = next((i for i, h in enumerate(hits, 1) if norm(r["phrase"]) in norm(h.text)), None)
        if rank is None or rank > 4 or conf < 0.5:
            print(f"rank={rank} conf={conf:.2f} | {r['question']}")
    elif conf >= 0.5:
        print(f"NOT REFUSED conf={conf:.2f} | {r['question']}")