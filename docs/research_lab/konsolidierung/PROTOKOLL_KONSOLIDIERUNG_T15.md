# Zusatzprotokoll T15 zur Konsolidierung (Version 1.1-T15)

Eingefroren am 16.11.2026 vor dem Laden und vor jeder Auswertung der hier genannten Daten. Dieses Zusatzprotokoll ergänzt `PROTOKOLL_KONSOLIDIERUNG.md` 1.0 (eingefroren, sha256 siehe `ergebnisse/PROTOKOLL_STAND.json`). Es ändert **keines** der Kriterien G1 bis G11, CG1, CG2 und keine Urteilsstufe. Die Ergebnisse T1 bis T13 lagen beim Einfrieren vor (Gesamturteil Stufe 2); T15 wird deshalb nicht als Auswahl nach Ergebnis verwendet, sondern als zusätzliche Prüfung außerhalb des Entwicklungszeitraums.

## 1. Frage

Hält die Trendregel in einem Zeitraum, der weder zur Entwicklung noch zu Training oder Validierung der Regel gehörte? Geprüft wird der Kandidat C3 (die C1-Regel S7b-D20-T3, unverändert, nur auf BTC und ETH).

## 2. Daten (nur diese)

- Binance **Spot** 4h-Kerzen, BTCUSDT und ETHUSDT, Monatsarchive 2017-08 bis 2019-12 von `data.binance.vision`, Prüfsummen laut der zugehörigen `.CHECKSUM`-Dateien.
- Spot ist Stellvertreter für den Perpetual: Die USD-M-Futures starten erst im September 2019, Funding gibt es erst ab diesem Zeitpunkt. Abweichungen (Basis, Funding, Leerverkauf, Liquidationen) sind Einschränkungen und werden berichtet.
- SOL existiert in diesem Zeitraum nicht. Daher wird C3 geprüft (BTC vor ETH bei gleichem Zeitstempel), nicht C1 und nicht C2.
- Der Zeitraum ist nicht der versiegelte Holdout (ab 2025-01-01). Der Lader verweigert weiterhin Daten ab 2025-01-01.
- Keine Daten außerhalb dieser Liste, keine Anpassung der Zeitspanne nach Sicht auf Ergebnisse.

## 3. Regel und Kosten (unverändert aus T1 bis T13)

- Regel: Donchian-Kanal 20, Einstieg in Richtung des SMA200, ATR14-Stop (1,5 × ATR14, mindestens 1 % des Schlusskurses), Ziel 3 R, Zeitstopp 30 Kerzen, höchstens eine Position über beide Symbole. Derselbe Code wie in T1 bis T13 (`s7b_nachrechnung.py`), keine Parameteränderung.
- Primäre Kosten: **K2** (Gebühr 0,06 %, Schlupf 0,06 % je Seite, Stop-Schlupf 0,10 %), Funding **aus**, weil für 2017 bis August 2019 keine Funding-Historie existiert. K2 ist das Kostenszenario des Kriteriums G2.
- Berichtet: K1 (Bitunix-Basis), K0 (Protokollkosten).
- **Funding-Sensitivität (vorab festgelegt):** vom primären E[R] wird der mittlere Funding-Kostenanteil je Trade abgezogen, den dieselbe Regel (C3) unter K2 mit Funding ohne Gutschrift im Zeitraum 2020 bis 2024 hatte. Das Ergebnis dieser Rechnung wird zusammen mit T15 ausgewiesen; es ersetzt P1 nicht.

## 4. Datenprüfung (vor der Simulation, eigener Bericht)

Vor dem Handelslauf wird ein Datenbericht geschrieben und festgehalten: Anzahl Monatsdateien je Symbol (erwartet 29), Prüfsummen, Kerzenzahl gegen erwartete Zahl im 4h-Raster, Lücken, Duplikate, ungültige Kerzen (High unter Low, nichtpositive Preise), erste und letzte Kerze. **Abbruchregel:** Fehlt mehr als 5 % der erwarteten 4h-Kerzen eines Symbols, oder weicht eine Prüfsumme ab, oder fehlt ein Monat, so wird T15 nicht ausgewertet und der Befund berichtet.

