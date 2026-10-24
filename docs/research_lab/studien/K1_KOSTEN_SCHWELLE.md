# Studie K1: Kosten-Schwelle für Plan-Journal-Pläne

Stand 25.10.2026. Festgelegt, bevor echte Journal-Daten gelesen wurden. Code: `src/research_lab/studies/cost_threshold.py`,
Tests: `tests/test_cost_threshold_study.py`, Validierung der Anzeige: `tests/test_plan_cost_check_rules.py`.

## Frage

Ist 0,25 R eine sinnvolle Forschungsgrenze für die geschätzten Roundtrip-Kosten eines Plans (`plan_cost_check.COST_LIMIT_R`,
PR #408), verglichen mit anderen Grenzen? Die Anzeige bleibt davon unberührt. Die Studie ist beschreibend und erzeugt
weder einen Filter noch eine Order- oder Risikoregel.

## Festlegungen

- **Varianten:** 0,10, 0,15, 0,20, 0,25, 0,33 und 0,50 R sowie „ohne Grenze“. Die Liste steht fest. Keine Grenze wird
  aus den Daten gewählt.
- **Kostenmodell:** Research-Protokoll 1.1, Abschnitt 4.4, als `protocol.BASE_COSTS` (Gebühr 0,05 % je Seite,
  Slippage 0,03 % je Seite, Stop-Slippage 0,05 %). Dazu der Stressfall `protocol.STRESS_COSTS` mit doppelten Sätzen.
  Plan-Journal, Anzeige und Studie nutzen dieselben Werte; ein Test prüft das.
- **Schätzung:** der Stop-Fall von Einstieg bis Stop, genau wie die Anzeige rechnet. Die Schätzung steht fest, sobald ein
  Plan aufgezeichnet ist. Ein Filter darauf nutzt also keine Information aus der Zukunft.
- **Ergebnis:** das gebuchte Ergebnis geschlossener Journal-Einträge (`gross_r`, `fee_r`, `slippage_r`, `net_r`).
  Im Stressfall werden die gebuchten Kosten verdoppelt. Das ist exakt, weil der Stressfall jeden Satz verdoppelt und die
  gebuchten Kosten linear in den Sätzen sind.
- **Zählung:** clusterbewusst wie `journal_review`. Pläne derselben Familie und Richtung innerhalb eines Chartfensters
  zählen als ein Cluster. Mindestens 30 Cluster sind nötig, sonst lautet der Status `INSUFFICIENT_CASES`. Für den
  Mittelwert des Netto-R gibt es ein Cluster-Block-Bootstrap mit festem Seed 20261025.
- **Daten:** die Journal-Ansichten der drei Regeln tim/1, struct/1 und level/1 vom Mac, nur lesend. Holdout-Daten des
  Research Lab werden nicht berührt.

## Was als Ergebnis zählt

- Für jede Grenze: behaltene Pläne und deren Anteil, behaltene geschlossene Fälle und Cluster, Netto-Mittel und
  Netto-Summe in R, Trefferquote, jeweils mit Basis- und Stresskosten.
- Der Mindest-Stopabstand je Grenze wird aus den Formeln berechnet, ohne Marktdaten.
- Ein Urteil über eine Grenze ist erst bei `DESCRIBED` möglich. Auch dann ist eine Grenze höchstens ein Kandidat für eine
  registrierte Hypothese mit eigenem Training, eigener Validierung und eigenem Holdout. Erst danach wäre ein Filter
  denkbar, und nur mit Uzis Freigabe.

## Grenzen

- Das Plan-Journal läuft erst seit dem 23.10.2026. Die Zahl der geschlossenen Fälle ist sehr klein.
- Die Schätzung deckt nur den Stop-Fall ab. Bei Ausstiegen an Zielen sind die Kosten in R anders.
- Funding wird im Plan-Journal nicht gebucht.
