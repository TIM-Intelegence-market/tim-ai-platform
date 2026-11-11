# S23: Alle Indikatoren zusammen: Sortiert ein Gesamt-Urteil aus allen Indikatoren mit Historie Standard-Trades nach ihrem Ergebnis? (Präregistrierung, Entwurf)

| Feld | Wert |
|---|---|
| Studie | S23 (nächste freie Nummer nach S22, 11.11.2026) |
| Version | **0.1, Entwurf.** Merkmal-Tabelle als Code: `src/research_lab/studies/s23.py`, Tests `tests/test_research_lab_s23.py`. Bisher nur `count` und `export` (ergebnisblind, kein Ergebnis wird berechnet). Das Modell (Abschnitt 4) kommt erst nach dem Einfrieren als 1.0 in den Code |
| Anlass | Uzi 11.11.2026: „richte TIM auf jeden Fall so ein, dass er wirklich alle Indikatoren nutzt, die wir haben“, „go“ auf den 4-Paket-Plan (Merkmal-Tabelle, Gesamt-Urteil, Live-Schatten, Schlusstest) |
| Protokoll | `../PROTOKOLL.md` Version 1.3 |
| Daten | Binance Spot BTCUSDT 1h und 30m (wie S22), USD-M Funding-Archiv, S8-Footprint-Speicher; 2019-10 bis 2024-12 |
| Holdout | ab 2025-01-01, wird nicht geladen. Training 2020–2022, Validierung 2023–2024 (Protokoll). Schlusstest 2025 nur einmal und nur mit Uzis ausdrücklichem Wort |
| Einordnung | Beobachtungsstudie mit hypothetischen Standard-Trades. Auch bei Bestehen kein Filter für Engine, Journale oder Echtgeld; nächster Schritt wäre nur der Live-Schatten (Abschnitt 7) |
| Abgrenzung | Momente und Trades sind die von S22, unverändert. S22 prüft nur R1–R5; S23 fragt, ob **alle** Familien zusammen mehr sortieren. S21 (K/F/G am Flip) und OFX (Einstiegsmodelle) werden nicht wiederholt, ihre Merkmale werden nur wiederverwendet |

## 1. Fragestellung

Jede geschlossene 1h-Kerze ist ein Moment; je Moment ein Long und ein Short zum Schlusskurs, Stop 1 ATR14, Ziel
2 ATR14, höchstens 48 Stunden (S22, Abschnitt 1). Für jeden Trade hält S23 alle Indikatoren fest, die sich mit dem
Stand zum Schlusszeitpunkt aus der Historie bauen lassen. Frage: Trennt ein Gesamt-Urteil daraus gute von
schlechten Trades, und zwar nach realistischen Bitunix-Kosten?

## 2. Merkmale (Stand zum Schluss der Kerze, Vorzeichen: über 0 spricht für die Richtung des Trades)

| Familie | Merkmale | Quelle |
|---|---|---|
| C Chart-Urteil | R1 Value-Rand, R2 Struktur 1h/4h, R3 Stop hinter Strong Low/High, R4 Level vor dem Ziel, R5 Trendlinie (je −1/0/+1) | `chart_verdict` unverändert, wie S22 |
| K Kerzen-Orderflow | CVD-Anteil der letzten 10 h, Gleichlauf CVD/Kurs, Volumentrend | S21 Familie K |
| F Footprint | Flags I/A/C/T/H/E der 8 Viertelstunden bis zum Schluss | S8-Speicher, S21 Familie F |
| G Funding | letzte Rate, z-Wert über 90 Raten (über 0 = diese Seite zahlt schon) | S21 Familie G |
| T Richtung | Tag, Woche, Monat: letzter abgeschlossener Schluss über/unter dem Mittel (20/10/3) | OFX-Richtungsfilter `ofx.trend` |
| V VWAP | Abstand zum 24h-VWAP und zum Wochen-VWAP (ab Montag 00:00 UTC), in ATR | neu, aus 1h-Kerzen |

