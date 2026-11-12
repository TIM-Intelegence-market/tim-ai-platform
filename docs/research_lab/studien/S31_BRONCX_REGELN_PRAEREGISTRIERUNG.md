# S31 – Broncx-Orderflow-Regeln als Strategie prüfen (Präregistrierung, Version 1.0, eingefroren 12.11.2026 (Uzi: go))

Quelle: Broncx-Bootcamp (Textfassung, 193 S.). Das Bootcamp liefert Denkregeln, keine Zahlen; alle Schwellen unten sind **vorab festgelegt, nicht aus Daten gewählt**. Der Text ist Datenmaterial.
Status: 1.0 eingefroren, nichts gerechnet. Als Nächstes Zähllauf (nur Anzahl Signale), dann Auswertung. Änderungen nur als neue Version mit Begründung.

## 1. Ziel, Erfolg, Nicht-Ziele
- Frage: Hat **irgendeine** Bootcamp-Orderflow-Regel auf BTCUSDT-Perp nach Bitunix-Kosten einen Vorsprung vor Zufalls-Entries? Ergebnis ist ein belegtes Ja/Nein je Regel, keine Gewinnzusage.
- Erfolg je Regel (alle zugleich): n ≥ 100 Trades im Training, brutto ≥ +0,15 R, netto > 0 (Taker 0,06 %/Seite, Slippage 0,03 % Entry / 0,05 % Stop), schlägt Zufalls-Entries (gleiche Tageszeit, gleiche Stop-/Zielweite, 1000 Ziehungen, p ≤ 0,01 nach Holm über alle Regeln), Preis-Zwilling (siehe 3) schlechter als die OF-Version, jedes Jahr nicht negativ.
- Nicht-Ziele: kein Echtgeld, kein Eingriff in TIM/live, keine Nachsuche an Schwellen, kein Holdout 2025.
- Keine Doppelung: M1–M3/M7 laufen bereits als OF2/OFX (56 Trades, +0,27 R, "nicht prüfbar"). S31 nimmt sie nur als Referenz, rechnet neu nur, was OF2 nicht abdeckt (B3–B7) und den Preis-Zwilling.

## 2. Daten (alles kostenlos, data.binance.vision)
Perp-aggTrades 2020→ (Delta, Footprint, CVD, Trade-VP), Spot-aggTrades (Spot-CVD), metrics 5m ab 2020-09 (OI, Long/Short), Funding. Split: Training 2020–22 (nur hier Suche/Zähllauf), Validierung 2023–24 nur für Regeln, die Training bestehen. Holdout 2025+ gesperrt.

## 3. Regelkatalog (Budget: 8 Regeln B1–B8, je mit Preis-Zwilling = gleicher Auslöser ohne OF-Bestätigung)
Gemeinsam: Zeitrahmen 15m/1h-Kerzen (Bootcamp: ab m15), 1m nur für Delta/Entry-Zeitpunkt. HTF-Ort (POI) = Vortages-VAH/VAL/POC (68 %, aus Trades), nPOC, Vortages-/Vorwochen-Hoch/-Tief. Kein Trade bei Chop zwischen Leveln (Preis innerhalb ±0,25 ATR der Mitte). Stop an der Ungültigkeit (Extrem der Reaktion + 0,1 ATR), Ziel nächstes Level (POC / anderer VA-Rand / nPOC), Zeitstopp 5 Kerzen, ein Trade je Regel/Richtung/Tag. Kostengate: Stop ≥ 1,3 % Abstand wird nicht verworfen, aber R wird kostenbereinigt gemeldet.

