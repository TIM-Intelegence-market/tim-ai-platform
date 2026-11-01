# S13: Noise-Band-Ausbruch (Intraday-Momentum) für BTC/ETH/SOL (Präregistrierung, Entwurf)

| Feld | Wert |
|---|---|
| Studie | S13 (nächste freie Nummer laut `workshop.generator.next_study_id`, 01.11.2026) |
| Version | **0.2 – Entwurf. Original gelesen, Regeln als Code (`src/research_lab/hypotheses/s13.py`, Tests `tests/test_research_lab_s13.py`), noch nicht eingefroren. Nichts registriert, keine Kurse für S13 ausgewertet** |
| Anlass | Uzi 01.11.2026 („go“ auf den Vorschlag aus der Reel-Auswertung): `/mnt/project-files/analysen/reels-chris-2026-11-01/bericht.md`, Punkt 1 |
| Quelle der Regeln | Zarattini, Aziz, Barbon (2024): „Beat the Market: An Effective Intraday Momentum Strategy for S&P500 ETF (SPY)“, SSRN 4824172 / Swiss Finance Institute RP 24-97. Original gelesen am 01.11.2026 (Fassung der Universität St. Gallen, Alexandria); Abgleich und Abweichungen in Abschnitt 4.6 |
| Anlass-Quelle | Zwei Instagram-Reels von @AlgorithmicTrading („Noise Band“, Oktober 2026): NQ/ES ab 2018, nach eigener Aussage breiteres Band als die Studie, sechs Walk-Forward-Tests, 2 000 Läufe auf gemischten Daten, Drawdown 30 %, Trefferquote ~50 %. Werbung für eigenen Kanal, kein Code gesehen |
| Protokoll | `../PROTOKOLL.md` Version 1.3, Kriterien K1–K5 unverändert |
| Holdout | ab 2025-01-01, wird nur mit Uzis ausdrücklichem Wort geladen |

## 1. Fragestellung

Bricht der Preis von BTC/ETH/SOL-Perpetuals zu festen Halbstunden-Zeitpunkten aus dem „Noise Band“ aus (die übliche Bewegung seit dem Tagesanker zu dieser Tageszeit, gemessen über die letzten 14 Tage), läuft die Bewegung dann im Mittel bis Sitzungsende weiter? Mit einem Ausstieg über ein nachgezogenes Band bzw. VWAP und nach allen Kosten: Hat das einen positiven Erwartungswert, der sich von zufälligen Einstiegen zu denselben Zeitpunkten unterscheidet?

## 2. Was TIM schon hat und Vorbelastung

- Klines 1m/5m BTC/ETH/SOL 2020–2024 auf dem Mac (Datensatz aus S10, `data.binance.vision`, Prüfsummen), NYSE-Kalender `src/research_lab/hypotheses/calendars.py`, Kostenmodell Protokoll 4.4, Zufallsvergleich 7.1, Runner `src/research_lab/runner.py`.
- **Umsetzung (0.2):** Die Engine bleibt unverändert. Der nachgezogene Stop läuft über ihre vorhandene Ausstiegsregel (`Signal.exit_rule`, Ausstieg zur Eröffnung der nächsten Kerze), der Katastrophen-Stop ist der feste Stop der Engine. Band, σ, VWAP und Prüfzeitpunkte stehen in `src/research_lab/hypotheses/s13.py`, der Zähllauf in `scripts/research_lab_s13.py count`.
- **Vorbelastung:**
  - S7 (Trendfolge-Ausbruch, BTC/ETH/SOL) scheiterte in der Validierung an K4 (Drawdown).
  - S10 (IB-Ausbruch nach NY-Open) endete am Machbarkeits-Gate, weil es zu selten Signale gab. Die Zählung ergab, dass an rund 70 % der NYSE-Tage die erste halbe Stunde schmaler als 0,25 Tages-ATR war. Das ist ergebnisblind, sagt aber etwas über die Spanne nach 09:30.
  - Gesehen ist außerdem die Behauptung der Studie: hohe Rendite auf SPY 2007–2024. Die Zahlen sind nicht geprüft, und sie gelten für Aktien-ETFs, nicht für Krypto.
  - S13 unterscheidet sich von S7 und S10 durch drei Punkte: Die Schwelle hängt von der Tageszeit ab, statt einer festen Range. Der Einstieg erfolgt nur zu Halbstunden-Zeitpunkten. Der Ausstieg ist ein nachgezogenes Band, kein festes Ziel.

