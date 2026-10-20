from typing import Protocol

from .model import Evidence


class FetchError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class WebResearchProvider(Protocol):
    name: str

    def fetch(self, url: str, *, timeout_seconds: float) -> Evidence:
        ...
