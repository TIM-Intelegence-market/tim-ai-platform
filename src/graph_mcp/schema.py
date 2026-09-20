"""Canonical graph schema: node/edge types, stable identities, record
contracts, deterministic hashing (STEPS 3-5)."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from src.graph_mcp import SCHEMA_VERSION


class NodeType(StrEnum):
    REPOSITORY = "Repository"
    DIRECTORY = "Directory"
    FILE = "File"
    MODULE = "Module"
    CLASS = "Class"
    FUNCTION = "Function"
    METHOD = "Method"
    TEST = "Test"
    DATABASE = "Database"
    TABLE = "Table"
    COLUMN = "Column"
    SERVICE = "Service"
    PROCESS = "Process"
    MISSION = "Mission"
    GATE = "Gate"
    INCIDENT = "Incident"
    ERROR_FINGERPRINT = "ErrorFingerprint"
    REPAIR_RECIPE = "RepairRecipe"
    AGENT = "Agent"
    TOOL = "Tool"
    GITHUB_ISSUE = "GitHubIssue"
    GIT_COMMIT = "GitCommit"
    DECISION = "Decision"
    OBSIDIAN_NOTE = "ObsidianNote"


class EdgeType(StrEnum):
    CONTAINS = "CONTAINS"
    IMPORTS = "IMPORTS"
    CALLS = "CALLS"
    DEFINES = "DEFINES"
    TESTS = "TESTS"
    READS = "READS"
    WRITES = "WRITES"
    DEPENDS_ON = "DEPENDS_ON"
    IMPLEMENTS = "IMPLEMENTS"
    VERIFIES = "VERIFIES"
    BLOCKS = "BLOCKS"
    UNBLOCKS = "UNBLOCKS"
    REQUIRES = "REQUIRES"
    CAUSED_BY = "CAUSED_BY"
    REPAIRED_BY = "REPAIRED_BY"
    REPRODUCED_BY = "REPRODUCED_BY"
    VALIDATED_BY = "VALIDATED_BY"
    ASSIGNED_TO = "ASSIGNED_TO"
    USES_TOOL = "USES_TOOL"
    RELATED_TO = "RELATED_TO"
    DOCUMENTED_BY = "DOCUMENTED_BY"
    SUPERSEDES = "SUPERSEDES"
    REFERENCES = "REFERENCES"
    PARENT_OF = "PARENT_OF"
    CHILD_OF = "CHILD_OF"


IDENTIFIER = re.compile(r"^[A-Za-z0-9_./:@#%-]{1,512}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stable_id(kind: str, *parts: str) -> str:
    """Deterministic identity — same entity, same id, every index run.
    Path-unfriendly characters are percent-encoded (stable across runs);
    no random UUIDs anywhere in this package."""
    from urllib.parse import quote
    identity = quote(":".join(str(p) for p in parts), safe=":/._-")
    if not identity or len(identity) > 512:
        raise ValueError(f"invalid identity parts: {identity!r}")
    node_id = f"{kind}:{identity}"
    if not IDENTIFIER.match(node_id):
        raise ValueError(f"invalid stable id: {node_id!r}")
    return node_id


def content_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                   default=str).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class Node:
    id: str
    type: NodeType
    name: str
    source: str                     # indexer that produced the node
    path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name or len(self.name) > 512:
            raise ValueError(f"invalid node name for {self.id}")
        if not IDENTIFIER.match(self.id):
            raise ValueError(f"invalid node id: {self.id!r}")

    def record(self, observed_at: str) -> dict[str, Any]:
        """Canonical node contract (STEP 5)."""
        return {
            "id": self.id,
            "type": self.type.value,
            "name": self.name,
            "source": self.source,
            "path": self.path,
            "metadata": self.metadata,
            "content_hash": self.identity_hash(),
            "observed_at": observed_at,
            "schema_version": SCHEMA_VERSION,
        }

    def identity_hash(self) -> str:
        """Hash over identity-relevant content (excludes observed_at)."""
        return content_hash({
            "id": self.id, "type": self.type.value, "name": self.name,
            "path": self.path, "metadata": self.metadata,
        })


@dataclass(frozen=True, slots=True)
class Edge:
    src: str
    dst: str
    type: EdgeType
    metadata: dict[str, Any] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.src == self.dst:
            raise ValueError(f"self-loop refused: {self.src}")
        for endpoint in (self.src, self.dst):
            if not IDENTIFIER.match(endpoint):
                raise ValueError(f"invalid edge endpoint: {endpoint!r}")
        # Provenance rule: non-trivial relationship classes require evidence.
        if self.type in _EVIDENCE_REQUIRED and not self.evidence:
            raise ValueError(f"edge {self.type} requires evidence: {self.src}->{self.dst}")

    def record(self) -> dict[str, Any]:
        """Canonical edge contract (STEP 5)."""
        return {
            "from": self.src,
            "to": self.dst,
            "type": self.type.value,
            "metadata": self.metadata,
            "evidence": self.evidence,
            "schema_version": SCHEMA_VERSION,
        }

    def identity_hash(self) -> str:
        return content_hash({
            "from": self.src, "to": self.dst, "type": self.type.value,
            "metadata": self.metadata, "evidence": sorted(self.evidence),
        })


# Trivial structural edges carry their endpoints as inherent evidence;
# semantic claims about behavior must cite where the claim comes from.
_EVIDENCE_REQUIRED = frozenset({
    EdgeType.READS, EdgeType.WRITES, EdgeType.CALLS, EdgeType.TESTS,
    EdgeType.IMPLEMENTS, EdgeType.VERIFIES, EdgeType.BLOCKS, EdgeType.UNBLOCKS,
    EdgeType.CAUSED_BY, EdgeType.REPAIRED_BY, EdgeType.REPRODUCED_BY,
    EdgeType.VALIDATED_BY, EdgeType.ASSIGNED_TO, EdgeType.SUPERSEDES,
})


def node_set_hash(nodes: list[dict[str, Any]]) -> str:
    return hashlib.sha256("\n".join(
        f"{n['id']}|{n['type']}|{n['content_hash']}"
        for n in sorted(nodes, key=lambda n: n["id"])
    ).encode()).hexdigest()


def edge_set_hash(edges: list[dict[str, Any]]) -> str:
    return hashlib.sha256("\n".join(
        f"{e['from']}|{e['to']}|{e['type']}|{e['metadata']}"
        for e in sorted(edges, key=lambda e: (e["from"], e["to"], e["type"]))
    ).encode()).hexdigest()
