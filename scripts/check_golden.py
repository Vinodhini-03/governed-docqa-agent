import json
import sys
from pathlib import Path

from app.ingest import ingest_path


def norm(s: str) -> str:
    return "".join(s.lower().split())


chunks = ingest_path(Path("data/real_docs"))
golden = Path(sys.argv[1] if len(sys.argv) > 1 else "eval/golden_real.jsonl")
bad = 0
for line in golden.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    r = json.loads(line)
    if not r["in_scope"]:
        continue
    hits = [c for c in chunks if r["source"] == c.source and norm(r["phrase"]) in norm(c.text)]
    if not hits:
        bad += 1
        print("PHRASE NOT FOUND:", r["question"], "->", r["phrase"])
    elif len(hits) > 1:
        print("appears in", len(hits), "chunks (fine):", r["phrase"])
print("problems:", bad)