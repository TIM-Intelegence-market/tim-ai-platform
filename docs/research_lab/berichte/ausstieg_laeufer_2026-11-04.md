# Läufer statt festem TP3: erste Auswertung (Papier), 04.11.2026

Stand 04.11. 16:35 (deutsche Zeit). Daten: TIM-Journale 15m, 1h, 30m; BTCUSDT-Spot-1m-Kerzen ab 27.10. (lückenlos);
Spot-Delta je Minute aus TIMs agg_trades (ab 27.10.); Perp-Delta erst ab 30.10. Kosten Kraken 5 bps je Seite.
Skript: `scripts/research_lab_exit_variants.py` (Branch claude/project-thread-wjvoz1).

## Methode
- Bis TP2 läuft jede Variante exakt wie das Journal. Nur das letzte Drittel nach TP2 wird auf 1m-Kerzen neu verfolgt.
- FEST = heutige Regel (TP3). Nachrechnung trifft das Journal in allen 10 Fällen auf den Preis genau.
- LAEUFER = kein TP3, Stop folgt wie heute dem letzten bestätigten Swing des Plan-Zeitfensters.
- LAEUFER_WEIT = Swing eine Stufe höher (15m→1h, 1h→4h).
- OF_LAEUFER = bei TP3 nur weiterlaufen, wenn Delta der letzten 3 geschlossenen Kerzen und seit Einstieg in Trade-Richtung zeigt.
- Kein Look-ahead: jede Entscheidung nur mit Kerzen/Delta, die vor der Minute geschlossen waren.

## Ergebnis (netto R, Kraken-Kosten, abgeschlossene Trades)
| Journal | Trades | mit TP2 | FEST | LAEUFER | LAEUFER_WEIT | OF_LAEUFER (Spot-Delta) |
|---|---:|---:|---:|---:|---:|---:|
| MID 1h | 9 | 3 | +3,71 | +3,82 | +3,66 | +3,82 |
| SHORT 15m | 17 | 1 | +0,77 | +0,77 | +0,10 | +0,77 |
| 30m (alt) | 23 | 2 | +0,15 | +0,20 | +0,11 | +0,20 |

Offen (noch nicht in den Summen): der MID-Long vom 04.11. (Einstieg 04:31, TP3 78.517 um 10:33).
Mit Läufer auf dem 1h-Swing läuft das letzte Drittel noch; bei 80.690 (16:35) wären es +3,02 R statt +2,07 R.
Auf dem 15m-Swing wäre derselbe Trade schon bei 78.305 ausgestoppt worden (schlechter als TP3).
Mit Protokollkosten (5/3/5 bps) gleiche Reihenfolge, alle Werte ~0,1 R je Trade tiefer.

## Einordnung
- Nur 7 verschiedene Trades erreichten TP2. Das ist kein Beleg, nur eine Richtung.
- Der Läufer hilft auf 1h, schadet auf 15m (enge Swings stoppen zu früh). Weiter (LAEUFER_WEIT) war bisher nicht besser.
- Orderflow-Filter: mit Spot-Delta sagte er bei 2 von 2 prüfbaren Fällen "weiterlaufen", beide Male richtig; mit Perp-Delta nur 1 Fall prüfbar (04.11.).
- Holdout 2025 nicht berührt (nur Live-Papierdaten ab 27.10.2026), Live-Trader unverändert.

## Vorschlag
Schatten-Journal neben dem MID-Journal: gleiche Einstiege, letztes Drittel als Läufer (1h-Swing) und als
Orderflow-Läufer, täglich neu gerechnet. Bewertung nach 30 Trades mit TP2, erst dann eine Regeländerung.