## 3. Daten

- USD-M-Perpetuals BTCUSDT, ETHUSDT, SOLUSDT (`protocol.UNIVERSE`), Klines 1m, Funding je 8 h.
- Training 2020–2022, Validierung 2023–2024 (SOL ab erstem vollständigem Perpetual-Monat). Die ersten 14 Tage jedes Instruments dienen nur als Vorlauf.
- VWAP aus 1m-Kerzen: typischer Preis (H+L+C)/3 mal Volumen, kumuliert ab Anker. Kein Tick-VWAP.

## 4. Regeln

### 4.1 Tagesanker (zwei Varianten, vorab festgelegt)

| Variante | Anker (Sitzungsbeginn) | Sitzungsende | Handelstage | „Vortagesschluss“ C₋₁ |
|---|---|---|---|---|
| **S13-NY** | 09:30 America/New_York | 16:00 New York | NYSE-Handelstage (`calendars.nyse_holidays`) | Schluss der 1m-Kerze bis 16:00 des vorigen NYSE-Tags |
| **S13-UTC** | 00:00 UTC | 23:30 UTC (letzte Prüfung 23:00) | jeder Kalendertag | = Anker-Eröffnung (durchgehender Handel, keine Lücke) |

Warum zwei Anker: Der Mechanismus der Studie (Absicherungsflüsse von Händlern und gehebelten ETFs bis Handelsschluss) gehört zu US-Aktien. Ob er bei Krypto über die US-Sitzung wirkt (NY) oder ob der Kalendertag reicht (UTC), ist offen. Weitere Anker werden nicht getestet.

### 4.2 Noise Band

1. O = Eröffnungskurs der ersten 1m-Kerze ab Anker. Für jede Minute m seit Anker: Bewegung_d(m) = |C_d(m) / O_d − 1|.
2. σ(m) = einfacher Mittelwert von Bewegung_d(m) über die **14 vorherigen** Handelstage der Variante (heute nicht enthalten).
3. Oberes Band OB(m) = max(O, C₋₁) · (1 + σ(m)). Unteres Band UB(m) = min(O, C₋₁) · (1 − σ(m)).
4. Fehlt an einem der 14 Vortage die Kerze zu Minute m, oder heute eine Kerze zwischen Anker und Prüfzeit: an diesem Prüfzeitpunkt kein Signal (Zählung je Grund im Bericht).
5. Bandbreite-Faktor = 1,0 wie in der Studie. Das breitere Band aus den Reels wird **nicht** getestet: Der Wert ist nicht genannt und wurde dort nach Sicht der Daten gewählt.

### 4.3 Einstieg und Ausstieg (Long, Short gespiegelt)

