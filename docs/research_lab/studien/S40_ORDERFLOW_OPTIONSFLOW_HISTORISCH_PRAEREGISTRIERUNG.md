# S40 – Hilft Orderflow oder Optionsflow über den Preis hinaus? (Präregistrierung, Version 1.0, eingefroren 24.11.2026)

Auftrag Uzi 23.11.2026: "Go P0-P4, historisch ja" (Weg H erlaubt), dann "s40 go". Grundlage: Forschungsplan
`docs/research_lab/of_optionen_gamma/FORSCHUNGSPLAN.md` (Abschnitte 4, 5, 7, 8, 11) und die Bausteine aus PR #352.
**Status: eingefroren 1.0** auf Uzis Wort ("merge + einfrieren", 24.11.2026 10:15 Ortszeit), nach zwei Prüfungen durch
`studien-pruefer` (0.1, 0.3). Ab jetzt wird nichts mehr geändert; jede Änderung ist eine neue Version.
Protokoll 1.3 (`src/research_lab/protocol.py`). Wie S34–S39 wird S40 per PR eingefroren (Hash des Commits im Bericht)
und nicht in `REGISTER.jsonl` eingetragen (dort 58 von 60 Plätzen belegt, `MAX_REGISTER_ENTRIES`).
Änderungen 0.1 → 0.2: Prüfung `studien-pruefer` vom 23.11. (12 Punkte), alle eingearbeitet (Abschnitt 13).

## 1. Frage in einem Satz
Sagen die vergangenen Käufe und Verkäufe (Orderflow aus Perp-Trades) oder die Optionskäufe (Deribit-Optionstrades)
die Kursrichtung der nächsten 1 bzw. 4 Stunden besser voraus als der Kurs allein?

## 2. Was S40 nicht prüft (Nicht-Ziele)
- **Gamma** (H1, Modelle A3, A4, A6): historisch fehlt Open Interest je Strike. Bleibt Weg V (vorwärts), eigene Version.
- **Orderbuch-Signale** (F3 Nachfüll-Teil, F4, F5, F9): keine L2-Historie. Bleiben vorwärts.
- **Q1, Q3, Q4** (Put/Call-Prämie, große Trades, Strukturen): überschneiden sich mit S33 (R4, R2, R3) und werden hier nicht
  getestet. **Q2, Q10** (brauchen OI) und **Q7–Q9** (Spanne statt Richtung) ebenfalls nicht.
- **Holdout ab 2025-01-01** wird nicht gelesen: Der Lader überspringt Archivdateien ab 2025 ungeöffnet
  (`fusion/historisch.py`), `purged_splits` und `compare` brechen bei jeder Zeile oder jedem Ziel ab 2025 ab.
- Keine Orders, kein Papierhandel, keine Live-Änderung. `TRADING_AUTHORIZED=NO` bleibt.

## 3. Abschnitte
Nach `protocol.py` (`VALIDATION_START_MS` = 2023-01-01): **Training 2020–2022, Validierung 2023–2024**, Holdout gesperrt.
(Hinweis: OFX nutzte nach Uzis Wort vom 10.11. Training 2020–23/Validierung 2024. S40 folgt dem Code wie S38; eine
andere Teilung wäre eine Entscheidung von Uzi vor dem Einfrieren.)

## 4. Daten
| Quelle | Inhalt | Zeitraum | Markt |
|---|---|---|---|
| Binance USDⓈ-M Archiv `aggTrades`, Tages-ZIP mit CSV | `agg_trade_id`, Preis, Menge, Zeit, `is_buyer_maker` | 2020-01 bis 2024-12 | BTCUSDT, ETHUSDT, SOLUSDT (ab 2020-09-14) |
| Binance Funding-Archiv `fundingRate` | Rate je Funding-Zeitpunkt | 2020-01 bis 2024-12 | wie oben |
| Deribit `history.deribit.com` Optionstrades | Instrument, Menge, IV, Index, Taker-Seite, Block-/Combo-ID | 2020-01 bis 2024-12, **Abdeckung vor 2021 OFFEN** | nur BTC |

