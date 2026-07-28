from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


def _tokens(text: str) -> set[str]:
    return {item for item in re.findall(r"[a-z0-9]{3,}", text.lower())}


@dataclass(frozen=True, slots=True)
class KnowledgeDocument:
    title: str
    source: str
    content: str
    authorized: bool
    provenance: str = "AUTHORIZED_PERSONAL_KNOWLEDGE"

    @property
    def document_id(self) -> str:
        return "knowledge_" + hashlib.sha256(f"{self.source}|{self.title}|{self.content}".encode()).hexdigest()[:20]


@dataclass(frozen=True, slots=True)
class Citation:
    document_id: str
    title: str
    source: str
    line_start: int
    line_end: int
    content_hash: str


@dataclass(frozen=True, slots=True)
class KnowledgeResult:
    excerpt: str
    score: float
    citation: Citation


class GoatHubKnowledge:
    def __init__(self, chunk_lines: int = 8) -> None:
        self.chunk_lines = chunk_lines
        self.documents: dict[str, KnowledgeDocument] = {}

    def ingest(self, document: KnowledgeDocument) -> bool:
        if not document.authorized:
            raise PermissionError("Knowledge material must be explicitly authorized")
        if not document.content.strip():
            raise ValueError("Knowledge content is empty")
        if document.document_id in self.documents:
            return False
        self.documents[document.document_id] = document
        return True

    def search(self, query: str, limit: int = 10) -> list[KnowledgeResult]:
        query_tokens = _tokens(query)
        if not query_tokens:
            return []
        results = []
        for doc in self.documents.values():
            lines = doc.content.splitlines()
            for start in range(0, len(lines), self.chunk_lines):
                chunk = "\n".join(lines[start:start + self.chunk_lines]).strip()
                chunk_tokens = _tokens(chunk)
                overlap = query_tokens & chunk_tokens
                if not overlap:
                    continue
                score = len(overlap) / len(query_tokens | chunk_tokens)
                citation = Citation(doc.document_id, doc.title, doc.source, start + 1, min(len(lines), start + self.chunk_lines), hashlib.sha256(chunk.encode()).hexdigest())
                results.append(KnowledgeResult(chunk, round(score, 6), citation))
        return sorted(results, key=lambda item: (-item.score, item.citation.document_id, item.citation.line_start))[:limit]

    def ingest_file(self, path: Path, authorized: bool) -> KnowledgeDocument:
        document = KnowledgeDocument(path.stem, str(path.resolve()), path.read_text(encoding="utf-8"), authorized)
        self.ingest(document)
        return document
