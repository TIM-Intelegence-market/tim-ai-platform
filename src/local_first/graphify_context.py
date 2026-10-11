from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from src.tim_manager.graphify_mcp import GraphifyClientError, GraphifyReadOnlyClient


class LocalGraphifyContextAdapter:
    """Prefer TIM's existing immutable Graphify graph, then bounded file metadata.

    Graphify is always treated as untrusted read-only retrieval. Failure never
    triggers a repository scan and never blocks the local worker by itself.
    """

    def __init__(self, repo_root: Path, max_files: int = 12) -> None:
        self.repo_root = repo_root.resolve()
        self.max_files = max_files

    def context_for(self, task: Any) -> dict[str, Any]:
        if os.getenv("TIM_LOCAL_GRAPHIFY", "1") != "0":
            try:
                with GraphifyReadOnlyClient(enabled_override=True) as client:
                    query = f"{task.objective}\nCurrent next action: {task.next_action}"
                    result = client.query_repository_context(query[:4096])
                return {
                    "source": "graphify_read_only",
                    "trust_class": result.trust_class,
                    "graph_hash": result.graph_hash,
                    "source_refs": list(result.source_refs)[: self.max_files],
                    "results": list(result.results)[: self.max_files],
                    "warnings": list(result.warnings),
                    "truncated": result.truncated,
                }
            except (GraphifyClientError, OSError, ValueError) as exc:
                graphify_error = type(exc).__name__
        else:
            graphify_error = "disabled_by_TIM_LOCAL_GRAPHIFY"

        files: list[dict[str, Any]] = []
        for relative in list(task.allowed_paths)[: self.max_files]:
            candidate = (self.repo_root / relative).resolve()
            if self.repo_root not in candidate.parents and candidate != self.repo_root:
                continue
            if not candidate.is_file():
                continue
            digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
            files.append({"path": relative, "sha256": digest, "size": candidate.stat().st_size})
        return {
            "source": "bounded_repo_index",
            "graphify_status": graphify_error,
            "files": files,
        }