- Empfangszeit: historische Zeilen bekommen `recv_ms = ts + 2000 ms` (`historisch.LATENCY_MS`).
- **Datenreife (Paket 1, vor Version 1.0):** je Quelle und Kalendermonat ein eigener Bericht (Monat für Monat gelesen,
  nicht der ganze Strom auf einmal). Perp-Trades: Monat gilt, wenn Lückenanteil < 2 % (Lücke = mehr als 10 min ohne
  Trade, berechnet beim Laden je Tag in `studies/s40_daten.py`, gleiche Konstanten wie `fusion/datenreife.py`). Deribit-Optionen: ein UTC-Tag gilt, wenn ≥ 50 Optionstrades
  (Optionen handeln nachts selten, die 10-min-Regel passt dort nicht). Ungültige Monate/Tage werden gezählt, nie gefüllt.
- Fehlt Deribit vor 2021 oder ist es lückenhaft, beginnen nur die Optionsflow-Tests (T7–T12) später. Der Startmonat wird
  im Datenreife-Bericht festgestellt und **vor jedem Ergebnis** in Version 1.0 eingetragen.

## 5. Raster, Zeitpunkte und Ziel
- 5-Minuten-Bars aus Trades (`of_features.bars_from_trades`): `known_ms` = max(Empfang des letzten Trades, Bar-Ende).
- **Prognosezeitpunkt t:** jede volle Stunde (h = 1 h) bzw. 00/04/08/12/16/20 UTC (h = 4 h). Merkmale nutzen nur
  Bars, die bis t bekannt sind (`known_ms ≤ t`), und nur Optionstrades mit `recv_ms ≤ t`. Die Ziele überlappen nicht.
- **Ziel:** Log-Rendite vom Eröffnungskurs der ersten Bar, die **zu oder nach t** öffnet, bis zum Eröffnungskurs
  h Stunden an Bars später (h = 12 bzw. 48 Bars; `studies/s40.label`). Da alle Merkmale bis t bekannt sind, liegt der
  Einstieg nie vor dem Wissen. (0.2 nannte `forward_label` mit Einstieg nach `known_ms`; in 0.3 strenger und einfacher:
  Einstieg ab t.) Fehlende Bars verlängern den Horizont; Zeilen, deren Ziel mehr als 10 % länger dauert als h, fallen
  heraus (gezählt).

## 6. Merkmale (fest, nur Vergangenheit)
**Normierung:** Stetige Merkmale (in der Tabelle mit z markiert) werden als z-Wert gegen die eigenen Werte der
**720 vorherigen vollen Stunden** geführt (30 Tage, t selbst ausgeschlossen), gleich für h = 1 h und 4 h. Fehlende Werte
(ungültige Monate) zählen nicht mit, das Fenster läuft über sie hinweg. Weniger als 480 gültige Werte im Fenster (20
Tage) oder Streuung 0: Merkmal fehlt. Tageszeit und die Dreiwert-Merkmale bleiben roh.

| Gruppe | Merkmal | Definition |
|---|---|---|
| Preis (A0) | `ret_1h`, `ret_4h`, `ret_24h` (z) | Log-Rendite vom Schluss der Bar 1/4/24 h vor t bis zum Schluss der letzten Bar vor t |
| Preis (A0) | `rv_24h` (z) | Wurzel der Summe quadrierter 5-min-Log-Renditen der letzten 288 Bars |
| Preis (A0) | `hour_sin`, `hour_cos` | sin/cos(2π·Stunde/24), Stunde von t in UTC |
| Orderflow (A1) | `ai_1h`, `ai_4h` (z) | F2: (Kauf − Verkauf)/(Kauf + Verkauf) des aggressiven Volumens der letzten 12/48 Bars |
| Orderflow (A1) | `cvd_div` (roh, −1/0/+1) | F1: `of_features.cvd_divergence(lookback=24, right=3, k_sigma=1.0)`, ausgewertet an jeder der letzten 12 Bars vor t; Wert = letzter von 0 verschiedener Wert, sonst 0 |
| Orderflow (A1) | `sweep` (roh, −1/0/+1) | F6: `of_features.sweep(lookback=24, m=3, min_excess=0.001, vol_mult=2.0)` (Hoch/Tief der 24 Bars vor dem 3-Bar-Fenster, Überschreitung > 0,1 % bei Volumen ≥ 2× Median, Schluss zurück), ausgewertet wie `cvd_div` |
| Optionsflow (A2, nur BTC) | `daf_1h`, `daf_24h` (z) | Q5: Netto-Delta der Taker (Käufe minus Verkäufe) in USD über 1/24 h vor t (`features_q.greek_flow`) |
| Optionsflow (A2, nur BTC) | `gaf_1h`, `gaf_24h` (z) | Q6: Netto-Gamma der Taker in USD je 1 % über 1/24 h vor t |