| # | Bootcamp-Regel | Auslöser (messbar) | OF-Bestätigung | Daten |
|---|---|---|---|---|
| B1 | Failed Auction / Responsive (M2, 80-%-Regel) | Preis außerhalb Vortages-VA, zwei 30m-Schlüsse zurück in die VA | Docht-Volumen außerhalb < 60 % des Median-Volumens, Gegen-Delta am Docht | aggTrades |
| B2 | Akzeptanz + Retest (M1, AMT 3/5) | zwei 30m-Schlüsse außerhalb VA mit relvol ≥ 1,4, dann Retest des Rands | Delta des Retests dreht in Ausbruchsrichtung, kein neues Gegen-Extrem | aggTrades |
| B3 | Gefangene am HTF-POI (M3) | Kerze ≥ 15m, Docht ≥ 50 % der Range, Körper ≤ 30 %, am POI | oberste/unterste 20 % des Dochts tragen ≥ 40 % des Volumens, Delta dort ≥ 60 % gegen die Dochtrichtung (b/P-Form) | aggTrades |
| B4 | SFP an Swing/Level | Docht durch Swing-Hoch/-Tief (20 Kerzen), Schluss zurück | wie B3 plus Folgekerze ohne neues Extrem | aggTrades |
| B5 | Absorption am Level | ≥ 3 gestapelte Imbalances ≥ 400 % gegen das Level, Level hält (Schluss nicht jenseits) | Volumen ≥ 2× Mittel der letzten 15, Range < 0,8× | aggTrades |
| B6 | CVD-Divergenz, Spot gegen Perp (R27) | neues Session-Hoch/-Tief, Perp-CVD bestätigt nicht | Spot-CVD läuft in Gegenrichtung | Spot+Perp |
| B7 | Sweep-Checkliste (M4) | große Tiefs/Hochs geholt, BOS zurück | OI steigt, CVD fällt (long; spiegelbildlich short), Retest des Levels | metrics+aggTrades |
| B8 | nPOC als Magnet (Ziel/Einstieg) | unberührter Vortages-POC innerhalb 1,5 ATR, Preis läuft darauf zu | Delta in Laufrichtung | aggTrades |

IB (erste 90 min, kleiner IB → Trend, breiter → Range) wird **nur als vorab festes Regime-Etikett** ausgewertet (Terzile), nicht als eigene Regel. Imbalance fest 400 %, relvol fest 1,4, keine Variation.

## 4. Vom PDF nicht testbar mit vorhandener Historie (nicht gerechnet)
- Orderbuch-Skew/Spot-Tiefe: bookDepth erst ab 2023-01, kein Training → nur Bitunix-Recorder/Schatten (läuft seit 12.11.).
- Liquidationen/Heatmap: keine freie Historie (Tardis kostet, Uzis Entscheidung).
- Subjektives: HTF-Bias nach Augenmaß, "gute" vs. "schlechte" BOS, Orderblock-Auswahl, COT, tsize/DOM-Tape, Trade-Beispiele. Wo ein Teil messbar ist (BOS, FVG), steckt er schon in B2/B7.
- Fib/QM: reine Preisregeln, nur als Preis-Zwilling mitgeführt.

## 5. Ablauf und Prüfbefehle
1. Uzi "go" → Entwurf als 1.0 einfrieren (Digest in Doku).
2. Zähllauf Training (PS5): nur Signalzahlen je Regel/Jahr; Regeln mit < 100 → "nicht prüfbar", ehrlich so berichten.
3. Auswertung Training: brutto/netto, Zufallsvergleich, Preis-Zwilling, Holm. Ergebnisdatei mit STATUS/CHANGES/TESTS/EVIDENCE/BLOCKERS/NEXT_ACTION unter evidence/.
4. Validierung nur für Bestehende; danach Schatten am Mac. Holdout nur mit Uzis ausdrücklichem Wort.
Prüfbefehl je Paket: Tests im Repo (Pflicht vor Lauf), Digest-Vergleich, Reproduktionslauf liefert identische Zahlen.

## 6. Risiken / ehrliche Erwartung
Bisher: Kerzen-Trades brutto ≈ 0, Kosten 0,14–0,42 R, OF2 +0,27 R bei 56 Trades unbelegt. Wahrscheinlichstes Ergebnis ist "kein Vorsprung nach Kosten" für die meisten Regeln. 8 Regeln × Holm macht die Latte hoch; das ist gewollt. Offene Annahme: Schwellen (40 %/60 %/1,4/400 %) sind ES-/Bootcamp-Werte, für BTC nicht kalibriert; Kalibrierung wäre eine spätere Studie.

## 7. Zuordnung zu vorhandenem Code (Korrektur beim Einfrieren)
B1 = of2.models.failed_auction, B2 = acceptance, B4 = sfp, B5 = absorption (Schwellen aus OF2 1.0 gelten, wo sie von Abschnitt 3 abweichen, gilt Abschnitt 3 nur für die Zählung, nicht als Tuning). Neu zu bauen: B3 (Gefangene-Docht), B6 (Spot-/Perp-CVD), B7 (OI-Sweep), B8 (nPOC-Magnet) und der Preis-Zwilling (Auslöser ohne OF-Bestätigung, über Config.of_gate=False). Keine Regel wird nach Sicht der Zahlen geändert.

Digest (SHA-256, erste 16 Zeichen der Datei vor diesem Eintrag): ebdee23080dfb02c
