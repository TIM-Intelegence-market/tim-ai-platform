# Isolierter Reparatur-Ablauf (#17, #18, #20)

`src/repair_workflow/pipeline.py::run_patch_pipeline` verbindet die einzeln gelieferten Bausteine in der
Reihenfolge, die #20 verlangt, und hält vor jedem Merge an:

1. **Reproduktion** (#17): `replay_twice` in zwei getrennten, danach gelöschten Arbeitsordnern. Nur zweimal
   `REPRODUCED` geht weiter; `INSUFFICIENT_EVIDENCE` nur mit dokumentiertem Waiver. Vorher wird kein Patch angesehen.
2. **Patch-Prüfung** (#20): `check_diff` gegen erlaubte Pfade und Größengrenzen.
3. **Gate-Engine** (#18): `determinism`, `lookahead_safety`, `db_integrity`, `queue_integrity` und
   `targeted_tests` gehen gemeinsam durch `decide`. Fehlende Evidenz ist nie PASS. Ein kritisches Gate, das
   fehlschlägt, endet als `SAFE_STOP` mit Eskalation.
4. **Kandidat und Review-Artefakt** (#20): `candidate_status` und `build_review_artifact`; die Verknüpfung
   Incident → Task → Reproduktion → Patch-Prüfsumme → Artefakt-Prüfsumme ist deterministisch.

Das Ergebnis ist immer `fixed: False`, `auto_merge: False`. Der Ablauf wendet keinen Patch an, nutzt kein git,
mergt und deployt nicht. Ungültige Eingaben enden als `BLOCKED`, ohne Ausnahme.

Tests: `tests/test_repair_workflow_pipeline.py` (18 Fälle: voller Lauf, keine Reproduktion, flackernde
Reproduktion, Waiver, rote Tests, jede kritische Integritätsverletzung, Pfadverstoß, fehlende Evidenz).

Nicht abgedeckt und weiter offen: echte Reparaturfälle aus dem Betrieb (#19) und Observe-Betrieb mit
Rollback-Drill (#21).
