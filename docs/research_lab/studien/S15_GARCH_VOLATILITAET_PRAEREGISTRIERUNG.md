# S15: GARCH(1,1)-Volatilitätsprognose gegen die 14-Tage-Varianz (Präregistrierung, Entwurf)

| Feld | Wert |
|---|---|
| Studie | S15 (nächste freie Nummer nach S14, 02.11.2026) |
| Version | **1.0, eingefroren am 02.11.2026 nach Uzis Einordnung (19:14 Uhr). Eingefrorener Code: Commit `3bf6f80` (`src/research_lab/studies/s15.py`, Skript `scripts/research_lab_s15.py`, Tests `tests/test_research_lab_s15.py`). Zähllauf bestanden. Nichts registriert, kein Fehlermaß für S15 gesehen** |
| Anlass | Uzi 02.11.2026 („go“ auf den Vorschlag aus der Auswertung des Accounts quantfinancetogo, `/mnt/project-files/analysen/quantfinancetogo-2026-11-02/bericht.md`, Teil 39 und Video „GARCH Model Explained“) |
| Quelle der Regeln | Bollerslev (1986, GARCH), Engle (1982, ARCH), RiskMetrics (1996, EWMA λ = 0,94), Patton (2011, QLIKE als robustes Fehlermaß bei verrauschter Ziel-Varianz), Diebold und Mariano (1995), Newey und West (1987/1994, Lag-Regel). Alle Zahlen unten sind vorab gesetzt und werden nicht optimiert |
| Protokoll | `../PROTOKOLL.md` Version 1.3: Datensplit (Training bis 2022, Validierung 2023–2024, Holdout ab 2025 nie geladen) |
| Einordnung | **Prognosestudie ohne Registerplatz** (Uzi per Karte 02.11.2026, 19:14 Uhr; `../PROTOKOLL.md` Eintrag 2026-11-02). S15 erzeugt keine Trades und kein Handelssignal, es wird nur die Güte einer Schwankungsprognose verglichen. Register bleibt 58/60, der Holdout ab 2025 wird nie geladen |

## 1. Fragestellung

Sagt ein GARCH(1,1)-Modell die Schwankung (Varianz) der nächsten 4 Stunden bzw. des nächsten Tages bei BTC, ETH und SOL besser voraus als die einfache Varianz der letzten 14 Tage?

Nutzen für TIM: Eine bessere Schwankungsprognose kann 1 R, Stop-Abstände und Positionsgrößen sauberer setzen (Risikoschicht P4 aus der Lückenanalyse vom 01.11.). S15 prüft **keinen** Gewinn-Edge.

## 2. Was TIM schon hat und Vorbelastung

- Klines 5m BTC/ETH/SOL USD-M 2020–2024 auf dem Mac (Datensatz aus S10, `data.binance.vision`, Prüfsummen), wie in S14 genutzt.
- TIM nutzt Schwankung bisher als einfache Fensterwerte (z. B. S13: σ über 14 Vortage). Ein GARCH-Modell gibt es in TIM noch nicht (Suche nach „garch“ im Code ohne Treffer).
- **Vorbelastung:** Gesehen sind nur das Video und Allgemeinwissen. Danach haben Krypto-Renditen Schwankungsballung, und GARCH-artige Modelle schlagen in der Literatur einfache Fenster oft, aber nicht immer. EWMA ist dabei häufig gleich gut. Für S15 wurden keine Kurse ausgewertet.

## 3. Daten

- Instrumente BTCUSDT, ETHUSDT (ab 2020-01), SOLUSDT (ab 2020-09), USD-M, 5m-Klines bis 2024-12.
- **Perioden:** 4h (S15-4h) und 1 Tag (S15-1d), ausgerichtet an UTC (00:00, 04:00, …). Eine Periode zählt nur, wenn alle 5m-Kerzen da und lückenlos sind (48 bzw. 288). Unvollständige Perioden fallen weg, die Reihe läuft über die vorhandenen Perioden weiter (wird im Bericht als Anzahl genannt).
- **Rendite der Periode:** r_t = 100 · ln(Schluss / Eröffnung) in Prozent, ohne Mittelwert (Null-Mittelwert-Annahme).
- **Ziel (realisierte Varianz):** RV_t = Summe der quadrierten 5m-Log-Renditen in der Periode (in Prozent²). Die erste 5m-Rendite ist ln(Schluss/Eröffnung) der ersten Kerze.
- Abschnitt einer Prognose = Abschnitt des Periodenstarts. Training: Start vor 2023-01-01, Validierung: 2023-01-01 bis 2024-12-31. Der Holdout wird nicht geladen.