1. Prüfzeitpunkte: jede volle und halbe Stunde nach dem Anker (NY: 10:00 … 15:30; UTC: 00:30 … 23:00). Maßgeblich ist der Schluss der 1m-Kerze, die zu diesem Zeitpunkt endet.
2. Einstieg Long, wenn der Schluss **strikt über** OB(m) liegt und keine Position offen ist. Einstieg zum Eröffnungskurs der nächsten 1m-Kerze (Taker, Slippage nach Protokoll 4.4). Erste Prüfung ist Minute 30 (NY 10:00) wie in der Studie.
3. Nachgezogener Stop (Variante der Studie mit VWAP): Long-Stop = max(OB(m), VWAP(m)), neu berechnet an jedem Prüfzeitpunkt. Ausgestiegen wird nur zu Prüfzeitpunkten: Liegt dort der Schluss unter dem Stop, folgt der Ausstieg zur Eröffnung der nächsten 1m-Kerze (Taker). Zwischen den Prüfzeitpunkten gibt es keinen Ausstieg, auch nicht bei großen Bewegungen.
4. Nach einem Ausstieg ist ein neuer Einstieg erlaubt, auch in die Gegenrichtung am selben Prüfzeitpunkt (wie in der Studie). Nicht erlaubt ist ein Wiedereinstieg in dieselbe Richtung am Prüfzeitpunkt des Ausstiegs (Kurs über dem Band, aber unter VWAP); frühestens am nächsten Prüfzeitpunkt (präzisiert in 0.2). Pro Instrument ist höchstens eine Position offen.
5. Sitzungsende: Die letzte 1m-Kerze der Sitzung ist immer ein Ausstiegs-Prüfzeitpunkt; geschlossen wird zur Eröffnung der ersten Kerze danach (NY 16:00, UTC 23:30), Taker. Nichts bleibt über Nacht offen.
   Fehlt an einem Prüfzeitpunkt Band oder VWAP (Lücke heute), wird eine offene Position dort geschlossen. Lücken in den Kerzen schließt die Engine ohnehin (`gap`).
6. **Katastrophen-Stop** (nicht in der Studie, wegen 24/7-Handel und Hebel): fester Stop bei Signalschluss ∓ 3 · σ(m_E) · O, auf jeder 1m-Kerze geprüft (Engine-Regel, Stop-Slippage). Wie oft er greift, steht im Bericht. Der Wert ist vorab gesetzt und wird nicht optimiert.

### 4.4 R-Einheit und Positionsgröße

Die Studie rechnet mit einem Volatilitätsziel (2 % Tagesvola, bis 4-fach Hebel), nicht in R. TIMs Kriterien K1–K5 sind in R definiert. Festlegung:

- **1 R = Abstand vom tatsächlichen Einstieg zum Katastrophen-Stop**, also rund 3 · σ(m_E) · O (wie bei allen TIM-Studien der Abstand zum festen Stop, `engine.Trade.r`). Geändert in 0.2: In 0.1 stand 1 R = σ · O; das passt nicht zur Engine, die R aus dem festen Stop rechnet. Der normale Ausstieg über das Band liegt meist deutlich unter 1 R Verlust. Alle Kosten werden in diese Einheit umgerechnet.
- Zusätzlich wird beschreibend berichtet: Rendite mit dem Volatilitätsziel der Studie (14-Tage-Vola, Ziel 2 %/Tag, Hebel ≤ 4) über das gepoolte Portfolio. Daraus folgt kein Urteil.

### 4.6 Abgleich mit dem Original (0.2)

Übereinstimmend: σ = Mittel der absoluten Bewegung seit 09:30-Eröffnung je Uhrzeit über 14 Tage; Bänder mit max/min aus Eröffnung und Vortagesschluss 16:00; Faktor VM = 1; Prüfung nur zu HH:00 und HH:30; erste Position um 10:00; Stop-Variante „aktuelles Band + VWAP“ (VWAP nur aus der Sitzung); Wechsel in die Gegenrichtung bei Bruch des anderen Bands; alles schließt um 16:00. Ergebnisse laut Studie (SPY, 2007 bis Anfang 2024, nach Kosten): Variante Band+VWAP mit 100 % Einsatz 9,7 % p. a., Sharpe 1,24, max. Drawdown 12 %; mit Volatilitätsziel 19,6 % p. a., Sharpe 1,33, Drawdown 25 %. Die Zahlen sind gelesen, nicht nachgerechnet.

Abweichungen für Krypto: zweiter Anker UTC (4.1); Katastrophen-Stop (4.3.6); R statt Volatilitätsziel (4.4; das Volatilitätsziel nur beschreibend); Ein- und Ausstieg zur Eröffnung der nächsten 1m-Kerze statt zum Prüfkurs; Funding nach Protokoll.

## 5. Erfolgskriterien

