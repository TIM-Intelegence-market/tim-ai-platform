"""Indexers: each owns a `source` prefix and produces Node/Edge records.

Contract (STEP 26/27): indexers return (nodes, edges, metrics) where metrics
carry at least FILES_SCANNED / FILES_CHANGED / NODES_ADDED / EDGES_ADDED /
INDEX_DURATION_SECONDS. Redaction is applied by the service before anything
reaches the store."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class IndexResult:
    source: str
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)  # path -> sha256
