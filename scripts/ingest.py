"""Usage: python -m scripts.ingest [path=data/docs]  (STORE=azure to index into Azure AI Search)"""
import sys
from pathlib import Path

from app.ingest import ingest_path
from app.store import get_store


def main(path: str = "data/docs") -> int:
    chunks = ingest_path(Path(path))
    store = get_store()
    store.reset()
    n = store.add(chunks)
    print(f"Indexed {n} chunks from {path}")
    return n


if __name__ == "__main__":
    main(*sys.argv[1:2])
