# Orderflow-Regeln für TIM: Absorption, Exhaustion und Umfeld

Stand: 2026-10-26. Quellen: Broncx-Bootcamp-PDF (Seiten laut
[BRONCX_BOOTCAMP_KNOWLEDGE.md](BRONCX_BOOTCAMP_KNOWLEDGE.md), Abschnitt „Footprint delta“
77-90, 183-187) und die unter „Quellen“ genannten öffentlichen Texte. Das Dokument ist
Lernstoff und Regelbuch für die Orderflow-Engine, kein Handelssignal und kein Nachweis
für einen Edge. Jede Regel ist eine Beobachtung mit Bedingungen; eine Entscheidung braucht
weiterhin Ort (HTF-Level), zweite unabhängige Evidenz und eine Invalidierung
(Interpretationsvertrag im Bootcamp-Katalog).

## 1. Grundbegriffe

| Begriff | Bedeutung | Woran TIM es misst |
| --- | --- | --- |
| Aggressor / Market Order | Wer den Preis bezahlt („kauf mir x BTC, egal zu welchem Preis“). Market Orders sind die schwerere Hand; Limit Orders nutzen eher große Teilnehmer (Bootcamp, CVD-Abschnitt). | `net_delta`, `aggressive_buy_volume`, `aggressive_sell_volume` |
| Delta | Aggressive Käufe minus aggressive Verkäufe je Kerze oder Preisstufe. | `net_delta` (Fenster), `delta_series` (je Kerze, optional) |
| CVD | Laufende Summe des Deltas. Steigender Kurs bei fallendem CVD = aggressives Verkaufen in passive Bids (bullisch gelesen). Spot-CVD kann keine Shorts enthalten; Spot gegen Perp vergleichen. | nur Eingabe `delta_divergence`, kein eigener CVD-Lauf |
| Footprint | Bid-/Ask-Volumen je Preisstufe innerhalb einer Kerze. Links Verkäufer (in den Bid), rechts Käufer (in den Ask). | `src/orderflow_scenario/footprint.py`: aus Binance-aggTrades (`buyer_is_maker`) oder OpenMarket `VOLUME_PROFILE_AGG` je Intervall |
| Imbalance | Eine Seite überwiegt die andere diagonal um ein Vielfaches; Bootcamp: 400-618 %. Drei oder mehr hintereinander = „stacked“, Aggression mit Fortsetzungsneigung, kann aber absorbiert werden. | F1/F2 in `analyze_footprint` (Faktor 4, Stapel ≥ 3) |
| Finished / Unfinished Auction | Kerzenextrem mit Null auf einer Seite = Auktion beendet, oft lokales Hoch/Tief. Beide Seiten > 0 am Extrem = unerledigt, Preis kommt oft zurück (Magnet). | F3 in `analyze_footprint` |
| Trapped / Puking | Gefangene Positionen schließen („puken“); jedes Schließen eröffnet die Gegenposition und treibt den Kurs. Hohes Delta ohne Follow-through in einen Orderblock = Puken. | Szenario-Belege `buyers_trapped`, `positive_delta_without_progress` |
| Volume Bubbles / RVOL | Große Marktorders und relatives Volumen als Bestätigung am Level. | `volume_bubbles` (Eingabe), `volume_ratio` (neu) |
| Open Interest | Offene Kontrakte. OI steigt + Preis fällt = Shorts stapeln sich; OI fällt + Preis steigt = Short Covering. | `positioning.py`, `open_interest_with_price` |

## 2. Absorption gegen Exhaustion

Beide sehen auf der Kerze ähnlich aus (wenig Fortschritt, oft ein Docht). Unterschied ist
die **Anstrengung** hinter der Bewegung:

