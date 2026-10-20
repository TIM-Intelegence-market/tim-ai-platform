from dataclasses import dataclass
from typing import Protocol


class DocumentError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Evidence:
    source_type: str
    provider: str
    extraction_method: str
    source_uri: str
    title: str
    text: str
    metadata: dict


class DocumentProcessor(Protocol):
    name: str

    def extract_text(
        self, data: bytes, *, filename: str, timeout_seconds: float
    ) -> Evidence:
        ...
