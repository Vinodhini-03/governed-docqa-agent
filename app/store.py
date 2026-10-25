"""Vector + keyword hybrid stores: LocalStore (offline) and AzureSearchStore (Azure AI Search)."""
import json
import math
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from app import embeddings
from app.config import get_settings
from app.ingest import Chunk
from app.textutil import tokens


@dataclass
class Hit:
    id: str
    source: str
    page: int
    text: str
    score: float


class LocalStore:
    def __init__(self, path: str):
        self.path = Path(path)
        self.rows: list[dict] = json.loads(self.path.read_text()) if self.path.exists() else []

    def reset(self) -> None:
        self.rows = []
        self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.rows))

    def add(self, chunks: list[Chunk]) -> int:
        vecs = embeddings.embed([c.text for c in chunks])
        self.rows.extend({**asdict(c), "embedding": v} for c, v in zip(chunks, vecs))
        self._save()
        return len(chunks)

    def search(self, query: str, k: int = 5) -> list[Hit]:
        if not self.rows:
            return []
        qv = embeddings.embed([query])[0]
        qt = tokens(query)
        docs = [tokens(r["text"]) for r in self.rows]
        avg = sum(map(len, docs)) / len(docs) or 1
        df = Counter(t for d in docs for t in set(d))
        n = len(docs)
        bm = []
        for d in docs:
            tf = Counter(d)
            s = 0.0
            for t in qt:
                if t in tf:
                    idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                    s += idf * tf[t] * 2.2 / (tf[t] + 1.2 * (0.25 + 0.75 * len(d) / avg))
            bm.append(s)
        top = max(bm) or 1.0
        scored = []
        for r, b in zip(self.rows, bm):
            cos = sum(a * c for a, c in zip(qv, r["embedding"]))
            scored.append((0.5 * cos + 0.5 * b / top, r))
        scored.sort(key=lambda x: -x[0])
        return [Hit(r["id"], r["source"], r["page"], r["text"], s) for s, r in scored[:k]]


class AzureSearchStore:
    """Azure AI Search with hybrid (keyword + vector) retrieval. Not exercised offline."""

    def __init__(self):
        from azure.core.credentials import AzureKeyCredential
        from azure.search.documents import SearchClient
        from azure.search.documents.indexes import SearchIndexClient

        s = get_settings()
        cred = AzureKeyCredential(s.search_key)
        self.index_name = s.search_index
        self.index_client = SearchIndexClient(s.search_endpoint, cred)
        self.client = SearchClient(s.search_endpoint, s.search_index, cred)

    def reset(self) -> None:
        from azure.search.documents.indexes.models import (
            HnswAlgorithmConfiguration,
            SearchableField,
            SearchField,
            SearchFieldDataType,
            SearchIndex,
            SimpleField,
            VectorSearch,
            VectorSearchProfile,
        )

        fields = [
            SimpleField(name="id", type=SearchFieldDataType.String, key=True),
            SimpleField(name="source", type=SearchFieldDataType.String, filterable=True),
            SimpleField(name="page", type=SearchFieldDataType.Int32, filterable=True),
            SearchableField(name="text", type=SearchFieldDataType.String),
            SearchField(
                name="embedding",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                searchable=True,
                vector_search_dimensions=embeddings.dim(),
                vector_search_profile_name="hnsw-profile",
            ),
        ]
        vs = VectorSearch(
            algorithms=[HnswAlgorithmConfiguration(name="hnsw")],
            profiles=[VectorSearchProfile(name="hnsw-profile", algorithm_configuration_name="hnsw")],
        )
        try:
            self.index_client.delete_index(self.index_name)
        except Exception:  # noqa: BLE001
            pass
        self.index_client.create_index(SearchIndex(name=self.index_name, fields=fields, vector_search=vs))

    @staticmethod
    def _key(cid: str) -> str:  # Search keys allow letters, digits, _ - =
        return "".join(ch if ch.isalnum() else "_" for ch in cid)

    def add(self, chunks: list[Chunk]) -> int:
        vecs = embeddings.embed([c.text for c in chunks])
        docs = [
            {"id": self._key(c.id), "source": c.source, "page": c.page, "text": c.text, "embedding": v}
            for c, v in zip(chunks, vecs)
        ]
        self.client.upload_documents(docs)
        return len(docs)

    def search(self, query: str, k: int = 5) -> list[Hit]:
        from azure.search.documents.models import VectorizedQuery

        vq = VectorizedQuery(vector=embeddings.embed([query])[0], k_nearest_neighbors=k, fields="embedding")
        res = self.client.search(search_text=query, vector_queries=[vq], top=k)
        return [Hit(r["id"], r["source"], r["page"], r["text"], r["@search.score"]) for r in res]


_store = None


def get_store():
    global _store
    if _store is None:
        s = get_settings()
        _store = AzureSearchStore() if s.store == "azure" else LocalStore(s.index_path)
    return _store


def reset_store_cache() -> None:
    global _store
    _store = None
