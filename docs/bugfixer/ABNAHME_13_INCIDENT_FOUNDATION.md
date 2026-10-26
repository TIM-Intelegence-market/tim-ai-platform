# Abnahme #13 Incident Foundation (M09/P2)

Stand 25.10.2026, `platform-main` plus diesem PR. Code: `src/bugfixer/` (Store, Verarbeitung, Tasks) und
`src/collection_reporting/errors.py` (Klassen). Nicht Teil von #13: Log-Tailing (#14), Reparatur, Diagnose (#15).

| Anforderung (Scope / Task Card) | Umsetzung | Test |
|---|---|---|
| P2.1 Incident- und Occurrence-Schema, Lebenszyklus | `model.py` (`SCHEMA_VERSION`, Übergänge nur mit Evidenz), Tabellen `incidents`, `history` in `store.py` | `test_foundation.py::test_cannot_skip_evidence_lifecycle`, `test_lifecycle_requires_evidence` |
| P2.2 Evidenz-Referenzen | `evidence_bundles` (sha256 je Incident), `inspect()['evidence_references']` | `test_evidence.py` |
| P2.3 Secret-Redaction vor Persistenz | `processing.redact_text`, Event wird vor dem Schreiben bereinigt | `test_foundation.py::test_secret_redaction`, `test_incident_foundation_exit_13.py::test_evidence_kept_with_the_incident_is_the_sanitized_event` |
| P2.4 Stabiler, versionierter Fingerprint | `processing.fingerprint`, `FINGERPRINT_VERSION` | `test_fingerprint_stable_but_preserves_semantic_codes`, `test_similar_software_faults_keep_distinct_fingerprints…` |
| P2.5 Deduplizierung und Wiederholungszähler | `store.record`: gleicher Fingerprint zählt `occurrence_count`/`suppressed_count` hoch; Wiederauftreten nach RESOLVED öffnet neu | `test_storm_has_one_incident_and_bounded_history`, `test_recurrence_reopens_resolved_incident`, `test_one_failure_is_one_persisted_incident_with_one_task_across_restart` |
| P2.6 Klassifikation inkl. UNKNOWN | 12 Klassen aus #9 in `ErrorClass`; unbekannt → `UNKNOWN` → `SAFE_STOP`, nie geraten | `test_every_required_incident_category_has_a_deterministic_result`, `test_every_required_incident_class_exists`, `test_unknown_is_never_guessed_and_its_task_is_stopped`, `test_classification_is_deterministic_across_stores` |
| P2.7 Incident → Task | `task_store._ensure_incident_task` legt im selben Schreibvorgang genau einen Task je Incident an; RESOLVED nur mit verifiziertem FIXED-Task | `test_task_reconciliation.py`, `test_plain_text_cannot_resolve_incident`, `test_different_failures_stay_separate_incidents_with_separate_tasks` |
| P2.8 Neustart und Persistenz | SQLite mit `synchronous=FULL`, Schreiben nur in Transaktion, Migration v1 → v2 idempotent | `test_one_failure_is_one_persisted_incident_with_one_task_across_restart`, `test_v1_migration_preserves_incidents_cursor_and_is_idempotent`, `test_recording_outside_a_transaction_is_refused` |

**Exit Gate:** Ein bereinigter, normalisierter Fehler erzeugt deterministisch genau einen persistierten Incident,
Wiederholungen werden gezählt statt vervielfacht, die Klasse ist deterministisch oder `UNKNOWN`, und der Incident
ist auch nach einem Neustart mit genau einem Task verknüpft. Erfüllt laut obigen Tests.

**Nicht belegt und nicht Teil von #13:** Laufzeitbetrieb auf dem Server (#14, #21).

Prüfbefehl: `python -m pytest tests/bugfixer -q`
