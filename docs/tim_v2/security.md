# TIM V2 Security Architecture

Security is a cross-cutting default-deny control plane. No secret, live
credential, broker connection or execution capability is introduced in V2.0.

| Control | Design requirement |
|---|---|
| Least privilege | separate identities for read, management, research and future execution; grants are task-scoped |
| Read-only paths | TIM-IM V1, MCP and status UI default to read-only; mutations require a separate authenticated surface |
| Secrets | external secret manager/injection; never Git, snapshots, prompts, logs or model context by default |
| Identity | authenticated human/service identity, authorization policy and revocable credentials |
| Integrity | content/schema/config hashes, signed release artifacts and verified manifests |
| Audit | append-only authorization and sensitive-operation records with access review |
| Supply chain | dependency lock/SBOM, provenance review, vulnerability policy and reproducible builds |
| Sandboxing | untrusted parsers/models/agents isolated with constrained filesystem, network, CPU and time |

Trust transitions validate typed input, provenance, authorization and policy.
Security or risk dependency failure blocks a privileged path. Incident response
preserves artifacts, isolates the affected scope, rotates relevant credentials
and requires a verified recovery decision before resumption.
