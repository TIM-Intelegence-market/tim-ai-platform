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
Schluss eine Stop-Ausführung war (STOP, BREAK_EVEN, BREAK_EVEN_COSTS, COST_STOP). Kosten in R = Kosten in Preis / Stopabstand, deshalb
treffen enge Stops härter. `net_r = gross_r − fee_r − slippage_r`. Funding wird nicht gebucht (Spot-Kerzen,
keine Perpetual-Position). Nicht gefüllte Pläne tragen keine Kosten. Die Konfigurationswerte des
Orderflow-Moduls (6/2/2 bp) werden bewusst nicht verwendet, damit Netto-R mit dem Register vergleichbar bleibt.

## Stop auf Break-even plus Kosten (`be_cost/1`)

Regel von Uzi (25.10.2026), gilt für jeden Plan, der ab dann ins Journal kommt (`stop_rule = be_cost/1`);
ältere Einträge ohne `stop_rule` behalten die alte Regel (Stop nach TP1 auf den Einstieg). Der neue Stop ist
der Preis, bei dem der Rest der Position nach Protokoll-1.1-Kosten genau 0 R bringt
(`cost_stop_level`: LONG `Fill · (1 + 0,05 % + 0,03 %) / (1 − 0,05 % − 0,05 %)`, SHORT gespiegelt, auf den
Tick weg vom Einstieg gerundet; bei BTC ≈ 0,18 % über dem Einstieg).

- Nach TP1 zieht der Stop auf diesen Preis (Ausstieg `BREAK_EVEN_COSTS`). Liegt er wegen eines sehr engen
  Stops jenseits von TP1, bleibt es beim Einstieg (`BREAK_EVEN`).
- Vor TP1 beurteilt TIM den laufenden Trade selbst, an jedem 30m-Schluss aus seinem Chartmodell
  (`judge_trades`, `verdict/1`, kein fester Timer). Voraussetzung: der 30m-Schluss liegt mindestens
  `COST_STOP_MIN_GAP_R` = 0,1 R jenseits des Kostenpreises, sonst HALTEN (`price_not_beyond_cost_level`).
  Dann SICHERN, wenn die Struktur seit dem Einstieg die Richtung bestätigt hat (BOS/MSS in Trade-Richtung,
  `structure_confirms_*`) oder die These schwächer wird (Strukturbruch dagegen `structure_against_*`,
  Marktzustand dagegen `market_state_against`, bestätigtes Gegen-Szenario `opposite_scenario_*`) oder das
  Sicherheitsnetz greift (`FALLBACK_HOURS` = 4 h im Trade oder `FALLBACK_MFE_R` = 0,75 R gesehen, Uzis Wahl
  „Zeit oder R, was zuerst“); sonst HALTEN (`thesis_intact`). Urteil, Gründe und Zeitpunkt stehen am Eintrag (`tim_verdict`,
  `tim_verdict_reasons`, `tim_verdict_at`); SICHERN setzt `cost_stop`/`cost_stop_at`, gültig ab der nächsten
  1m-Kerze, Ausstieg `COST_STOP`. Das Urteil wird je 30m-Schluss erneuert, bis der Stop gezogen ist.
- Sobald der Stop geschützt ist (nach TP1 oder nach SICHERN), zieht TIM ihn wie ein Orderflow-Trader
  hinter die letzte bestätigte 30m-Swing-Marke seit dem Einstieg nach (`swing_stop`: Swing-Tief für Long,
  Swing-Hoch für Short, Pivotbreite wie `chart_model.PIVOT_WINDOW`), nur weiter in den Gewinn, und nur wenn
  der 30m-Schluss mindestens 0,1 R jenseits der Marke liegt (`cost_stop_kind = SWING`, Ausstieg
  `TRAIL_STOP`). Ein Stop wandert nie zurück.

Nur Papier; die Regel ändert keine Entscheidungsfelder und keine Kostensätze.

## Ausführbarkeit (Abnahme §2, Teil 1)

`INSTRUMENT_SPECS` (`instrument/1`) kennt BINANCE/SPOT/BTCUSDT mit Tick 0,01 und Losschritt 0,00001;
`short_executable=false`, weil das Journal keine Leihe oder Margin modelliert. `executability()` liefert
Gate-Gründe `instrument_unknown`, `short_not_executable_on_spot`, `data_quality_<status>` (alles außer PASS
sperrt); sie werden Teil von `journal_decision_reasons`, der Eintrag trägt `instrument`. Der Fill-Preis wird
gegen den Plan auf den Tick gerundet (Kauf-Limit aufwärts, Verkaufs-Limit abwärts). Sind die 15m-Kerzen beim
Update älter als 30 Minuten (`STALE_AFTER`), werden keine neuen Pläne aufgenommen; das wird einmal je Schluss
als `CANDLE_CLOSE_SKIPPED` festgehalten.

## Lernvorschläge (Abnahme §4, Teil 1)

`src/research_lab/journal_review.py` (`journal-review/1`) liest geschlossene Journal-Fälle und ändert nichts:
weder Journal noch Grade-Regeln, Äquivalenztabelle oder Kostenmodell (`champion.changed_by_this_proposal=false`).
Fälle derselben Familie (ScenarioType, Richtung) innerhalb eines Chart-Fensters (80 × 15 min) bilden einen
Cluster; gezählt werden Cluster, nicht Einträge. Je Familie und Grade: Fälle, Cluster, Brutto-/Netto-Mittel,
Kostenanteil, Trefferquote, Ausstiegsgründe, Datenlücken und ein Cluster-Block-Bootstrap (95 %, Seed fest) des
Netto-Mittels. Urteil: `INSUFFICIENT_CASES` unter 30 Clustern, `CANDIDATE_FOR_REGISTRATION`, wenn die untere
Intervallgrenze über 0 liegt, sonst `NO_POSITIVE_EDGE_FOUND`. Ein Kandidat ist kein neuer Grade und keine
Freigabe: der einzige vorgesehene nächste Schritt ist eine registrierte Hypothese im Research-Lab-Register mit
eigenem Train/Validation/Holdout. Vorschläge sind deterministisch (`proposal_id` aus dem Inhalt) und werden als
eigene Dateien geschrieben (`write_proposal`), nie überschrieben. Keine Schwelle wird aus dem Journal gelernt.
Ein Übernahme-/Rollback-Pfad existiert bewusst noch nicht (M4 Teil 2, erst mit menschlicher Freigabe).

## Grenzen

Keine Teilfüllungen, keine Mengenrundung der Position (nur Preis-Tick), kein Funding, kein Simulator mit
Kontozustand, Tages-/Positionsrisiko oder Kill-Switch (ohne Ausführungspfad gibt es nichts zu begrenzen). Die Fälle
überlappen zeitlich (alle 15 Minuten aus 80-Kerzen-Fenstern) und sind keine unabhängigen Studienfälle.
Nichts hier ist eine Handels- oder Anlageempfehlung.
