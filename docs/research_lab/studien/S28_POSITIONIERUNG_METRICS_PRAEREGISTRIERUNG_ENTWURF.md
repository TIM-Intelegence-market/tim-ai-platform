# S28: Positionierung aus dem Binance-Metrics-Archiv: Erklärt sie etwas, was die bisherigen Indikatoren nicht erklären? (Präregistrierung, Entwurf)

| Feld | Wert |
|---|---|
| Studie | S28 (12.11.2026; S24 = alle Indikatoren, S26 = Aufwand gegen Ergebnis, S27 = größere Trades) |
| Version | **0.1, Entwurf.** Zähllauf als Code: `src/research_lab/studies/s28.py`, Tests `tests/test_research_lab_s28.py`. `evaluate` verweigert den Lauf, solange die Version mit 0 beginnt und ist noch nicht gebaut: es entsteht mit dem Einfrieren |
| Anlass | S24, S26 und S27 haben mit den vorhandenen Indikatoren auf BTC 1h keinen Edge gefunden. Uzi am 12.11.2026: „wie können wir diese Daten kriegen?“ und danach „S28“. Das Metrics-Archiv ist Gratis-Historie, die TIM bisher nur für Open Interest nutzt |
| Protokoll | `../PROTOKOLL.md` Version 1.3 |
| Daten | Binance USD-M `futures/um/daily/metrics` BTCUSDT, alle 5 Minuten, 2020-09-01 bis 2024-12-31; Kerzen wie S24 |
| Holdout | ab 2025-01-01, wird nicht geladen (die Dateien werden nur bis 2024-12-31 angefordert, der Speicher sperrt den Rest). Training 2020–2022, Validierung 2023–2024 |

## 1. Fragestellung

Haben Merkmale der Positionierung (Open Interest, Positionen der Top-Trader, Verhältnis der Taker-Käufe zu
Taker-Verkäufen) einen Zusammenhang mit dem Ergebnis des S27-Trades (Stop 3 ATR14, Ziel 6 ATR14, höchstens 168 h), der nach
Bitunix-Kosten übrig bleibt?

## 2. Neue Familie O

Drei Merkmale je Moment (jede geschlossene 1h-Kerze, Long und Short; Vorzeichen +1 Long, −1 Short):

| Merkmal | Definition |
|---|---|
| `oi_preis` | Vorzeichen × Vorzeichen der Preisänderung über 24 h × relative Änderung des Open Interest über 24 h |
| `top_ls` | Vorzeichen × ln(`sum_toptrader_long_short_ratio`) |
| `taker_ls` | Vorzeichen × ln(Mittel von `sum_taker_long_short_vol_ratio` der letzten 12 Stände, eine Stunde) |

**Kein Blick in die Zukunft:** Es zählen nur Stände, die mindestens 5 Minuten vor dem Kerzenschluss gestempelt sind. Das
Archiv sagt nicht, ob der Stempel Anfang oder Ende der 5 Minuten meint. Fehlt ein Stand (Lücke über 15 Minuten, auch der
Stand 24 h davor), ist das Merkmal leer und der Moment fällt aus der vollständigen Menge.

## 3. Was gleich bleibt

Das S27-Verfahren, ohne Suche: dieselben Momente, derselbe Trade, dieselben Kosten (Taker 0,06 %, Schlupf 0,03 %,
0,05 % mehr am Stop, Funding über die Haltedauer), dieselben Modelle M1 (Stimmen ±4) und M2 (logistische Regression,
einmal auf dem Training gefittet, oberes Drittel NEHMEN, unteres AUSLASSEN), Gate, Wochen-Block-Bootstrap, Holm,
Verschiebungstest und die sechs Bedingungen aus S27 Abschnitt 4. Der Unterschied ist nur die Merkmalsmenge:
**Variante A** nur Familie O, **Variante B** O zusammen mit den sechs S24-Familien. Holm läuft über beide Modelle in beiden
Varianten (m = 4).

## 4. Ablauf und Gate

1. `count` (ergebnisblind): vollständige Zeilen je Abschnitt und Richtung, Wochen. Gate wie S24: mindestens 300 je Richtung
   und Abschnitt, Validierung mindestens 50 Wochen. Der Zähllauf braucht die Tagesdateien (rund 1.580 kleine
   Downloads) und läuft auf der PS5.
2. Einfrieren als 1.0 auf Uzis Wort. Mit dem Einfrieren kommt `evaluate`.
3. `evaluate` auf der PS5.

## 5. Entscheidung (nur Validierung)

Wie S27: bestanden nur mit allen sechs Bedingungen, sonst „NO ROBUST EDGE PROVEN“.

## 6. Orderbuchtiefe: bewusst nicht Teil von S28

`bookDepth` (Bänder ±1 bis ±5 %) beginnt erst am 2023-01-01, also am ersten Tag der Validierung. Es gibt kein Training,
auf dem ein Modell gefittet werden dürfte. Die Tiefe bleibt Schatten-Merkmal und wird mit dem Bitunix-Recorder weiter
gesammelt. Die Liquidationen laufen als S12 (Gate 16.11.2026).

## 7. Was folgt

Bestanden: Live-Schatten am Mac (kein Handel, mindestens 4 Wochen), Schlusstest 2025 nur mit Uzis Wort. Nicht bestanden:
offen berichten, keine weiteren Varianten auf denselben Daten.

## 8. Grenzen

- Top-Trader-Verhältnis und Taker-Verhältnis sind Binance-Zahlen, nicht Bitunix.
- Die Dateien von 2020-09 bis 2021-11 wiederholen Zeilen und sind laut Datensatz-Hinweis nachträglich ergänzt worden; gleiche
  Wiederholungen werden zusammengefasst, widersprüchliche Zeilen brechen den Lauf ab.
- Familie O ist neu und wurde noch nie gegen Ergebnisse gelesen. Die Wahl der drei Merkmale beruht auf dem Spaltenaufbau
  der Datei, nicht auf einem Blick auf die Ergebnisse.
