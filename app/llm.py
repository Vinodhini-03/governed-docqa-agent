"""Provider layer: swap the LLM via LLM_PROVIDER without touching the workflow."""
import os
import re

import httpx
import time

from app.config import get_settings, secret
from app.textutil import tokens


SYSTEM = (
    "You answer questions using ONLY the numbered context passages. Cite every claim with its passage "
    "number like [1]. If the context does not contain the answer, reply exactly: I don't know based on "
    "the provided documents."
)


def _prompt(question: str, contexts: list[str]) -> str:
    ctx = "\n\n".join(f"[{i}] {c}" for i, c in enumerate(contexts, 1))
    return f"Context:\n{ctx}\n\nQuestion: {question}\nAnswer:"


def _extractive(question: str, contexts: list[str]) -> str:
    q = set(tokens(question))
    cands = []
    for i, c in enumerate(contexts, 1):
        for sent in re.split(r"(?<=[.!?])\s+|\n", c):
            if len(sent.strip()) < 15:
                continue
            ov = len(q & set(tokens(sent)))
            cands.append((ov, -i, sent.strip(), i))
    cands.sort(reverse=True)
    best = [c for c in cands[:2] if c[0] > 0]
    if not best:
        return "I don't know based on the provided documents."
    return " ".join(f"{s.rstrip('.')}. [{i}]" for _, _, s, i in best)


def _openai_style(url: str, headers: dict, body: dict) -> str:
    for attempt in range(6):
        r = httpx.post(url, headers=headers, json=body, timeout=60)
        if r.status_code == 429 and attempt < 5:
            time.sleep(min(float(r.headers.get("retry-after", 5 * (attempt + 1))), 60))
            continue
        if r.status_code >= 400:
            raise RuntimeError(f"LLM request failed ({r.status_code}): {r.text[:300]}")
        return r.json()["choices"][0]["message"]["content"].strip()
    raise RuntimeError("LLM request failed after retries")


def generate(question: str, contexts: list[str]) -> str:
    provider = get_settings().llm_provider
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": _prompt(question, contexts)}]
    if provider == "groq":
        return _openai_style(
            "https://api.groq.com/openai/v1/chat/completions",
            {"Authorization": f"Bearer {secret('GROQ_API_KEY')}"},
            {"model": os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"), "messages": msgs, "temperature": 0},
        )
    if provider == "azure_openai":
        url = (
            f"{os.environ['AZURE_OPENAI_ENDPOINT'].rstrip('/')}/openai/deployments/"
            f"{os.environ['AZURE_OPENAI_CHAT_DEPLOYMENT']}/chat/completions"
            f"?api-version={os.getenv('AZURE_OPENAI_API_VERSION', '2024-06-01')}"
        )
        return _openai_style(url, {"api-key": secret("AZURE_OPENAI_KEY")}, {"messages": msgs, "temperature": 0})
    if provider == "ollama":
        r = httpx.post(
            f"{os.getenv('OLLAMA_URL', 'http://localhost:11434')}/api/chat",
            json={"model": os.getenv("OLLAMA_MODEL", "llama3.2"), "messages": msgs, "stream": False,
                  "options": {"temperature": 0}},
            timeout=120,
        )
        r.raise_for_status()
        return r.json()["message"]["content"].strip()
    return _extractive(question, contexts)
