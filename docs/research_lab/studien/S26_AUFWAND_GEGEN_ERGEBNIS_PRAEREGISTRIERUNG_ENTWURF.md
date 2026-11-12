# S26: Aufwand gegen Ergebnis: Sortieren Absorption, Initiative und Book Sweep einer 1h-Kerze Standard-Trades? (Präregistrierung, Entwurf)

| Feld | Wert |
|---|---|
| Studie | S26 (11.11.2026; S23 = Open Interest am Flip, S24 = alle Indikatoren, S25 = GARCH-Größe) |
| Version | **0.1, Entwurf.** Regeln als Code: `src/research_lab/studies/s26.py`, Tests `tests/test_research_lab_s26.py`. `evaluate` verweigert den Lauf, solange die Version mit 0 beginnt |
| Anlass | Uzi 11.11.2026: Zusammenfassung des Videos „The Only Orderflow Guide You'll Ever Need“ (Aufwand gegen Ergebnis), „go“ auf den Vorschlag, das als eigene Kennzahl zu prüfen |
| Protokoll | `../PROTOKOLL.md` Version 1.3 |
| Daten | Binance Spot BTCUSDT 1h (Taker-Kaufvolumen je Kerze), USD-M Funding-Archiv; 2019-10 bis 2024-12 |
| Holdout | ab 2025-01-01, wird nicht geladen. Training 2020–2022, Validierung 2023–2024 |
| Abgrenzung | Momente, Trades und Kosten wie S22/S24 (Stop 1 ATR, Ziel 2 ATR, 48 h, Bitunix-Taker 0,06 %, Schlupf, Funding). S24 enthält Delta nur als Anteil über 10 Stunden; S26 prüft die Muster der einen gerade geschlossenen Kerze. Die Footprint-Familien aus S19 werden nicht wiederholt |

## 1. Fragestellung

Das Video beschreibt drei Lesarten von Aufwand (Volumen, Delta) gegen Ergebnis (Körper, Schlusslage, Spanne):
Absorption (viel Aufwand, kein Ergebnis, Gegenbewegung), Initiative (Aufwand und Ergebnis passen, Fortsetzung),
Book Sweep (wenig Aufwand, großer Weg, dünnes Buch). Sind Trades in Richtung dieser Lesart nach Kosten besser als
die übrigen?

## 2. Regeln (fest, nichts angepasst; für Long, Short gespiegelt)

Basis: Volumen der Kerze gegen den Median der 24 Kerzen davor (`vol_rel`), Delta-Anteil = (Taker-Kauf − Taker-Verkauf)
/ Volumen, Schlusslage in der Spanne (0 = Tief, 1 = Hoch), Körper und Spanne in ATR14.

| Muster | Bedingung (Long) | Lesart |
|---|---|---|
| ABSORPTION | Delta-Anteil ≤ −0,10, `vol_rel` ≥ 1,5, Schluss in der oberen Hälfte | Verkäufer aufgenommen → Long |
| INITIATIVE | Delta-Anteil ≥ +0,10, `vol_rel` ≥ 1,5, Schluss im obersten Viertel, Körper ≥ 0,5 ATR | Käufer haben Kontrolle → Long |
| SWEEP | Spanne ≥ 1,5 ATR, `vol_rel` ≤ 0,8, Körper aufwärts | dünnes Buch nach oben → Long |

Die Schwellen sind vor jedem Blick auf Daten gesetzt (runde Werte aus der Beschreibung im Video, keine Suche).

## 3. Ablauf und Gate

1. `count` (ergebnisblind): Treffer je Muster, Abschnitt und Richtung. Gate je Muster: mindestens 200 Treffer in
   Training und Validierung, Validierung mindestens 50 Wochen. Ein Muster unter dem Gate wird nicht getestet.
   Zähllauf 0.1 (PS5, 11.11.2026 22:30, ergebnisblind): Training ABSORPTION 307, INITIATIVE 616, SWEEP 11;
   Validierung 307 / 666 / 19 (106 Wochen). SWEEP liegt weit unter dem Gate und wird mit diesen Regeln nicht getestet.
2. Einfrieren als 1.0 auf Uzis Wort.
3. `evaluate` auf der PS5.

## 4. Hypothesen und Entscheidung (nur Validierung)

Je Muster H: Mittel Netto-R der Trades mit Muster minus ohne Muster > 0. Wochen-Block-Bootstrap (4 Wochen, 9.999
Ziehungen), Holm über 3, α = 0,05. Ein Muster besteht nur zusätzlich mit: Abstand ≥ 0,05 R, gleiches Vorzeichen im
Training, Verschiebungstest p < 0,05, Trades mit Muster im Mittel positiv nach Kosten. Sonst „NO ROBUST EDGE PROVEN“.

## 5. Was folgt

Bestanden: Muster als Merkmal in den Live-Schatten (kein Handel), danach Schlusstest 2025 nur mit Uzis Wort.
Nicht bestanden: offen berichten, keine Nachsuche mit anderen Schwellen.

## 6. Grenzen

- Delta aus Binance-Spot-Kerzen (Taker-Kaufvolumen), nicht aus dem Bitunix-Buch.
- „Weg des geringsten Widerstands“ braucht das Orderbuch; das hat TIM nicht und wird hier nicht geprüft.
- Eine Kerze ist eine grobe Einheit; Footprint je Preisstufe bleibt S19/S24 vorbehalten.