## 5. Kriterien

- **P1 (primär, einziges Bestehenskriterium):** E[R] je Trade unter K2 (Funding aus) ist größer als 0, **und** der einseitige Monatsblock-Bootstrap-p-Wert (Anteil der 10 000 Ziehungen ganzer Kalendermonate mit Mittel ≤ 0, Seed 20261116, Trades gehören dem Monat ihres Signals) ist höchstens 0,05.
- Nur berichtet, ohne Schwelle: P2 E[R] unter K1 und K0; P3 Zufallseinstiege in SMA200-Richtung (1 000 Ziehungen, wie T3, p-Wert); P4 E[R] und n je Jahr (2017, 2018, 2019); P5 größter Rückgang in R; P6 Funding-Sensitivität (siehe oben); P7 Trefferquote, Profitfaktor, mittlere Gewinne und Verluste, Wilson-Intervall der Trefferquote; P8 Ergebnis je Instrument.
- Genau **ein** Lauf. Kein Parameter, keine Kosten und kein Kriterium wird nach Sicht auf das Ergebnis geändert. Ein Fehlschlag wird berichtet wie ein Erfolg.

## 6. Einordnung des Ergebnisses (vorab)

- **bestätigt** (P1 erfüllt): Die Trendregel zeigt auf BTC und ETH auch im Zeitraum 2017-08 bis 2019-12 eine positive Netto-Erwartung. Das füllt die Evidenzstufe „außerhalb der Entwicklung bestätigt“ für diese beiden Coins, **nicht** für andere Märkte. G7 (Mehrfachtest) und G8 (Übertragung auf andere Coins, nicht bestanden) bleiben bestehen; das Gesamturteil nach Protokoll Abschnitt 5 ändert sich dadurch nicht.
- **nicht bestätigt, Richtung positiv** (E[R] > 0, p > 0,05): kein Nachweis, aber auch keine Widerlegung. Die Aussagekraft ist begrenzt, siehe Abschnitt 7.
- **nicht bestätigt, Richtung negativ** (E[R] ≤ 0): Die Regel hat außerhalb des Entwicklungszeitraums keine positive Erwartung gezeigt. Das wird als Gegenbeleg in die Evidenzmatrix aufgenommen.
- Das Ergebnis wird in jedem Fall in `KONSOLIDIERTE_STUDIE.md` und in der Evidenzmatrix berichtet.

## 7. Aussagekraft (vorab, Schätzung)

Erwartet werden etwa 195 Trades (rund 27 Monate × 7,2 Trades je Monat; so viele hatte C3 auf BTC und ETH in 2020 bis 2024, T7). Mit einer Streuung von 1,73 R je Trade und einem einseitigen Test zum Niveau 5 % hat der Test bei einer wahren Erwartung von +0,24 R eine Power von etwa 62 %, und die kleinste bei 80 % Power nachweisbare Erwartung liegt bei etwa +0,31 R. Ein negatives oder unklares Ergebnis schließt einen kleineren Vorteil also nicht aus.

## 8. Einschränkungen, die vorab feststehen

- Spot statt Perp, Funding fehlt, Leerverkäufe sind als Perp-Short simuliert.
- Nur zwei Coins, beide im Nachhinein als Handelsobjekte gewählt (Survivorship), und beide mit starker Wechselkorrelation.
- Das Marktumfeld 2017 bis 2019 (Blase 2017, Rückgang 2018, Erholung 2019) ist ein anderes Regime als 2020 bis 2024; das ist der Zweck des Tests, macht aber eine Übertragung auf die Gegenwart nicht sicher.
- Allgemeines Vorwissen über die Preisgeschichte lässt sich nicht ausschließen; die Regelparameter wurden aber nicht auf diesen Daten bestimmt.

## 9. Ablage

Code: `src/research_lab/konsolidierung/t15_ausserhalb.py`. Ergebnisse: `ergebnisse/t15_datenaudit.json` (vor dem Lauf), `ergebnisse/t15_ausserhalb.json`. Testlog: `TESTLOG.md`. Rohdaten werden nicht ins Repository gelegt; die Prüfsummen stehen im Datenbericht.