| | Absorption | Exhaustion |
| --- | --- | --- |
| Was passiert | Aggressive Marktorders treffen auf passive Limit Orders, die immer wieder nachgefüllt werden. Jemand hält dagegen. | Der aggressiven Seite gehen die Teilnehmer aus. Niemand hält dagegen, es ist schlicht niemand mehr da. |
| Volumen | Hoch, mindestens auf oder über dem jüngsten Normalmaß. | Dünn; jeder weitere Schub trägt weniger Volumen. |
| Delta | Weiter in Richtung der Bewegung, aber ohne Preisfortschritt („Delta Failure“). | Delta-Zuwachs je Kerze wird kleiner, am Ende Flip. „Delta Exhaustion“: neues Hoch, aber kleinerer Delta-Gewinn als in der Kerze davor. |
| Range | Preis bleibt stehen. | Schübe werden kleiner, letztes Extrem auf dünnster Beteiligung. |
| Ort | An einem verteidigten Referenzlevel (Swing, VAH/VAL, HVN, VWAP, Orderblock). | Am Ende einer längeren Einbahnbewegung. |
| Footprint-Bild | Großer Volumenstapel auf einer Preisstufe (Beispiel: 1.400 Kontrakte, 15-mal so viel wie daneben). | „N x 0“ oder „2 x N“ am Extrem: kein Rest-Gegenpart mehr. |
| Bestätigung | Delta-Flip, gescheiterter Retest des Levels, Strukturbruch in Gegenrichtung. | Delta-Flip, anschließende Absorption oder Delta-Failure; allein kein Trade. |
| Kann scheitern | Der passive Teilnehmer zieht seine Orders zurück, Level bricht. | Die Pause ist nur eine Pause, die Bewegung läuft weiter. |

Broncx selbst: „Finished auction was deciding factor for reversal. Lots of sellers puking (high
Delta)“ ist Absorption/Puken mit hohem Delta; „Sometimes signs are less obvious with exhaustion
cases on lower delta, but it's generally just a confluence and wouldn't enter with it on my own.“
Beide gelten bei ihm nur als Konfluenz am HTF-Level, nie als eigener Einstieg.

### Regeln in TIM (`src/orderflow_scenario/engines/orderflow_interpretation.py`)

Eingabe: Kerzen, `net_delta` (Fenster), optional `delta_series` (je Kerze), optional
`delta_divergence`. Anstrengung = Volumen der letzten Kerze geteilt durch den Mittelwert
der bis zu fünf Kerzen davor (`volume_ratio`), Range analog (`range_ratio`). Schwellen:
schwer ≥ 1,2, dünn < 0,7, schrumpfend < 0,8. Mit nur zwei Kerzen gibt es keinen Maßstab;
dann gilt der alte Lesart „Delta gegen Preis = Absorption“.

| Regel | Bedingung | Ergebnis (`reaction`) |
| --- | --- | --- |
| R1 | Delta gegen die Preisrichtung, Volumen nicht dünn | `ABSORPTION`, `absorption_hypothesis` = PASSIVE_SELLERS (Delta > 0) oder PASSIVE_BUYERS; bei schwerem Volumen Zusatz `absorption_effort_high_volume` |
| R2 | Delta gerichtet, Preis flach (< 0,1 %), Volumen schwer | `ABSORPTION` (`…_flat_price`) |
| R3 | Delta gegen die Preisrichtung, Volumen dünn | `EXHAUSTION`, Widerlegung `absorption_refuted_thin_volume`, `exhaustion_hypothesis` = BUYERS_EXHAUSTED (Delta > 0) oder SELLERS_EXHAUSTED |
| R4 | Delta mit der Preisrichtung, Volumen dünn **und** Range schrumpfend | `EXHAUSTION` (`aggressive_…_fading_into_extreme`); sonst `CONTINUATION` |
| Bestätigung Absorption | `delta_divergence = true` | `absorption_confirmed` |
| Bestätigung Exhaustion | `delta_series`: Delta der Aggressorseite dreimal kleiner (FADING) oder letzte Kerze gegen den Aggressor (FLIP) | `exhaustion_confirmed` |
| Widerlegung Exhaustion | `delta_series`: Delta der Aggressorseite wächst (EXPANDING) | Hypothese fällt, `exhaustion_refuted_delta_expanding`; bei Delta mit Preis wieder `CONTINUATION` |
| Fehlende Daten | Exhaustion-Hypothese ohne `delta_series` | `missing_data` enthält `delta_series` |

Absorption und Exhaustion schließen sich aus (`OrderflowInterpretation.__post_init__`).
Wirkung: Szenario A (Ausbruch long) bekommt `exhaustion_hypothesis_buyers_exhausted` als
Gegenbeleg und `…_sellers_exhausted` als Beleg; Szenario B (Sweep-Reversal long) Beleg bei
SELLERS_EXHAUSTED; Szenario C (Rejection short) Beleg bei BUYERS_EXHAUSTED. Eine bestätigte
Exhaustion zählt in der heuristischen Wahrscheinlichkeit wie eine bestätigte Absorption
(+0,06). Bericht: Zeilen „Reaktion“, „Exhaustion-Hypothese“, Evidenzkette „Exhaustion“.

### 2a. Footprint je Preisstufe (`src/orderflow_scenario/footprint.py`)

