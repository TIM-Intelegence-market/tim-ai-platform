import pytest

from src.knowledge.goathub import GoatHubKnowledge, KnowledgeDocument


def test_authorized_knowledge_search_has_citation() -> None:
    engine = GoatHubKnowledge(chunk_lines=2)
    document = KnowledgeDocument("Orderflow Notes", "notes.md", "Delta measures aggressive flow.\nAbsorption needs repeated evidence.\nUnrelated line.", True)
    engine.ingest(document)
    result = engine.search("absorption evidence")[0]
    assert result.citation.document_id == document.document_id
    assert result.citation.line_start == 1
    assert result.citation.content_hash


@pytest.mark.parametrize("chunk_lines", [0, -1])
def test_invalid_chunk_lines_is_rejected(chunk_lines: int) -> None:
    with pytest.raises(ValueError):
        GoatHubKnowledge(chunk_lines=chunk_lines)


@pytest.mark.parametrize("limit", [0, -1])
def test_search_with_non_positive_limit_returns_empty_list(limit: int) -> None:
    engine = GoatHubKnowledge(chunk_lines=2)
    engine.ingest(KnowledgeDocument("Orderflow Notes", "notes.md", "Absorption needs repeated evidence.", True))
    assert engine.search("absorption evidence", limit=limit) == []


def test_unauthorized_material_is_rejected() -> None:
    with pytest.raises(PermissionError):
        GoatHubKnowledge().ingest(KnowledgeDocument("Private", "unknown", "content", False))
