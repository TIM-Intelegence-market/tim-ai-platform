# Graphify Backend Capability Matrix

Date: 2026-07-29

Host: Apple Silicon, 16 GiB unified memory

Ollama: 0.32.0, local loopback API

No model was downloaded and no paid or external API was used.

| Candidate | Local digest | Parameters / quantization | Declared context | Structured output | JSON Schema | Timeout evidence | Storage / practical memory | Execution | License | Decision |
|---|---|---|---:|---|---|---|---|---|---|---|
| `qwen2.5:7b` | `845dbda0ea48` | 7.6B / Q4_K_M | 32,768 | Ollama `format` | Yes, enforced by direct Ollama API | Raw Graphify previously emitted invalid JSON; controlled canary has mixed success and 180s timeouts | 4.7 GB model; observed fully on GPU, about 5.2 GB loaded with 16k context | Local | Apache 2.0 | **Approved and evaluated; NO-GO** |
| `llama3.2:latest` | `a80c4f17acd5` | 3.2B / Q4_K_M | 131,072 | Ollama `format` | Transport supports schema | Previous one-document Graphify test timed out at 180s | 2.0 GB model; lowest storage requirement | Local | Llama 3.2 Community License | Not approved for repeated evaluation because prior timeout already misses completion gate |
| `deepseek-r1:8b` | `6995872bfe4c` | 8.2B / Q4_K_M | 131,072 declared; 32,768 original | Ollama `format`; thinking-capable | Transport supports schema; thinking separation adds evaluation complexity | Not evaluated in this gate | 5.2 GB model before context; high pressure on 16 GiB host | Local | MIT | Not approved: slower/larger thinking model offers no justified reliability advantage for constrained extraction |
| `llava:7b` | `8dd30f6b0cb1` | 7B / Q4_0 | 32,768 | Ollama `format` | Transport supports schema | Not evaluated | 4.7 GB model plus unused vision stack | Local | Apache 2.0 | Not approved: vision model is not appropriate for the Markdown-only gate |

## Backend distinction

Ollama supports schema-constrained structured outputs when a JSON Schema is
provided in the `format` field. The prior Graphify 0.9.29 Ollama path did not
apply that constraint, so this recovery uses a separate deterministic
acceptance harness. This harness does not repair model responses and does not
modify Graphify or TIM.

The Graphify Claude CLI backend can use a native `--json-schema` capability,
but Claude CLI is not installed and would transmit repository documents to an
external model provider. It was not approved or attempted.

## Privacy and licensing

All evaluated inference remained on `127.0.0.1`. The canary files did not leave
the host. Model licenses were read from the locally installed Ollama manifests;
this matrix is an engineering inventory, not legal advice.

## Recommended next candidates

Any next candidate requires separate approval. Recommended options are:

1. a newer Graphify release that applies Ollama's schema constraint directly;
2. a stronger local instruction model with verified constrained-decoding
   behavior and sufficient throughput;
3. Claude CLI structured output or a hosted structured-output API only after
   explicit data-transfer, cost, retention, and provider approval.

For a materially larger local model, 32 GiB unified memory is a practical
minimum planning assumption and 64 GiB provides safer headroom for model,
16k–32k context, and graph tooling. This is an estimate, not a measured TIM
requirement.