Optionsflow-Regeln: Block- und Combo-Trades (`group_id` gesetzt) zählen **nicht** (Forschungsplan Abschnitt 9: getrennt
führen; explorativ berichtet). Delta und Gamma nach Black-Scholes auf den Indexpreis, Zins 0, IV des Trades, wie
`features_q`. Das ungewichtete Delta inverser Optionen (ohne Prämienanpassung) ist eine **MODELLANNAHME**
(Forschungsplan 6.1); es betrifft die Größe, kaum das Vorzeichen. Liegt im 24-h-Fenster ein ungültiger Deribit-Tag,
fehlen die Optionsmerkmale dieser Zeile.

**Laufzeit:** `cvd` und `confirmed_swings` rechnen bei jedem Aufruf ab Bar 0. `s40.py` rechnet sie fortlaufend
(inkrementell) und muss in einem Test für 2.000 synthetische Bars dieselben Werte liefern wie die Bausteine.

## 7. Modelle und Rechnung
Modelle (alle enthalten den Preis, `walkforward.MODELS`): A0 = Preis; A1 = Preis + Orderflow; A2 = Preis + Optionsflow;
A5 = Preis + Orderflow + Optionsflow. Ridge mit λ = 1 auf standardisierten Merkmalen (Mittel und Streuung nur aus dem
jeweiligen Trainingsteil). Keine Baumverfahren, keine Merkmalsauswahl, keine Parametersuche.

**Zeilenbasis:** `compare` wird **je Test einzeln** mit genau den beiden verglichenen Modellen aufgerufen (`models` =
Teilmenge). Damit gelten für jeden Test die Zeilen, auf denen beide Modelle alle Merkmale haben; fehlende Optionsdaten
kürzen T1–T6 nicht. A3, A4, A6 werden nicht aufgerufen.

1. **Training 2020–2022:** Walk-forward mit wachsendem Fenster, 6 Folds (`purged_splits`), erster Trainingsblock
   `min_train` = 4.320 Zeilen (h = 1 h) bzw. 1.080 Zeilen (h = 4 h), das sind 180 Tage. Embargo = h + 24 h + 2 s.
   Ausgewertet werden nur Vorhersagen außerhalb der Stichprobe ("OOS-Zeilen").
2. **Validierung 2023–2024 (genau einmal, nur Tests, die das Training bestehen):** Trainingszeilen mit
   `label_end_ms ≥ 2023-01-01 − Embargo` fallen weg; jedes Modell wird einmal auf allen übrigen Trainingszeilen geschätzt,
   Koeffizienten mit SHA-256 im Bericht, dann auf 2023–2024 vorhergesagt. Kein Nachschätzen. `s40.py` braucht dafür eine
   eigene Funktion mit Test (Grenze und Hash).
3. **Bericht** aller 12 Tests, auch der nicht bestandenen.

## 8. Haupttests (genau 12, Holm über 12)
Prüfgröße: Clark-West (einseitig, größeres Modell besser) auf den OOS-Zeilen, Standardfehler nach **Newey-West** mit
Lag L = ⌊4·(n/100)^(2/9)⌋ (feste Regel; Volatilitäts-Cluster machen die Verlustdifferenzen abhängig). `s40.py` ergänzt
diese HAC-Variante; `walkforward.clark_west` (einfacher Fehler) wird nur zusätzlich berichtet.

| Nr | Markt | Vergleich | h |
|---|---|---|---|
| T1, T2 | BTC | A1 gegen A0 | 1 h, 4 h |
| T3, T4 | ETH | A1 gegen A0 | 1 h, 4 h |
| T5, T6 | SOL | A1 gegen A0 | 1 h, 4 h |
| T7, T8 | BTC | A2 gegen A0 | 1 h, 4 h |
| T9, T10 | BTC | A5 gegen A1 (H2: Optionsflow zusätzlich zum Orderflow) | 1 h, 4 h |
| T11, T12 | BTC | A5 gegen A0 | 1 h, 4 h |

Die Märkte sind korreliert. Holm gilt auch bei Abhängigkeit; BTC, ETH und SOL werden nicht zu einer Stichprobe
zusammengelegt. Alles andere (5 m, 15 m, 24 h; Einzelmerkmale; Blocks/Combos; Tageszeit- und Regime-Schnitte; F7, F8,
F10) ist **explorativ** und kann nichts bestehen.