## 4. Modelle (vorab festgelegt)

Jede Prognose für Periode t nutzt nur Perioden vor t.

| Modell | Regel | Rolle |
|---|---|---|
| **B1 14-Tage-Varianz** | Mittelwert von r² über die letzten 84 (4h) bzw. 14 (1d) vorhandenen Perioden, also 14 Tage, solange keine Periode fehlt | Vergleichsmaßstab (heutiger TIM-Stil) |
| **B2 EWMA** | h_t = 0,94 · h_{t−1} + 0,06 · r²_{t−1}, Start mit dem Mittelwert von r² der ersten 14 Tage | nur beschreibend |
| **G GARCH(1,1)** | h_t = ω + α · r²_{t−1} + β · h_{t−1} | geprüftes Modell |

GARCH-Schätzung:

1. Gauß-Quasi-Maximum-Likelihood auf allen Perioden vor dem Schätzzeitpunkt (wachsendes Fenster), Startvarianz = Mittelwert von r² dieser Daten. Nebenbedingungen ω > 0, α, β ≥ 0, α + β < 0,9999 (über Transformation).
2. Optimierer: deterministischer Nelder-Mead (höchstens 400 Auswertungen), Start bei ω = 0,05 · Varianz, α = 0,10, β = 0,85, danach warm von der letzten Schätzung.
3. **Einlaufzeit:** Die ersten 365 · (Perioden je Tag) vollständigen Perioden des Coins (also 365 Tage, solange keine Periode fehlt) dienen nur der Schätzung. Die erste ausgewertete Prognose ist die nächste Periode, für alle drei Modelle gleich. Fehlende Perioden verschieben den Beginn nach hinten; ihre Zahl steht im Zähllauf.
4. **Neuschätzung alle 30 Tage** an Perioden (180 bei 4h, 30 bei 1d). Nach jeder Neuschätzung wird die Rekursion mit den neuen Werten über alle früheren Perioden neu gerechnet.

## 5. Erfolgskriterien

Fehlermaß **QLIKE** = RV/h − ln(RV/h) − 1 (Patton 2011, robust gegen das Rauschen von RV). Perioden mit RV = 0 oder einer Prognose ≤ 0 werden ausgelassen und im Bericht gezählt.

Differenz je Periode d = QLIKE(B1) − QLIKE(G), d > 0 heißt GARCH ist besser. **Gepoolt** wird als Mittelwert über die drei Coins je Periodenstart (so zählt ein gemeinsamer Marktschock nicht dreifach). Test: Diebold-Mariano mit Newey-West-Varianz, Lag = ⌊4 · (n/100)^(2/9)⌋, p einseitig aus der Normalverteilung.

Eine Variante (S15-4h, S15-1d) **besteht**, wenn alle Punkte erfüllt sind:

| # | Kriterium |
|---|---|
| 1 | Training: ≥ 500 gepoolte Perioden, Ø d > 0, p < 0,10 |
| 2 | Validierung: ≥ 250 gepoolte Perioden, Ø d > 0, p < 0,05 |
| 3 | Validierung: Ø d > 0 bei mindestens 2 von 3 Coins (je Coin über seine eigenen Perioden) |
| 4 | Validierung: Ø gepooltes d > 0 in jedem Kalenderjahr; 2023 und 2024 müssen beide vorhanden sein |

Die zwei Varianten werden getrennt bewertet. Es gibt keine Korrektur fürs Vielfachtesten, weil keine Variante ausgewählt und gehandelt wird. Beide Ergebnisse werden berichtet.

### 5.1 Machbarkeits-Gate (vor jedem Ergebnis)

