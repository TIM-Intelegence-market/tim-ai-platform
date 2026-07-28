# TIM Health Center Architecture

Version: 1.0

Zweck: Read-only Diagnoseoberfläche für Betrieb, wissenschaftliche Integrität und Governance.

## Designprinzipien

- Keine Kernlogik verändern
- Keine Trading-Funktionen
- Keine neue Prognose- oder Signal-Logik
- Diagnosekarten zeigen persistierte Evidenz statt abgeleiteter Vermutungen

## Bereiche

### Operational Health

Zeigt Persistenz, Stream, Dashboard, Runtime und Aufnahmepfad.

### Scientific Health

Zeigt Coverage, Replay, Determinismus, Provenance, Hash-Integrität, Research Integrity und Acceptance.

### Governance Health

Zeigt OBSERVE-only, Core Freeze, offene Blocker, Readiness, Audit-Status und Review-Status.

## Diagnosekarten

Jede Karte enthält:

- component_id
- display_name
- domain
- status
- severity
- short_summary
- reason_code
- reason_text
- observed_since_utc
- last_checked_utc
- evidence_count
- affected_artifact_count
- linked_report
- linked_blocker
- recommended_next_action
- operational_impact
- scientific_impact
- governance_impact
- freshness_seconds
- provenance
- source_hash

Karten sind read-only und öffnen Details per `details`-Element.

## Timeline

Die Timeline dokumentiert Runtime-, Validator-, Research- und Acceptance-Ereignisse mit:

- event_id
- event_type
- timestamp_utc
- component_id
- previous_status
- new_status
- reason_code
- evidence_reference
- provenance
- source_hash

## Known Limitations

- Nur persistierte Zustände, keine Rekonstruktion
- Red-/Yellow/Green-Bewertung folgt dokumentierten Artefakten
- Historische Lücken bleiben dokumentiert statt kaschiert
