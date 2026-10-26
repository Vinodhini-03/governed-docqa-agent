"""Embeddings: Azure OpenAI if configured, fastembed if EMBEDDINGS=fastembed, else an offline hashing embedder."""
import hashlib
import math
import os

import httpx

from app.config import secret
from app.textutil import tokens

HASH_DIM = 512
FASTEMBED_DIM = 384
_fe = None


def _azure_ready() -> bool:
    return bool(os.getenv("AZURE_OPENAI_ENDPOINT") and os.getenv("AZURE_OPENAI_EMBED_DEPLOYMENT"))


def _fastembed_ready() -> bool:
    return os.getenv("EMBEDDINGS", "").lower() == "fastembed"


def dim() -> int:
    if _azure_ready():
        return 1536
    return FASTEMBED_DIM if _fastembed_ready() else HASH_DIM


def _hash_embed(text: str) -> list[float]:
    toks = tokens(text)
    feats = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
    v = [0.0] * HASH_DIM
    for f in feats:
        h = int(hashlib.sha1(f.encode()).hexdigest(), 16)
        v[h % HASH_DIM] += 1.0 if (h >> 100) & 1 else -1.0
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


def _fastembed(texts: list[str]) -> list[list[float]]:
    global _fe
    if _fe is None:
        from fastembed import TextEmbedding

        _fe = TextEmbedding("BAAI/bge-small-en-v1.5")
    out = []
    for vec in _fe.embed(texts):
        v = [float(x) for x in vec]
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        out.append([x / n for x in v])
    return out


def embed(texts: list[str]) -> list[list[float]]:
    if _azure_ready():
        url = (
            f"{os.environ['AZURE_OPENAI_ENDPOINT'].rstrip('/')}/openai/deployments/"
            f"{os.environ['AZURE_OPENAI_EMBED_DEPLOYMENT']}/embeddings"
            f"?api-version={os.getenv('AZURE_OPENAI_API_VERSION', '2024-06-01')}"
        )
        r = httpx.post(url, headers={"api-key": secret("AZURE_OPENAI_KEY")}, json={"input": texts}, timeout=60)
        r.raise_for_status()
        return [d["embedding"] for d in sorted(r.json()["data"], key=lambda d: d["index"])]
    if _fastembed_ready():
        return _fastembed(texts)
    return [_hash_embed(t) for t in texts]