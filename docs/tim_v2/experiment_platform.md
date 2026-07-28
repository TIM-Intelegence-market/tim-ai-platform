# TIM V2 Experiment Platform

Status: architecture contract. No experiment is executed by this platform in
V2.0.

An `Experiment` is a reproducible test of one registered hypothesis. It holds
an immutable ID and version, hypothesis reference, dataset manifest, parameter
set, code version, environment/configuration identity, execution plan, result
reference, statistical findings, artifact manifest, reproducibility record and
status.

| Status | Meaning | Permitted transition |
|---|---|---|
| planned | hypothesis and method registered | review or cancel |
| approved | required inputs and safeguards accepted | future run only |
| completed | result manifest recorded | review |
| inconclusive | result exists without supported conclusion | review or supersede |
| invalid | provenance, temporal or integrity gate failed | preserve and close |
| superseded | successor experiment exists | terminal |

Runs are append-only. A rerun creates a new run/result identity that references
the original plan; it cannot replace a result, statistic, artifact or scientific
conclusion. The platform has no access to execution adapters.