K1–K5 aus dem Protokoll, Horizont „Short“, ausgewertet mit dem allgemeinen Runner: Training ≥ 500 Trades, E[R] > 0, p < 0,10 gegen Zufall; Validierung ≥ 250 Trades, E[R] > 0, p < 0,05, Profitfaktor > 1,1, Drawdown ≤ 20 %, Jahresstabilität, Walk-Forward > 0. Wie bei S6/S10 zusätzlich mindestens 160 effektive Trades im Training und 183 in der Validierung (n_eff = ⌊n / D⌋, Designeffekt D aus dem Tagescluster über alle Instrumente). Zusätzlich berichtet: Ergebnis mit doppelten Kosten, BTC allein, Anteil der Ausstiege zum Sitzungsende bzw. durch Katastrophen-Stop, Funding-Anteil.

### 5.1 Machbarkeits-Gate (vor jedem Ergebnis)

Ergebnisblinder Zähllauf: nur Einstiegssignale (erster Ausbruch je Tag und Instrument), keine Ausstiege, kein R. Eine Variante wird nur ausgewertet, wenn sie gepoolt im Training ≥ 500 und in der Validierung ≥ 250 Signale an mindestens 160 bzw. 183 verschiedenen Tagen hat. Grobe Schätzung vorab: S13-UTC hat bis zu ~1 100 Tage je Instrument im Training, S13-NY ~750; das Gate sollte erreichbar sein. Besteht eine Variante nicht, wird sie nicht gelockert.

## 6. Zufallsvergleich

Protokoll 7.1 mit Pool-Methode nach R4(a): Zufällige Einstiege nur an **denselben Prüfzeitpunkten** (gleiche Variante, Instrument, Abschnitt), Richtung aus den echten Trades gezogen, danach exakt derselbe Ausstieg 4.3 (Band/VWAP, Sitzungsende, Katastrophen-Stop), dieselbe R-Einheit und dieselben Kosten. 10 000 Läufe, Seed 20261101.

## 7. Bis zur Erstellung gesehene Daten

Für S13 wurden keine Kurse ausgewertet. Gesehen sind: die Zusammenfassung der Studie (SPY, Mai 2007 bis April 2024) und zwei Reels (NQ/ES ab 2018, Werbung, Zahlen ungeprüft). Die Vorbelastung aus S7 und S10 steht in Abschnitt 2.

## 8. Festlegungen und offene Punkte vor Version 1.0

1. **Register:** Zuerst kommt der Zähllauf 5.1, der keinen Registerplatz belegt. Besteht eine Variante, läuft S13 wie von Uzi für S10 entschieden (28.10.2026) als **eigene Familie** (kein Archiv-Holdout, Bestätigung nur prospektiv auf neuen Daten). Die letzten zwei Registerplätze (58/60) bleiben frei. Vor jedem Ergebnis ist eine Protokoll-Einordnung wie bei S8 nötig. Uzi kann stattdessen die zwei Registerplätze wählen. Dann ist das Register voll und der Holdout für diesen Registerzeitraum verbraucht.
2. ~~Originalstudie lesen~~ erledigt in 0.2 (4.6).
3. ~~Code~~ in 0.2 gebaut (12 Tests, u. a. kein Blick in spätere Kerzen, NY-Kalender mit Sommerzeit, Lückenregel, Engine-Läufe). Offen: Zufallsvergleich (Abschnitt 6) als Code, danach Regeln mit Commit-Hash einfrieren (Version 1.0), erst dann Zähllauf auf dem Mac (`python scripts/research_lab_s13.py count`, Daten aus dem S10-Abruf, ein Instrument nach dem anderen im Speicher).
4. **Universum:** gepoolt über BTC/ETH/SOL wie bei S7 und S10, BTC allein wird beschreibend berichtet.

## Änderungsprotokoll

- 0.1 (01.11.2026): Entwurf aus der Zusammenfassung der Studie und den zwei Reels. Nichts registriert, keine Marktdaten ausgewertet.
- 0.2 (01.11.2026): Original gelesen (4.6). Regeln als Code mit Tests, Zählskript. R-Einheit auf den Katastrophen-Stop umgestellt (4.4). Ausstieg zur Eröffnung nach dem Prüfzeitpunkt und bei fehlendem Band präzisiert (4.3). Weiterhin keine Marktdaten ausgewertet.