## 9. Erfolgskriterien
**Training (je Test, alle zugleich):**
- OOS-Zeilen n ≥ 10.000 (h = 1 h) bzw. ≥ 2.500 (h = 4 h), sonst "nicht prüfbar".
- Clark-West (HAC) Holm-p ≤ 0,05 über 12.
- Spearman-IC des größeren Modells > IC des kleineren und > 0.
- Jahresregel auf der Clark-West-Größe f (angepasste MSPE-Differenz je Zeile): ein Kalenderjahr zählt, wenn es
  ≥ 2.000 (1 h) bzw. ≥ 500 (4 h) OOS-Zeilen hat. Summe f > 0 in mindestens 2 der zählenden Jahre; bei nur 2 zählenden
  Jahren (SOL, evtl. Optionsflow) in beiden. Kein Jahr trägt mehr als 60 % der Gesamtsumme von f.

**Validierung (nur bestandene Tests):** gleiche Richtung, Clark-West (HAC) einseitig p ≤ 0,05 mit Holm über die Zahl der
bestandenen Tests, IC-Gewinn > 0, n ≥ 10.000 (1 h) bzw. ≥ 2.500 (4 h).

**Handelsprüfung (nur wenn ein Test die Validierung besteht, sonst entfällt sie):** Regel fest: Einstieg wie das Ziel
(Abschnitt 5), wenn |Vorhersage| > 0,20 %, Richtung = Vorzeichen, Ausstieg nach h, kein Stop.
- Kosten Basis: Taker 0,06 % je Seite plus Schlupf 0,03 % je Seite (zusammen 0,18 % hin und zurück). Funding: tatsächliche
  Binance-Rate an jedem Funding-Zeitpunkt (00/08/16 UTC) mit Einstieg < Zeitpunkt ≤ Ausstieg, Long zahlt bei positiver
  Rate. Bitunix-Funding fehlt historisch; Binance als Ersatz ist eine Annahme.
- Kosten Stress: doppelte Basis (0,36 % hin und zurück), keine Funding-Gutschrift. Zusätzlich berichtet: `STRESS_COSTS`
  aus `protocol.py` (baut auf 0,05 % Gebühr auf, 0,32 % hin und zurück).
- Bestanden, wenn in der Validierung (a) Netto-Rendite je Trade > 0 mit 90-%-Block-Bootstrap (Kalenderwoche, 10.000,
  Seed 40) Untergrenze > 0, (b) mit Stress-Kosten noch > 0, (c) Deflated Sharpe ≥ 0,95 mit N = **8.106.956** Versuchen
  (OFX 8.106.900 Varianten laut Studienregister, S35a 12, S36 15, OF2 7, S31 8, S31b 2, S40 12), (d) n ≥ 300 Trades.
  Mit diesem N ist (c) fast unerreichbar; das ist gewollt, die Familie wurde schon sehr breit durchsucht.

**Bestanden heißt nur:** "Merkmal sagt historisch etwas voraus". Es ist keine Handelsfreigabe. Nächster Schritt wäre ein
Papier-Vorwärtslauf (Gate G-G, ≥ 3 Monate), nie Echtgeld.

## 10. Stichprobe (vorab gerechnet, MODELLANNAHME)
Basis sind die OOS-Zeilen vor Ausschlüssen: Training 26.300 h minus 180 Tage erster Block minus 20 Tage Vorlauf.
Nachweisgrenze für den IC eines Modells ≈ (z_α + z_β)/√n mit Power 80 %: ohne Holm 2,49/√n, mit Holm-Stufe α = 0,05/12
etwa 3,48/√n.

| Fall | OOS-Zeilen (ca.) | IC ohne Holm | IC mit Holm |
|---|---|---|---|
| Training BTC/ETH 1 h | 21.000 | 0,017 | 0,024 |
| Training BTC/ETH 4 h | 5.300 | 0,034 | 0,048 |
| Training SOL 1 h | 15.500 | 0,020 | 0,028 |
| Training SOL 4 h | 3.900 | 0,040 | 0,056 |
| Validierung 1 h | 17.500 | 0,019 | – |
| Validierung 4 h | 4.400 | 0,038 | – |

Die Rechnung gilt für das IC-Niveau eines Modells, **nicht** für den Clark-West-Zuwachs eines verschachtelten Modells;
dessen Trennschärfe ist nicht vorab belegt. Die Literatur (Forschungsplan Abschnitt 1) erwartet über 15 Minuten kaum
Vorhersagekraft. "Nicht bestanden" ist das wahrscheinlichste Ergebnis und wird so berichtet.