Ein Footprint-Balken enthält je Kerze und Preisstufe das Volumen in den Bid (aggressive
Verkäufe) und in den Ask (aggressive Käufe). Quellen: Binance-aggTrades mit `buyer_is_maker`
(`footprint_from_trades`, Tick-Größe nötig) oder OpenMarket `VOLUME_PROFILE_AGG` je Intervall
(`footprint_from_levels`, Bid = Sell, Ask = Buy; nur wenn `side_is_aggressor` belegt ist, sonst
`missing_data`). Gelesen wird der letzte Balken:

| Regel | Bedingung | Ergebnis |
| --- | --- | --- |
| F1 Imbalance | Ask auf Stufe p ≥ 4 × Bid auf p − 1 Tick (Kauf) bzw. Bid auf p ≥ 4 × Ask auf p + 1 Tick (Verkauf); eine Null auf der Gegenseite zählt | `buy_imbalances`, `sell_imbalances` |
| F2 Stacked | ≥ 3 gleichseitige Imbalances auf aufeinanderfolgenden Stufen | `stacked_buy`/`stacked_sell`; Szenario A Beleg (Kauf) / Gegenbeleg (Verkauf), B Gegenbeleg (Verkauf), C Gegenbeleg (Kauf); **widerlegt** eine Exhaustion-Hypothese der Aggressorseite (`exhaustion_refuted_stacked_imbalances`) |
| F3 Auktionsrand | Hoch oder Tief mit Null auf einer Seite = finished, beide > 0 = unfinished | `finished_high/low`; finished am Extrem in Bewegungsrichtung **bestätigt** Exhaustion (`exhaustion_supported_by_finished_auction`) |
| F4 Cluster | Eine Stufe ≥ 3 × mittleres Stufenvolumen, in den äußeren 20 % der Range, Aggressor drückt hinein | `absorption_cluster` PASSIVE_SELLERS/PASSIVE_BUYERS; passend zur Hypothese **bestätigt** Absorption (`absorption_supported_by_footprint_cluster`) |
| F5 Dünnes Extrem | Randstufe in Bewegungsrichtung ≤ 25 % des mittleren Stufenvolumens („N x 0“) | `thin_extreme`; **bestätigt** Exhaustion (`exhaustion_supported_by_thin_extreme`) |
| F6 Delta und POC | Delta je Balken liefert `delta_series`, wenn keine übergeben wurde; fehlt `net_delta`, gilt das Delta des letzten Balkens; POC-Lage UPPER/MIDDLE/LOWER (P-/b-Form-Hinweis) | `footprint.last_delta`, `poc_location` |

Eingabe: JSON `footprint: [{"open_time", "levels": [[Preis, Bid, Ask], …]}]` oder `footprint_tick_size`
plus Trades (CLI baut den Footprint). Ausgabe: `orderflow.footprint` im Analyse-JSON, Zeile
„Footprint“ im Bericht, `facts.footprint` in der Evidenzkette.

### Was TIM dabei noch nicht sieht

- Der OpenMarket-Footprint hängt an `side_is_aggressor` (REST-Seitensemantik laut Adapter
  noch unbewiesen); bis dahin bleibt dort nur das Profil (POC/VA) und `missing_data` nennt
  `footprint:VOLUME_PROFILE_AGG_side_semantics_unverified`. Stufenbreite dort 5 USD, also grob.
- Live-aggTrades aus der TIM-Datenbank sind noch nicht an die Pipeline angeschlossen; der
  Footprint aus Trades läuft über JSON-Eingaben (CLI).
- Der Marktzustand `EXHAUSTION` in `engines/market_state.py` ist nur ein Kerzenbild (langer
  Docht, Körper < 15 %, Volumen ≥ 1,3x). Das ist im Bootcamp-Sinn eher Excess/SFP-Docht und
  wird von keinem Szenario genutzt; maßgeblich ist die Reaktion der Orderflow-Engine.
- `src/analysis/bronxc_rules.py` nennt eine Kerze mit kleinem Körper und hohem Volumen
  `ABSORPTION_CONTEXT`. Das passt zu R1/R2 (Anstrengung ohne Fortschritt), kennt aber kein Delta.
- Schwellen (1,2 / 0,7 / 0,8; 4x; 3x; 25 %) stammen aus den Quellen und sind nicht kalibriert.

## 3. Weitere Bootcamp-Regeln (Status in TIM)

