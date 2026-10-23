# Setup-Grade und Evidenzstatus (Plan-Journal)

Stand: 2026-10-23. Gehört zu `src/orderflow_scenario/engines/trade_plan.py` (`grade_scenario`,
`GRADE_RULESET_VERSION`), `src/research_lab/setup_evidence.py` und `src/dashboard/plan_journal.py`.
Abnahmebezug: Abnahmevertrag des Master-Auftrags, Abschnitt 1 (Empfehlung nur bei belegter Eignung).

Drei Dinge werden getrennt gespeichert und dürfen nicht vermischt werden:

| Feld | Bedeutung | Quelle | Ändert sich nach dem Festhalten? |
|---|---|---|---|
| `setup_grade` + `grade_reasons` + `grade_ruleset_version` + `graded_state` | Heuristische Regelqualität des Szenarios in seinem tatsächlichen Zustand | `grade_scenario()` | nein |
| `evidence_status` + `evidence_ref` | Empirische Evidenz der Setup-Familie laut Hypothesenregister | `setup_evidence.evidence_status()` | nein |
| `execution_status`, `journal_decision`, `journal_decision_reasons`, `pipeline_decision` | Darf gehandelt werden (Papier) und warum nicht | `plan_journal.journal_gate()` | nein |
| `status`, `gross_r`, `tp_hits`, `exit_reason` | Hypothetischer Verlauf nach TIMs Regeln | `plan_journal.evaluate()` | ja, bis CLOSED |

## Grade `grade/1.0.0`

Punkte: Szenario `CONFIRMED` +2; Szenario-Score ≥ 0,45 +1; Reward/Risk (Ziel 1) ≥ 2,0 +1; keine
Gegenbelege +1. A ab 4 Punkten, B bei 3, sonst C. `A+` wird nie vergeben: es gibt keine definierte und
geprüfte Regel dafür. Die Note sagt nichts über einen empirischen Vorteil.

Gegenbeispiele (alle in `tests/test_setup_grade.py`):

- Dasselbe Szenario im Zustand `WATCHING` erhält B, mit erzwungenem `CONFIRMED` A. Die Chart-Vorschau
  (`chart_model.run_scenarios`) baut Pläne mit erzwungener Bestätigung; deshalb benotet das Journal
  den Originalzustand, nie `plan.grade` der Vorschau.
- Ein bestätigtes Szenario mit Score und Reward/Risk erreicht A **trotz** Gegenbelegen (4 von 5 Punkten).
  Das ist die Regel 1.0.0, wie sie vor dieser Dokumentation im Code stand; der Grund
  `conflicting_evidence_present` wird mitgespeichert. Ob Gegenbelege A ausschließen sollen, ist eine
  Regeländerung und braucht eine neue Version, keinen stillen Patch.
- Über alle Kombinationen aus Zustand, Score, Reward/Risk und Gegenbelegen fällt nie `A+`.

Eine Änderung der Punkte, Schwellen oder Notengrenzen erhöht `GRADE_RULESET_VERSION`. Alte
Journal-Einträge behalten ihre Version.

## Evidenzstatus `setup-evidence-mapping/0`

| Status | Bedingung |
|---|---|
| `INSUFFICIENT_EVIDENCE` | keine Regel-Äquivalenz für (ScenarioType, Timeframe), Register fehlt oder ist unlesbar, oder registrierte Varianten ohne finales positives Urteil |
| `NEGATIVE_EVIDENCE` | mindestens eine äquivalente Variante `failed_train`, `failed_validation` oder `failed_holdout` |
| `CANDIDATE_FROZEN` | alle äquivalenten Varianten `candidate` (Holdout offen) |
| `PASSED_HOLDOUT` | alle äquivalenten Varianten `passed_holdout`; keine Ausführungsfreigabe impliziert |

Die Äquivalenztabelle `RULE_EQUIVALENCES` ist leer. Grund: Die Pipeline-Szenarien
(`BREAKOUT_ACCEPTANCE`, `REJECTION_FAILED_BREAKOUT`, …) entstehen aus anderen Regeln als die
registrierten Strategien T1–T3 (`BOSDetector`, `BroncxRules`). Namensähnlichkeit ist keine Äquivalenz;
`entry_model` erzeugt nie eine Zuordnung. Jede Zuordnung wird als Codeänderung mit Test und
neuer `EVIDENCE_MAPPING_VERSION` eingetragen. Jeder Status trägt `register_head_hash`,
`register_events`, `mapping_version` und `protocol_version`. Eine gebrochene Hash-Kette des Registers
ergibt kein Urteil; das Journal hält dann `INSUFFICIENT_EVIDENCE` mit Grund `REGISTER_UNREADABLE` fest.

Stand des Registers am 2026-10-23 (`docs/research_lab/REGISTER.jsonl`): 48 Varianten, 42 `failed_train`,
6 `failed_validation`, keine Kandidaten, kein Holdout-Lauf. Es gibt kein Setup mit positiver Evidenz.

## Entscheidung

`journal_gate()` liefert `PAPER_TRADE` nur, wenn Evidenz `PASSED_HOLDOUT`, Ausführung `PAPER_APPROVED`,
Pipeline `TRADE_PLAN` und Szenario `CONFIRMED` sind; sonst `NO_TRADE` mit allen fehlenden Gründen.
Kein Code setzt `PAPER_APPROVED`; das wäre ein eigener menschlicher Freigabeschritt. Die Entscheidung
der Pipeline bleibt als `pipeline_decision` erhalten.

## Grenzen

Ergebnisse sind Brutto-R ohne Gebühren und Slippage (`gross_r`). Das Journal ist noch ein
veränderliches Dokument, kein append-only Ereignisprotokoll; Replay und Netto-R folgen in einem
eigenen Paket. Nichts hier ist eine Handels- oder Anlageempfehlung.