## 11. Abbruch und Sonderfälle
- Datenreife zeigt für einen Markt weniger als 70 % gültige Monate in einem Abschnitt: dieser Markt "nicht prüfbar".
- Rechenfehler oder Look-ahead-Fund nach dem Einfrieren: Lauf ungültig, Fund im Bericht, neue Version.
- Holdout-Zeile im Lauf: der Code bricht ab; das wird als Fehler berichtet, nie umgangen.

## 12. Pakete und Prüfbefehle
1. **Datenreife** (liest nur, vor 1.0): Archive 2020–2024 auf der PS5 laden, dann
   `python -m src.research_lab.studies.s40_daten laden --ziel DIR`, dann `... s40_daten bericht --ziel DIR`
   (Tages-ZIPs mit Prüfsumme, 5-min-Bars, Lücken je Tag, Deribit-Tagesregel, Monatsbericht `datenreife.json`).
   Ergebnis in `S40_DATENREIFE.md`. Der Startmonat Optionsflow wird als `OPTIONS_START_MONTH` in `s40.py` eingetragen.
2. **Einfrieren 1.0** per PR: diese Datei ohne "ENTWURF", Startmonat Optionsflow eingetragen,
   `src/research_lab/studies/s40.py`, Tests mit synthetischen Daten: Look-ahead-Test je Merkmal (Zukunft verändern,
   Merkmal bei t gleich), inkrementell = Baustein, Validierungsgrenze und Hash, HAC-Clark-West gegen Handrechnung.
   Prüfung `studien-pruefer`, dann Uzis "einfrieren".
3. **Training** auf dem Mac (Datenordner `~/Documents/TIM/s40-data`): `python -m src.research_lab.studies.s40 --phase train`.
4. **Validierung** nur bei bestandenem Training: `--phase validate`.
5. **Bericht** `S40_BERICHT.md` mit allen 12 Tests.

## 13. Eingearbeitete Prüfung (studien-pruefer, 23.11.2026, Urteil 0.1: NACHBESSERN)
Datenreife je Monat und mit ZIP-Lader (1); `sweep`/`cvd_div` mit Code-Parametern und Auswertungsfenster (2); Zeilenbasis
je Test, A3/A4/A6 nicht aufgerufen (3); z-Wert-Regel eindeutig (4); Purge an der Grenze 2022/2023 (5); HAC-Fehler (6);
Jahresregel, n-Basis und `min_train` in Zeilen (7); Stichprobe auf OOS-Basis mit Holm (8); Kosten, Stress und Funding
(9); feste Versuchszahl (10); Optionsflow-Regeln (11); Einstiegsversatz dokumentiert, Abschnittsteilung benannt (12).
Offen bis 1.0: Deribit-Abdeckung 2020 (Paket 1).

**0.3 (23.11.):** Rechencode `src/research_lab/studies/s40.py` mit Tests `tests/test_s40.py` (schnelle Merkmale gleich
den Bausteinen, Look-ahead, z-Werte nur aus Vorstunden, HAC-Clark-West gegen Handrechnung, Holm, Jahresregel,
Monatsausschluss und Holdout, Kosten und Funding, Wiederfinden eines eingepflanzten Effekts). Einstiegsregel in
Abschnitt 5 präzisiert (Einstiegs-Bar muss vor t + 5 min öffnen, Dehnung ab t gemessen, letzte bekannte Bar höchstens
10 min alt). Zweite Prüfung `studien-pruefer` (12 Punkte) eingearbeitet: Trainingsziele enden vor 2023, Werte aus
ungültigen Monaten nicht im z-Fenster, Ausschlüsse je Grund gezählt, Deribit-70-%-Regel und Startmonat, Dateien ab 2025
ungeöffnet, `STRESS_COSTS` zusätzlich berichtet, ISO-Wochen im Bootstrap, Sperren gegen zweites Training und gegen
Validierung mit anderem Code oder anderen Daten, Optionen je Sekunde gebündelt (Speicher).

**Von Uzi entschieden (23.11., "lassen"/"jaja"):** (1) Teilung 2020–2022 Training / 2023–2024 Validierung (wie
`protocol.py`); (2) Deflated Sharpe ≥ 0,95 ist Pflicht der Handelsprüfung.

**1.0 (24.11.):** Datenreife fertig (`S40_DATENREIFE.md`): alle Quellen 100 % gültige Monate, T1–T12 prüfbar,
`OPTIONS_START_MONTH = "2020-01"`. Daten auf dem Mac geladen (nicht PS5, Uzi 23.11.). Keine Regeländerung gegenüber 0.3.
