import hashlib

import pytest

from src.research_evidence.documents import DocumentError
from src.research_evidence.stirling_pdf import StirlingPdfProcessor


class FakeTransport:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        if self.error:
            raise self.error
        return self.result


def processor(transport):
    return StirlingPdfProcessor(
        "http://127.0.0.1:8080", transport, clock=lambda: 0
    )


def test_extracts_text_and_preserves_provenance():
    transport = FakeTransport((200, {"text": "hello", "pages": 2}))
    result = processor(transport).extract_text(
        b"%PDF-content", filename="report.pdf", timeout_seconds=4.5
    )

    assert result.text == "hello"
    assert result.source_type == "pdf"
    assert result.provider == "stirling-pdf"
    assert result.extraction_method == "stirling.pdf_to_text"
    assert result.source_uri == "file:report.pdf"
    assert result.title == "report.pdf"
    assert result.metadata == {
        "original_sha256": hashlib.sha256(b"%PDF-content").hexdigest(),
        "processor_version": "unknown",
        "pages": 2,
    }
    assert len(transport.calls) == 1


def test_rejects_size_before_transport():
    transport = FakeTransport((200, {"text": "", "pages": 0}))
    with pytest.raises(DocumentError) as error:
        StirlingPdfProcessor(
            "http://127.0.0.1", transport, clock=lambda: 0, max_bytes=3
        ).extract_text(b"%PDF", filename="x", timeout_seconds=1)
    assert error.value.code == "size"
    assert transport.calls == []


def test_rejects_type_before_transport():
    transport = FakeTransport((200, {"text": "", "pages": 0}))
    with pytest.raises(DocumentError) as error:
        processor(transport).extract_text(
            b"not a pdf", filename="x", timeout_seconds=1
        )
    assert error.value.code == "type"
    assert transport.calls == []


@pytest.mark.parametrize(
    "result,code",
    [
        ((413, {}), "http_413"),
        ((200, {"text": 1, "pages": 1}), "parse"),
        ((200, {"text": "x", "pages": 301}), "pages"),
    ],
)
def test_rejects_response_errors(result, code):
    with pytest.raises(DocumentError) as error:
        processor(FakeTransport(result)).extract_text(
            b"%PDF-x", filename="x", timeout_seconds=1
        )
    assert error.value.code == code


def test_maps_transport_exception():
    with pytest.raises(DocumentError) as error:
        processor(FakeTransport(error=RuntimeError("offline"))).extract_text(
            b"%PDF-x", filename="x", timeout_seconds=1
        )
    assert error.value.code == "transport"


def test_requires_loopback_http_base_url():
    with pytest.raises(ValueError):
        StirlingPdfProcessor("https://127.0.0.1", FakeTransport(), clock=lambda: 0)
    with pytest.raises(ValueError):
        StirlingPdfProcessor("http://example.test", FakeTransport(), clock=lambda: 0)
