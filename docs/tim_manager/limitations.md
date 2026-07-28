# Known Limitations

- TIM is untracked inside a Git repository rooted at the user home directory.
- The Git adapter therefore cannot provide TIM-specific commit provenance.
- The parent repository commit is context only. Current TIM-IM outputs use
  `repository_status=unversioned`, `repository_commit=null`,
  `authoritative_git_repository=false` and a reproducible
  `content_manifest_hash`.
- GitHub is disabled and no cloud metadata is scanned.
- MCP is a small stdio JSON-RPC implementation without an external SDK.
- MCP exposes no mutation tools, but `tim_search` does not open the isolated
  TIM-IM SQLite index in explicit SQLite read-only mode.
- Semantic embeddings and LLM summarization are intentionally not enabled.
- Contradiction extraction is intentionally limited to explicit namespaced
  `tim_manager_claims` JSON metadata and controlled status/Boolean rules.
  Arbitrary prose is not interpreted as a claim, and unsupported predicates
  remain unclassified instead of being guessed.
- Module verification proves configured evidence presence, not successful test
  execution; executable test outcomes remain a separate validation result.
- No global project-completion percentage is produced.
