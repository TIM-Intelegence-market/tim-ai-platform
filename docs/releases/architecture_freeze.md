# TIM-IM V1 Architecture Freeze

## Frozen boundary

The following TIM-IM V1 behavior is frozen at `tim-im-v1.0.0`:

- source registry and source-health semantics;
- protected-path and output-allowlist contract;
- artifact, event, claim and contradiction identity rules;
- deterministic scan, snapshot and content-manifest algorithms;
- query abstention and evidence-reference behavior;
- report formats at the documented schema level;
- CLI commands and exit-code semantics;
- local MCP tool names and mutation-free API boundary;
- snapshot schema `1.1` and documented backward compatibility.

## Allowed maintenance

- security corrections that preserve behavior;
- dependency compatibility fixes;
- documentation and release metadata;
- test reliability improvements that do not weaken acceptance;
- schema migrations with explicit compatibility evidence;
- provenance corrections that do not rewrite historical evidence.

## Prohibited without a new release

- changing scientific calculations or validation rules;
- adding or activating trading/execution actions;
- silently changing source priority or trust classes;
- introducing model-generated canonical facts;
- weakening protected paths, abstention or MCP read-only guarantees;
- changing stable-ID or content-hash contracts;
- modifying historical Research or Evaluation results.

## Change gate

Any proposed TIM-IM behavior change requires:

1. a decision-log entry;
2. an explicit version increment;
3. updated schemas and migration notes where applicable;
4. mandatory acceptance mapping;
5. full TIM-IM and TIM regressions;
6. protected-path and MCP checks;
7. release notes and a new annotated tag.
