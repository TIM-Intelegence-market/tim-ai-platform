# Source Adapters

- Filesystem: read-only discovery, metadata, bounded text parsing and SHA-256.
- Git: read-only repository metadata. TIM is currently untracked inside the
  user-wide repository, so Git evidence is limited.
- Structured artifacts: JSON and JSONL validation is isolated per artifact.
- GitHub: configured as disabled and is not contacted.
- Local databases: no scientific database is opened or migrated by TIM-IM v1.

Every scanned document is untrusted data. Its contents cannot trigger tools.