| Regel | Quelle | Status |
| --- | --- | --- |
| Reihenfolge: HTF-Kontext → Auktionsregime → Ort → Struktur → Orderflow → Reaktion → Szenario → Invalidierung | Bootcamp-Katalog | Vertrag der Pipeline |
| SFP: langer Docht durch Swing/Level ohne Schluss darüber; allein „Selbstmord“, braucht Orderflow-Bestätigung | Bootcamp Price Action | `liquidity_sweep_*` im Marktzustand |
| Orderblock wirkt durch gefangene Positionen: große Käufe in bärische OBs, große Verkäufe in bullische OBs; „nicht der OB zählt, die Reaktion“ | Bootcamp OB-Checkliste | Reaktion ja (R1-R4), OB-Erkennung nein |
| Balance = Range, Imbalance = dünne schnelle Bewegung (FVG); außerhalb Value erst Akzeptanz nachweisen; VAH → runter, VAL → hoch, außer klare Rejection | AMT | `auction_state`, `acceptance_*`, `rejection_*` |
| Profil: Volumen am unteren Ende = gefangene Verkäufer (b-Form), oben = gefangene Käufer (P-Form); nPOC, poor highs/lows, single prints | TPO/Profil | `positioning.py` (Profil-Lage), keine Formerkennung |
| CVD: Preis hoch + CVD runter = Verkäufe in passive Bids; Spot gegen Perp; Divergenzen als Umkehrhinweis | CVD | nur Flag `delta_divergence` |
| OI: steigt in Grind-down = Shorts stapeln sich (Squeeze-Kandidat); Checkliste „Lows gesweept + BOS + wicky highs + OI hoch + CVD runter + Retest Support/FVG“ | OI-Abschnitt | OI-Lesart ja, Checkliste als Ganzes nein |
| Orderbuch-Skew: Bid/Ask-Verhältnis bis x % Tiefe; schwere Bid-Seite = Widerstand nach unten, Orders können verschwinden | Walkthrough | `orderbook_depth` nur als Beobachtung |
| Grind/TWAP: gleichmäßiger Anstieg mit Stützen an den Hochs; nach Ende des TWAP große Expansion | Trade Breakdowns | fehlt |
| Stacked Imbalances: Aggression, Fortsetzung wahrscheinlich, es sei denn absorbiert; viele davon, daher nur Konfluenz | Footprint | F2, nur Beleg/Gegenbeleg in Szenarien |
| Finished Auction: lokales Top/Bottom, Unfinished: Magnet, nur an Schlüssellevels | Footprint | F3 als Beobachtung; Magnet-Logik (Rückkehr zum unfinished Rand) fehlt |

## 4. Prüfung

`tests/test_orderflow_absorption_exhaustion.py` deckt R1-R4, Bestätigung, Widerlegung,
Zwei-Kerzen-Rückfall, Adapter, Pipeline, Bericht und den Ausschluss beider Lesarten ab.
`tests/test_orderflow_footprint.py` deckt F1-F6, beide Builder, die Bestätigungen und
Widerlegungen in der Engine, Szenario-Belege, JSON-Adapter, CLI aus Trades, Bericht und den
OpenMarket-Adapter (Delta-Serie aus TRADE_AGG, Footprint aus VOLUME_PROFILE_AGG, gesperrt ohne
Seitennachweis) ab. `tests/test_orderflow_signed_delta.py` bleibt unverändert grün.

## Quellen

- Broncx-Bootcamp-PDF (Eigentümer-Kopie, nur Lernquelle): Footprint-, CVD-, OI-, AMT-, Profil-Abschnitte und Trade Breakdowns.
- LuxAlgo Library, „Absorption & Exhaustion“: https://www.luxalgo.com/library/concept/absorption-and-exhaustion/
- LuxAlgo Library, „Footprint Concepts“: https://www.luxalgo.com/library/concept/footprint-concepts/
- ATAS, „Footprint Patterns“ (stacked imbalances, finished/unfinished auction, absorption): https://learn.atas.net/volume-basics/volume-analysis/footprint-patterns
- NexusFi, „Advanced Footprint Chart Patterns“ (Delta Exhaustion, Delta Failure, Absorption; Trefferquoten dort sind unbelegte Eigenangaben): https://nexusfi.com/a/strategies/advanced-footprint-chart-patterns
- Crowstack, „Footprint Course: Absorption“ (nur frei lesbarer Teil, „N x 0“-Notation): https://crowstack.substack.com/p/footprint-course-absorption-lesson
- Optimus Futures, „Footprint Chart Absorption vs Exhaustion“ (Video, nur Kurztext): https://optimusfutures.com/blog/?p=19691
