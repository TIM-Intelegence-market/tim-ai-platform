# TIM V2 Observability

Status: design only; V2.0 adds no telemetry service.

Every future component emits structured, redacted logs, metrics, traces and
domain/audit events with UTC time, correlation/run/artifact IDs, schema version
and severity. Health states are `healthy`, `degraded`, `blocked` and `unknown`;
missing telemetry is `unknown`, never proof of health.

| Signal | Purpose | Retention / integrity rule |
|---|---|---|
| Metrics | capacity, latency, error and freshness indicators | aggregated; no secrets |
| Traces | causal request/task paths | correlation IDs; sampled policy disclosed |
| Logs | diagnosis | structured/redacted; rotation and access policy |
| Events | domain state changes | append-only references where required |
| Audit trail | authority and sensitive action evidence | tamper-evident retention |
| Heartbeat | liveness and dependency freshness | timeout causes degraded/blocked state |
| Alerts | human action on defined thresholds | never auto-authorize promotion |

Observability is operational evidence, not scientific evidence, unless a
separate validated evidence record explicitly refers to it.