Ergebnisblinder Zähllauf (`scripts/research_lab_s15.py count`): nur die Zahl vollständiger Perioden nach der Einlaufzeit je Abschnitt, keine Prognose und kein Fehlermaß. Eine Variante wird nur ausgewertet, wenn sie gepoolt im Training ≥ 500 und in der Validierung ≥ 250 Perioden hat; das Auswerteskript rechnet für eine Variante unter dem Gate keine Fehlermaße. Das Gate wird nicht gelockert.

### 5.2 Beschreibend, ohne Urteil

- GARCH gegen EWMA (B2) mit demselben Test, dazu beide Vergleiche (gegen B1 und B2) auch mit MSE statt QLIKE.
- Geschätzte α, β, Persistenz α + β und Halbwertszeit eines Schocks je Neuschätzung.
- **Vorab festgelegte Lesart:** Besteht GARCH gegen B1, liegt aber gegen EWMA nicht bei p < 0,05 vorn, empfiehlt der Bericht EWMA als einfachere Wahl für TIM. Besteht GARCH nicht gegen B1, bleibt TIM bei der 14-Tage-Varianz.

## 6. Was danach käme (nicht Teil von S15)

Eine bestandene Variante ändert nichts automatisch. Ob TIM die Prognose für 1 R, Stops oder Positionsgrößen nutzt, wäre ein eigener Schritt mit eigener Freigabe, zuerst im Papier.

## 7. Bis zur Erstellung gesehene Daten

Für S15 wurden keine Kurse ausgewertet. Gesehen sind nur das Video und das in Abschnitt 2 genannte Allgemeinwissen. Die Tests nutzen nur synthetische Daten.

### 7.1 Zähllauf 5.1 (02.11.2026, ergebnisblind)

Bericht `../reports/s15_count_2026-11-02T1720Z.md` (Commit `a6dafaa`, Datensatz-Hash `182b222e…`, auf dem Mac). Gezählt wurden nur vollständige Perioden nach der Einlaufzeit, keine Prognose und kein Fehlermaß.

| Variante | Training gepoolt | Validierung gepoolt | BTC / ETH / SOL Training | BTC / ETH / SOL Validierung | Gate |
|---|---:|---:|---:|---:|---|
| S15-4h | 4386 | 4386 | 4386 / 4386 / 2812 | 4386 / 4386 / 4386 | bestanden |
| S15-1d | 731 | 731 | 731 / 731 / 468 | 731 / 731 / 731 | bestanden |

Im Datensatz fehlt keine Periode (BTC und ETH je 1827 Tage, SOL 1564 Tage, alle vollständig). Die Einlaufzeit endet damit genau 365 Tage nach Datenbeginn.

## 8. Offene Punkte vor Version 1.0

1. ~~Einordnung~~ entschieden: Prognosestudie ohne Registerplatz (Uzi 02.11.2026).
2. ~~Zähllauf 5.1 auf dem Mac~~ erledigt (7.1).
3. ~~Einfrieren~~ erledigt (1.0, Commit `3bf6f80`). Danach ein Lauf mit Fehlermaß auf dem Mac (`python scripts/research_lab_s15.py run`).

## Änderungsprotokoll

- 0.1 (02.11.2026): Entwurf auf Uzis „go“. Regeln als Code, Zähl- und Auswerteskript, 10 Tests auf synthetischen Daten. Nichts registriert, keine Marktdaten ausgewertet.
- 0.2 (02.11.2026): Zähllauf eingetragen (7.1), beide Varianten bestehen. Nach unabhängiger Prüfung präzisiert, alles vor jedem Ergebnis: Einlaufzeit und B1 zählen vorhandene Perioden (4.3, Tabelle 4); Kriterium 4 verlangt beide Jahre und nutzt das gepoolte d; ausgelassene Perioden werden gezählt; das Gate wird im Auswerteskript erzwungen; MSE auch gegen EWMA. Weiter kein Fehlermaß gesehen.
- 1.0 (02.11.2026): Einordnung Prognosestudie ohne Registerplatz (Uzi), Regeln und Code mit Commit `3bf6f80` eingefroren. Kein Fehlermaß gesehen.
