# Orderflow-Begriffe und Schwellen in TIM: eine Definition je Begriff

Stand: 2026-11-09 (Master-Analyse aus Kundensicht, Punkt P8). Dieses Blatt ist das Glossar
zu `ORDERFLOW_REGELN.md`: je Begriff **eine** Definition, wo Engine und Chart sie verwenden,
und welche Zahl dahintersteht. Wo Engine und Chart bewusst verschieden rechnen, steht es hier
und nirgends sonst anders. Die Zahlen in Abschnitt 2 werden von
`tests/test_orderflow_begriffe.py` gegen den Code geprüft; eine Änderung im Code ohne
Änderung hier lässt die Suite rot werden.

**Keine der Schwellen ist an BTC gemessen.** Sie stammen aus dem Broncx-Bootcamp, aus ATAS
und aus Lehrtexten. Ob sie für BTC passen, prüft Studie S19
(`../research_lab/studien/S19_ORDERFLOW_SCHWELLEN_BTC_PRAEREGISTRIERUNG_ENTWURF.md`),
registriert vor dem ersten Datenzugriff; bis dahin bleiben sie, wie sie sind.

## 1. Begriffe

| Begriff | Definition in TIM | Engine (`src/orderflow_scenario/`) | Chart (`src/dashboard/`) |
| --- | --- | --- | --- |
| Aggressor | Die Seite, die den Preis bezahlt (Market Order). Binance `is_buyer_maker = true` heißt: der Käufer war passiv, also aggressiver Verkauf (Bid). | `Trade.side`, `footprint_from_trades` | `footprint_data` (Spot-Tabelle `agg_trades`), `perp_flow` (Perp-aggTrades) |
| Delta | Aggressive Käufe minus aggressive Verkäufe, je Kerze oder je Preisstufe, in Coins. | `net_delta` (Fenster), `delta_series` (je Kerze) | Footprint-Zelle, `bar_deltas`, Delta-Zeile unter dem Chart |
| CVD | Laufende Summe des Deltas über die gezeigten Kerzen; Spot und Perp getrennt, nie addiert. | nur Eingabe `delta_divergence` | `cvd.spot`, `cvd.perp` (Band „CVD“) |
| Footprint | Bid- und Ask-Volumen je Preisstufe innerhalb einer Kerze. Stufe = Tick (BTC 5 $). | `FootprintBar.levels` | Zeilen `[bucket, level, bid, ask]` in 5-Minuten-Eimern, zur Kerze zusammengefasst |
| Imbalance | Diagonaler Vergleich: Ask auf Stufe p gegen Bid auf der Stufe darunter (Kauf) bzw. Bid auf p gegen Ask auf der Stufe darüber (Verkauf). Imbalance, wenn die eine Seite mindestens das `IMBALANCE_RATIO`-Fache der anderen ist. | F1: Nachbarstufe genau 1 Tick; fehlt sie, kein Flag | Nachbarzeile in der **angezeigten Zeilenbreite** (zoomabhängig, Vielfaches des Ticks); leere Nachbarzeile zählt als Null; Randzeilen nie markiert. Bewusst anders (Prüfung 06.11.2026) |
| Stacked Imbalance | Mindestens `STACK_MIN` gleichseitige Imbalances auf aufeinanderfolgenden Stufen. | F2 `stacked_buy` / `stacked_sell` | gleiche Zahl, auf Zeilenbreite |
| Finished / Unfinished Auction | Kerzenhoch oder -tief mit Null auf einer Seite = finished; beide Seiten > 0 = unfinished (Magnet). | F3 `finished_high` / `finished_low` | nur Anzeige der Zelle, kein Flag |
| Absorption | Aggressive Marktorders treffen auf passive Limit-Orders, die nachgefüllt werden: Anstrengung ohne Preisfortschritt. Volumen der letzten Kerze mindestens `HEAVY_VOLUME_RATIO`-mal der Mittelwert der bis zu fünf Kerzen davor. | R1/R2 in `orderflow_interpretation.py`; Footprint-Bestätigung F4 `absorption_cluster` (eine Stufe ≥ `CLUSTER_RATIO` × mittleres Stufenvolumen, in den äußeren 20 % der Range) | kein eigenes Flag. `src/analysis/bronxc_rules.py` nennt eine Kerze mit Körper ≤ 25 % der mittleren Spanne und Volumen ≥ 1,5 × Mittel `ABSORPTION_CONTEXT`: Kerzenbild ohne Delta, nicht dieselbe Definition |
| Exhaustion | Der aggressiven Seite gehen die Teilnehmer aus: Volumen der letzten Kerze unter `THIN_VOLUME_RATIO` × Mittel, bei Delta mit Preis zusätzlich Range unter `SHRINKING_RANGE_RATIO` × Mittel. Bestätigt durch Delta-FADING/FLIP (`delta_series`), finished auction am Extrem (F3) oder dünnes Extrem (F5, Randstufe ≤ `THIN_EXTREME_RATIO` × mittleres Stufenvolumen). Widerlegt durch EXPANDING Delta oder Stacked Imbalances der Aggressorseite. | R3/R4; F3/F5 | kein Flag |
| Exhaustion-Kerzenbild (Marktzustand) | **Anderer Begriff, gleicher Name:** `engines/market_state.py` setzt `EXHAUSTION`, wenn der Körper < 15 % der Kerzenspanne ist und die Körper-Volatilität der letzten drei Kerzen ≥ 1,3 × der älteren. Ohne Volumen, Delta oder Docht. Kein Szenario nutzt es; maßgeblich ist die Reaktion der Orderflow-Engine (Zeile darüber). | `market_state.py` | Analyse-Text „Marktzustand“ |
| Volume Bubble | Eine Taker-Order (aggTrades derselben Millisekunde und Seite) mit Gegenwert ≥ `BUBBLE_MIN_USD` (BTC 100 000 $; XMR-Perp 10 000 $). Kreisfläche nach Größe, grün Käufer, rot Verkäufer. | keine Eingabe (`volume_bubbles` nur als Flag) | `footprint_data.volume_bubbles` (Spot), `perp_flow` (Perp); nur die größten im Fenster werden gezeichnet |
| POC / Value Area (Volumen) | Preisstufe mit dem meisten Volumen; Value Area = kleinster Bereich um den POC mit `VALUE_AREA_SHARE` (70 %) des Volumens, wechselseitig nach oben und unten erweitert. **Zwei Quellen:** aus echten Trades (Chart-VP, Perp-Schatten-Journal) oder aus Kerzen geschätzt (Spot-Journale, Level-Pläne, Szenario-Engine ohne Footprint). | `profile.py` (aus Kerzen oder `VOLUME_PROFILE_AGG`) | `footprint_data.profile_from_rows` (Trades), `vp_plans` (Kerzen) |
| TPO / Value Area (Zeit) | Market Profile je UTC-Tag aus 30-Minuten-Perioden (Buchstaben ab 00:00). POC = Stufe mit den meisten Perioden, Value Area = 70 % der Perioden um den POC, zeilenweise erweitert (nicht die CBOT-Zweierschritte). | nicht verwendet | `chart_live.tpo_profiles` |
| Open Interest | Offene Kontrakte des Perp (Binance USD-M, 1h). Z-Score über `OI_WINDOW` Stunden (7,5 Tage, das Fenster von Broncx). Nur eine Börse (Issue #162). | Eingabe `open_interest_trend` RISING/FALLING/FLAT | `perp_flow.open_interest`, Band „OI“ |
| Basis | Spot-Schluss minus Perp-Schluss derselben Kerze in $, Anzeige im Perp-Modus. Pläne rechnen auf Spot, gehandelt wird der Perp. | nicht verwendet | `chart_live` `model["basis"]` |
| Score | Heuristische Konfidenz eines Szenarios: Basis 0,30 plus feste Zuschläge je Beleg (`probability.py`), Typ `UNCALIBRATED_CONFIDENCE`. **Keine Wahrscheinlichkeit.** Die Trefferquote je Score-Bucket steht im Plan-Journal (`summary.score_reliability`, Urteil ab 30 Plänen). | `probability.py` | Spalte „Score (Heuristik)“ |

## 2. Schwellen (vom Test gegen den Code geprüft)

Spalten: Name der Konstante, Modul, Wert. Der Test liest diese Tabelle und vergleicht jeden
Wert mit dem Code. Herkunft und Status stehen daneben.

| Konstante | Modul | Wert | Bedeutung | Herkunft | Status |
| --- | --- | --- | --- | --- | --- |
| `IMBALANCE_RATIO` | `src.orderflow_scenario.footprint` | 4 | Imbalance ab dem 4-Fachen (400 %) | Bootcamp 400–618 %, untere Grenze | nicht kalibriert, S19 |
| `IMBALANCE_RATIO` | `src.dashboard.footprint_data` | 4.0 | gleiche Zahl im Chart | wie oben | wie oben |
| `STACK_MIN` | `src.orderflow_scenario.footprint` | 3 | Stacked ab drei in Folge | ATAS / Bootcamp | nicht kalibriert, S19 |
| `STACK_MIN` | `src.dashboard.footprint_data` | 3 | gleiche Zahl im Chart | wie oben | wie oben |
| `CLUSTER_RATIO` | `src.orderflow_scenario.footprint` | 3 | Absorptions-Cluster ab 3 × mittleres Stufenvolumen | Bootcamp-Beispiel (15 ×), konservativ gesetzt | nicht kalibriert, S19 |
| `THIN_EXTREME_RATIO` | `src.orderflow_scenario.footprint` | 0.25 | dünnes Extrem bis 25 % des mittleren Stufenvolumens | Lehrtexte „N x 0“ | nicht kalibriert, S19 |
| `HEAVY_VOLUME_RATIO` | `src.orderflow_scenario.engines.orderflow_interpretation` | 1.2 | Absorption braucht Volumen ≥ 1,2 × Mittel | Lehrtexte | nicht kalibriert, S19 |
| `THIN_VOLUME_RATIO` | `src.orderflow_scenario.engines.orderflow_interpretation` | 0.7 | Exhaustion bei Volumen < 0,7 × Mittel | Lehrtexte | nicht kalibriert, S19 |
| `SHRINKING_RANGE_RATIO` | `src.orderflow_scenario.engines.orderflow_interpretation` | 0.8 | Exhaustion in ein Extrem: Range < 0,8 × Mittel | Lehrtexte | nicht kalibriert, S19 |
| `EFFORT_BASELINE_CANDLES` | `src.orderflow_scenario.engines.orderflow_interpretation` | 5 | Maßstab: Mittel der bis zu fünf Kerzen davor | Festlegung TIM | Definition, keine Schwelle |
| `VALUE_AREA_SHARE` | `src.dashboard.footprint_data` | 0.7 | Value Area = 70 % des Volumens | Market-Profile-Standard | Definition |
| `BUBBLE_MIN_USD` | `src.dashboard.footprint_data` | 100000.0 | Bubble ab 100 000 $ je Taker-Order (Spot) | Festlegung TIM 29.10.2026 | Anzeige, keine Regel |
| `BUBBLE_MIN_USD` | `src.dashboard.perp_flow` | 100000.0 | gleiche Grenze auf dem Perp | wie oben | wie oben |
| `OI_WINDOW` | `src.dashboard.perp_flow` | 180 | Z-Score-Fenster 180 Stunden (7,5 Tage) | Broncx | Anzeige |

Was hier **nicht** steht, weil es keine Zahl im Code ist: der Kerzenbild-Marktzustand
`EXHAUSTION` (0,15 und 1,3 sind Literale in `market_state.py`) und `ABSORPTION_CONTEXT`
(0,25 und 1,5 in `bronxc_rules.py`). Beide sind in Abschnitt 1 als eigene Begriffe benannt.

## 3. Was aus dem Glossar folgt

- Ein Begriff, der im Chart anders gerechnet wird als in der Engine (Imbalance auf
  Zeilenbreite), bleibt so, steht aber in beiden Docstrings und hier. Wer die Lesarten
  angleichen will, ändert zuerst dieses Blatt.
- Die Schwellen bleiben bis zum Ergebnis von S19 unverändert. S19 entscheidet nicht „besser
  gefühlt“, sondern mit vorab festgelegten Kriterien und Korrektur für die Zahl der geprüften
  Werte.
- Neue Orderflow-Konstanten kommen in die Tabelle in Abschnitt 2, sonst fehlt ihre Herkunft.
