"""GitHub graph adapter (STEP 14): provider-based, credential-free.

`index_payload` maps a documented provider payload (issues, commits, PRs)
onto graph records. No network access happens here; a provider process
may call it with data it legitimately fetched. Unit tests use fixtures —
basic tests require no credentials by design."""
from __future__ import annotations

from typing import Any

from src.graph_mcp.indexer import IndexResult
from src.graph_mcp.schema import Edge, EdgeType, Node, NodeType, stable_id, utc_now


class GithubIndexer:
    source = "github"

    def index_payload(self, payload: dict[str, Any]) -> IndexResult:
        result = IndexResult(source=self.source)
        observed = utc_now()
        src = self.source
        for issue in payload.get("issues", []):
            number = int(issue["number"])
            issue_id = stable_id("github:issue", str(number))
            result.nodes.append(Node(
                issue_id, NodeType.GITHUB_ISSUE, f"#{number} {issue.get('title', '')}",
                src, "", {"state": issue.get("state", ""), "url": issue.get("url", "")}
            ).record(observed))
            parent = issue.get("parent")
            if parent:
                result.edges.append(Edge(
                    stable_id("github:issue", str(int(parent))), issue_id,
                    EdgeType.PARENT_OF, {},
                    evidence=[issue.get("url", "provider payload")]).record())
            for blocked in issue.get("blocked_by", []):
                result.edges.append(Edge(
                    stable_id("github:issue", str(int(blocked))), issue_id,
                    EdgeType.BLOCKS, {},
                    evidence=[issue.get("url", "provider payload")]).record())
        for commit in payload.get("commits", []):
            sha = str(commit["sha"])[:12]
            commit_id = stable_id("github:commit", sha)
            result.nodes.append(Node(
                commit_id, NodeType.GIT_COMMIT, sha, src, "",
                {"message": str(commit.get("message", ""))[:200]}
            ).record(observed))
            for issue_number in commit.get("implements", []):
                result.edges.append(Edge(
                    commit_id, stable_id("github:issue", str(int(issue_number))),
                    EdgeType.IMPLEMENTS, {},
                    evidence=[f"commit {sha}"]).record())
        for pull in payload.get("pull_requests", []):
            for issue_number in pull.get("implements", []):
                pr_id = stable_id("github:pr", str(int(pull["number"])))
                result.nodes.append(Node(
                    pr_id, NodeType.GITHUB_ISSUE, f"PR #{pull['number']}", src, "",
                    {"kind": "pull_request", "state": pull.get("state", "")}
                ).record(observed))
                result.edges.append(Edge(
                    pr_id, stable_id("github:issue", str(int(issue_number))),
                    EdgeType.IMPLEMENTS, {},
                    evidence=[f"PR #{pull['number']}"]).record())
        result.metrics.update({"NODES_ADDED": len(result.nodes),
                               "EDGES_ADDED": len(result.edges)})
        return result
