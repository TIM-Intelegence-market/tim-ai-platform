import hashlib
from urllib.parse import urlsplit

from .documents import DocumentError, Evidence


class StirlingPdfProcessor:
    name = "stirling-pdf"

    def __init__(
        self,
        base_url,
        transport,
        *,
        clock,
        max_bytes=20_000_000,
        max_pages=300,
        processor_version="unknown",
    ):
        parsed = urlsplit(base_url)
        if parsed.scheme != "http" or parsed.username or parsed.password:
            raise ValueError("base_url must be loopback http")
        if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("base_url must be loopback http")
        self.base_url = base_url.rstrip("/")
        self.transport = transport
        self.clock = clock
        self.max_bytes = max_bytes
        self.max_pages = max_pages
        self.processor_version = processor_version

    def extract_text(self, data: bytes, *, filename: str, timeout_seconds: float) -> Evidence:
        if not isinstance(data, bytes) or not data or len(data) > self.max_bytes:
            raise DocumentError("size")
        if not data.startswith(b"%PDF-"):
            raise DocumentError("type")

        digest = hashlib.sha256(data).hexdigest()
        try:
            status, payload = self.transport(
                "POST",
                self.base_url + "/api/v1/convert/pdf/text",
                {"filename": filename, "sha256": digest},
                data,
                timeout_seconds,
            )
        except Exception as exc:
            raise DocumentError("transport") from exc

        if status != 200:
            raise DocumentError(f"http_{status}")
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("text"), str)
            or not isinstance(payload.get("pages"), int)
            or isinstance(payload.get("pages"), bool)
        ):
            raise DocumentError("parse")

        pages = payload["pages"]
        if pages > self.max_pages:
            raise DocumentError("pages")

        return Evidence(
            source_type="pdf",
            provider="stirling-pdf",
            extraction_method="stirling.pdf_to_text",
            source_uri="file:" + filename,
            title=filename,
            text=payload["text"],
            metadata={
                "original_sha256": digest,
                "processor_version": self.processor_version,
                "pages": pages,
            },
        )
