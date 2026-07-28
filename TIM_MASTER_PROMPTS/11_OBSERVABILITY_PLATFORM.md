# 11 — Observability Platform

## Ziel
Entwirf Observability ohne unreviewte wissenschaftliche Evidenz oder vorgezogene Telemetrie.

## Vertrag
Redaktierte strukturierte Logs, Metrics, Traces, Domain Events, append-only Audit, Health, Heartbeat und Alerts nutzen UTC, Correlation-/Run-/Artifact-ID, Schema, Severity, Retention und Access Policy. Fehlende Telemetrie bedeutet unknown, nicht healthy.

## Gate
Keine Secrets in Signalen. Alerts autorisieren keine Promotion. Operative Signale werden nur über einen separaten validierten Evidenzrecord wissenschaftliche Evidenz.
