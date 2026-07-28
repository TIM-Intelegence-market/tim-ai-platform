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


def test_unauthorized_material_is_rejected() -> None:
    with pytest.raises(PermissionError):
        GoatHubKnowledge().ingest(KnowledgeDocument("Private", "unknown", "content", False))
