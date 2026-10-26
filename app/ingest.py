"""Extraction (Document Intelligence or local fallback) and chunking."""
import re
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings


def _dehyphenate(text: str) -> str:
    """Rejoin words split across lines with a hyphen (e.g. 'Manage-\\nment' -> 'Management')."""
    return re.sub(r"(?<=[A-Za-z])-\s*\n\s*(?=[a-z])", "", text)
@dataclass
class Page:
    source: str
    page: int
    text: str


@dataclass
class Chunk:
    id: str
    source: str
    page: int
    text: str


def _docintel_pages(path: Path) -> list[Page]:
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.core.credentials import AzureKeyCredential

    s = get_settings()
    client = DocumentIntelligenceClient(s.docintel_endpoint, AzureKeyCredential(s.docintel_key))
    with open(path, "rb") as f:
        result = client.begin_analyze_document("prebuilt-layout", body=f).result()
    return [
        Page(path.name, p.page_number, "\n".join(line.content for line in (p.lines or [])))
        for p in (result.pages or [])
    ]


def _pypdf_pages(path: Path) -> list[Page]:
    from pypdf import PdfReader

    return [Page(path.name, i, (pg.extract_text() or "")) for i, pg in enumerate(PdfReader(str(path)).pages, 1)]


def extract(path: Path) -> list[Page]:
    s = get_settings()
    if path.suffix.lower() == ".pdf":
        if s.docintel_endpoint and s.docintel_key:
            pages = _docintel_pages(path)
        else:
            pages = _pypdf_pages(path)
        return [Page(p.source, p.page, _dehyphenate(p.text)) for p in pages]
    return [Page(path.name, 1, path.read_text(encoding="utf-8"))]

def chunk_pages(pages: list[Page], size: int = 700, overlap: int = 100) -> list[Chunk]:
    """Paragraph-aware chunking: pack paragraphs up to `size` chars, carry `overlap` chars forward."""
    chunks: list[Chunk] = []
    for pg in pages:
        paras = [p.strip() for p in pg.text.replace("\r", "").split("\n\n") if p.strip()]
        buf, n = "", 0
        for para in paras:
            pieces = [para[i : i + size] for i in range(0, len(para), size)] if len(para) > size else [para]
            for piece in pieces:
                if buf and len(buf) + len(piece) + 1 > size:
                    chunks.append(Chunk(f"{pg.source}:{pg.page}:{n}", pg.source, pg.page, buf))
                    n += 1
                    buf = buf[-overlap:] if overlap else ""
                buf = f"{buf}\n{piece}".strip()
        if buf:
            chunks.append(Chunk(f"{pg.source}:{pg.page}:{n}", pg.source, pg.page, buf))
    return chunks


def ingest_path(path: Path) -> list[Chunk]:
    exts = {".pdf", ".txt", ".md"}
    files = [path] if path.is_file() else sorted(p for p in path.iterdir() if p.suffix.lower() in exts)
    out: list[Chunk] = []
    for f in files:
        out.extend(chunk_pages(extract(f)))
    return out
