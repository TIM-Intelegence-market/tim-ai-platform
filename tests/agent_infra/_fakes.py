"""Unique-name test fakes (importable without conftest collisions)."""
from __future__ import annotations

from contextlib import contextmanager


class FakeSerena:
    """Canned serena answers for CandleAggregator-style flows."""

    def __init__(self, symbols=None, references=None) -> None:
        self._symbols = symbols if symbols is not None else [{
            "name_path": "CandleAggregator", "kind": "Class",
            "relative_path": "src/data_ingestion/aggregator.py",
            "body_location": {"start_line": 53, "end_line": 83}}]
        self._references = references if references is not None else {
            "main.py": {"Variable": [{
                "name_path": "TIMApplication/aggregator",
                "body_location": {"start_line": 45, "end_line": 45},
                "content_around_reference": "self.aggregator = CandleAggregator(...)"}]},
            "tests/test_aggregator.py": {"Function": [{
                "name_path": "test_add_trade",
                "body_location": {"start_line": 1, "end_line": 9},
                "content_around_reference": "agg = CandleAggregator((\"1m\",))"}]},
        }

    def find_symbol(self, pattern, relative_path="", substring_matching=False):
        return [s for s in self._symbols
                if pattern in s["name_path"] or s["name_path"] in pattern]

    def find_referencing_symbols(self, name_path, relative_path):
        return self._references


def fake_serena_factory(fake: FakeSerena):
    @contextmanager
    def factory():
        yield fake
    return factory