**Ohne Historie, nur im Live-Schatten (Paket 3):** Orderbuch, Liquidationen (seit 02.11.2026), Open Interest (kein
Archiv), Gamma/Optionen, Kronos (eigene Studie S18), Chart-Urteil R6–R8 (Absorption, Welle, Tages-CVD),
Bitunix-Trades (Recorder seit 11.11.2026).

## 3. Kosten

Bitunix-Taker 0,06 % je Seite plus Schlupf 0,03 % je Seite und 0,05 % zusätzlich beim Stop (wie OF2 und die
Bitunix-Rechnung aus PR #226). Funding wird über die Haltedauer mit der jeweils veröffentlichten Rate verrechnet.
Netto-R = Brutto-R minus Kosten geteilt durch das Risiko (1 ATR).

## 4. Modelle (vor dem Einfrieren festzulegen, hier der Vorschlag)

Zwei Modelle, beide nur mit vollständigen Zeilen (alle geladenen Familien vorhanden):

- **M1 Stimmen (nichts angepasst):** Jedes Merkmal gibt eine Stimme mit seinem Vorzeichen, nach vorher
  festgelegter Lesart: C, K-Anteil, F, T, V mit dem Trade; G gegen den Trade (zahlende Seite = überfüllt).
  Gleichlauf und Volumentrend stimmen nicht ab. Score = Summe; NEHMEN ab +4, AUSLASSEN ab −4, sonst NEUTRAL.
- **M2 Logistische Regression:** Ziel Netto-R > 0. Merkmale auf dem Training standardisiert, L2-Strafe λ = 1,
  einmal auf dem Training geschätzt, danach eingefroren. NEHMEN = vorhergesagte Wahrscheinlichkeit im obersten
  Drittel der Trainingswerte, AUSLASSEN = unterstes Drittel. Die Schwellen kommen aus dem Training.

## 5. Ablauf und Gate

1. `count` (ergebnisblind): Abdeckung je Familie und Abschnitt. Gate: je Abschnitt und Richtung mindestens 300
   vollständige Zeilen, Validierung mindestens 50 Wochen.
2. Einfrieren als 1.0 auf Uzis Wort (Modelle, Schwellen, Kosten, Tests unverändert danach).
3. `evaluate` auf der PS5: M2 einmal auf dem Training geschätzt, beide Modelle auf der Validierung bewertet.

## 6. Hypothesen und Entscheidung (nur Validierung 2023–2024)

- **H1 (M1), H2 (M2):** Mittel Netto-R NEHMEN minus AUSLASSEN > 0. Wochen-Block-Bootstrap (4 Wochen, 9.999 Ziehungen),
  Holm über 2 Hypothesen, α = 0,05.
- Ein Modell besteht nur, wenn zusätzlich: Abstand ≥ 0,05 R; dasselbe Vorzeichen im Training; Verschiebungstest
  (199 Verschiebungen um mindestens zwei Wochen) p < 0,05; **NEHMEN im Mittel positiv nach Kosten**.
- Ergänzend, ohne Test: Mehrwert gegenüber S22 allein (Familie C) und Beitrag je Familie (für den Bericht).

## 7. Was folgt

- **Bestanden:** Live-Schatten am Mac mit allen Familien, auch den nur-live-Quellen, mindestens 4 Wochen und
  30 geschlossene Pläne, ohne zu handeln. Danach Schlusstest 2025 einmal, nur mit Uzis Wort.
- **Nicht bestanden:** offen berichten („NO ROBUST EDGE PROVEN“); keine Nachsuche mit anderen Schwellen auf
  denselben Daten.

## 8. Grenzen

- Standard-Trades (1 ATR / 2 ATR / 48 h) sind kein OF2-Einstieg; S23 prüft, ob die Indikatoren sortieren, nicht
  eine fertige Strategie.
- Footprint und Funding gibt es erst ab 2020; der Vorlauf vor dem ersten Moment liegt in 2019.
- Indikatoren ohne Historie können hier nicht geprüft werden (Abschnitt 2).
