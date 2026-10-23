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
| `status`, `gross_r`, `fee_r`, `slippage_r`, `net_r`, `tp_hits`, `exit_reason` | Hypothetischer Verlauf nach TIMs Regeln und Kosten nach Protokoll 1.1 | `plan_journal.evaluate()` | ja, bis CLOSED |

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

## Speicherung und Replay

Die einzige Wahrheit ist das append-only, hash-verkettete Ereignislog
`data/journal/tim_plan_journal.events.jsonl` (`src/dashboard/journal_log.py`). Ereignisse:
`PLAN_RECORDED` (vollständiger Eintrag bei Aufnahme), `PLAN_UPDATED` (geänderte Felder mit Hash der
verwendeten Kerzen), `CANDLE_CLOSE_PROCESSED` (verarbeiteter 15m-Schluss mit Hash der 80 sichtbaren
Kerzen) und `CANDLE_REVISION_OBSERVED` (gleicher 15m-Schluss, anderer Kerzeninhalt; Entscheidungen
bleiben). `fold()` baut die Sicht `tim_plan_journal.json`; `rebuild()` schreibt sie neu. Regeln, die
`fold()` erzwingt: kein Ereignis darf ein Entscheidungsfeld ändern, kein Ereignis nach einem Endzustand,
kein Plan doppelt. Ein Neustart mit denselben Kerzen erzeugt keine Ereignisse. Eine gebrochene Kette
(editiert, gelöscht, umsortiert) sperrt Journal und Seite; nur eine abgeschnittene letzte Zeile nach
einem Absturz wird verworfen und vermerkt. Tests: `tests/test_journal_log.py`,
`tests/test_plan_journal.py` (Replay == Sicht, Neustart ohne Duplikate, Sichtverlust, Revision).

## Kosten (Netto-R)

`gross_r` ist das R-Vielfache vor Kosten. `fee_r` und `slippage_r` folgen Protokoll 1.1 §4.3/§4.4
(`cost_model_version = protocol/1.1`): Gebühr 0,05 % und Slippage 0,03 % je Seite auf den Einstieg (volle
Menge), auf jedes Drittel an seinem Ziel und auf den Rest beim Schlusskurs; 0,05 % Slippage, wenn der
Schluss eine Stop-Ausführung war (STOP, BREAK_EVEN). Kosten in R = Kosten in Preis / Stopabstand, deshalb
treffen enge Stops härter. `net_r = gross_r − fee_r − slippage_r`. Funding wird nicht gebucht (Spot-Kerzen,
keine Perpetual-Position). Nicht gefüllte Pläne tragen keine Kosten. Die Konfigurationswerte des
Orderflow-Moduls (6/2/2 bp) werden bewusst nicht verwendet, damit Netto-R mit dem Register vergleichbar bleibt.

## Ausführbarkeit (Abnahme §2, Teil 1)

`INSTRUMENT_SPECS` (`instrument/1`) kennt BINANCE/SPOT/BTCUSDT mit Tick 0,01 und Losschritt 0,00001;
`short_executable=false`, weil das Journal keine Leihe oder Margin modelliert. `executability()` liefert
Gate-Gründe `instrument_unknown`, `short_not_executable_on_spot`, `data_quality_<status>` (alles außer PASS
sperrt); sie werden Teil von `journal_decision_reasons`, der Eintrag trägt `instrument`. Der Fill-Preis wird
gegen den Plan auf den Tick gerundet (Kauf-Limit aufwärts, Verkaufs-Limit abwärts). Sind die 15m-Kerzen beim
Update älter als 30 Minuten (`STALE_AFTER`), werden keine neuen Pläne aufgenommen; das wird einmal je Schluss
als `CANDLE_CLOSE_SKIPPED` festgehalten.

## Grenzen

Keine Teilfüllungen, keine Mengenrundung der Position (nur Preis-Tick), kein Funding, kein Simulator mit
Kontozustand, Tages-/Positionsrisiko oder Kill-Switch (ohne Ausführungspfad gibt es nichts zu begrenzen). Die Fälle
überlappen zeitlich (alle 15 Minuten aus 80-Kerzen-Fenstern) und sind keine unabhängigen Studienfälle.
Nichts hier ist eine Handels- oder Anlageempfehlung.
