"""Embeddings: Azure OpenAI when configured, otherwise a deterministic hashing embedder (offline)."""
import hashlib
import math
import os

import httpx

from app.config import secret
from app.textutil import tokens

HASH_DIM = 512


def _azure_ready() -> bool:
    return bool(os.getenv("AZURE_OPENAI_ENDPOINT") and os.getenv("AZURE_OPENAI_EMBED_DEPLOYMENT"))


def dim() -> int:
    return 1536 if _azure_ready() else HASH_DIM


def _hash_embed(text: str) -> list[float]:
    toks = tokens(text)
    feats = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
    v = [0.0] * HASH_DIM
    for f in feats:
        h = int(hashlib.sha1(f.encode()).hexdigest(), 16)
        v[h % HASH_DIM] += 1.0 if (h >> 100) & 1 else -1.0
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


def embed(texts: list[str]) -> list[list[float]]:
    if not _azure_ready():
        return [_hash_embed(t) for t in texts]
    url = (
        f"{os.environ['AZURE_OPENAI_ENDPOINT'].rstrip('/')}/openai/deployments/"
        f"{os.environ['AZURE_OPENAI_EMBED_DEPLOYMENT']}/embeddings"
        f"?api-version={os.getenv('AZURE_OPENAI_API_VERSION', '2024-06-01')}"
    )
    r = httpx.post(url, headers={"api-key": secret("AZURE_OPENAI_KEY")}, json={"input": texts}, timeout=60)
    r.raise_for_status()
    return [d["embedding"] for d in sorted(r.json()["data"], key=lambda d: d["index"])]
