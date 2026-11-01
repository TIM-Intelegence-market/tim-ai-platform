# S14: Paar-Handel (Statistical Arbitrage) ETH/BTC, SOL/BTC, SOL/ETH (Präregistrierung, Entwurf)

| Feld | Wert |
|---|---|
| Studie | S14 (nächste freie Nummer laut `workshop.generator.next_study_id`, 01.11.2026) |
| Version | **1.0 – eingefroren am 02.11.2026 nach Uzis Einordnung (0:06 Uhr). Eingefrorener Code: Commit `f26a6d8` (Regeln `src/research_lab/hypotheses/s14.py`, Zufallsvergleich `src/research_lab/studies/s14_random.py`, Auswertung `src/research_lab/studies/s14_eval.py`, Skript `scripts/research_lab_s14.py`). Zähllauf bestanden für W168 und W720. Nichts registriert, kein R für S14 gesehen** |
| Anlass | Uzi 01.11.2026 („go“ auf den Vorschlag aus dem Reel `instagram.com/reel/DfKfQNPotER`, Kanal nishantaqc): Pairs Trading mit Kointegration, z-Wert ±2, Ausstieg bei Rückkehr |
| Quelle der Regeln | Lehrbuch-Standard nach Engle und Granger (1987) und Gatev, Goetzmann, Rouwenhorst (2006, „Pairs Trading“). Das Reel nennt nur die Grundidee (Kointegration, Absicherungsverhältnis aus Regression, Einstieg bei 2 Standardabweichungen, Ausstieg bei Rückkehr). Alle Zahlen unten sind vorab gesetzt und werden nicht optimiert |
| Protokoll | `../PROTOKOLL.md` Version 1.3, Kriterien K1–K5 unverändert, Horizont „Short“ (Signale auf 1h-Kerzen) |
| Einordnung | **Eigene Familie** wie S13 (Uzi per Karte 02.11.2026, 0:06 Uhr; `../PROTOKOLL.md` Eintrag 2026-11-02). Register bleibt 58/60, der Holdout ab 2025 wird nie geladen |

## 1. Fragestellung

Laufen zwei Krypto-Perpetuals mit gemeinsamem Trend (ETH und BTC, SOL und BTC, SOL und ETH) nach einer Abweichung von zwei Standardabweichungen wieder zusammen? Ist ein marktneutraler Handel auf den Abstand („Spread“) nach allen Kosten beider Beine positiv und besser als zufällige Einstiege mit demselben Ausstieg?

## 2. Was TIM schon hat und Vorbelastung

- Klines 5m BTC/ETH/SOL USD-M 2020–2024 und Funding auf dem Mac (Datensatz aus S10, `data.binance.vision`, Prüfsummen). Kostenmodell Protokoll 4.4, Zufallsvergleich 7.1.
- Die Engine (`backtest/engine.py`) handelt nur ein Instrument. Ein Paar hat zwei Beine, deshalb rechnet `s14.simulate_trade` den Trade selbst, mit denselben Kostenregeln (Taker-Gebühr und Slippage je Bein und Seite, Funding je Bein).
- **Vorbelastung:** Paar-Handel wurde in TIM noch nie getestet (Logbuch, Register). Gesehen sind: das Reel (Coca-Cola/Pepsi, keine Zahlen zu Krypto) und allgemeines Wissen, dass ETH/BTC über Jahre Trends hat (ETH/BTC fiel 2022–2024 deutlich). Das spricht gegen dauerhafte Kointegration, ist aber kein ausgewertetes Ergebnis.

## 3. Daten

- Instrumente BTCUSDT, ETHUSDT, SOLUSDT (USD-M), 5m-Klines zu 1h-Kerzen zusammengefasst. Eine Stunde zählt nur, wenn alle zwölf 5m-Kerzen da sind; sonst fehlt die Stunde.
- Paare (y gegen x): **ETH/BTC**, **SOL/BTC**, **SOL/ETH**. Ein Paar hat an einer Stunde nur Daten, wenn beide Beine sie haben.
- Training bis 2022, Validierung 2023–2024. SOL-Paare ab dem ersten vollständigen SOL-Monat (2020-09).

## 4. Regeln

### 4.1 Spread und z-Wert

1. ln y_t und ln x_t sind die Logarithmen der 1h-Schlusskurse.
2. Fenster = die **W vorherigen** Stunden t−W … t−1 (die aktuelle Stunde nicht enthalten), lückenlos in beiden Beinen. Sonst an t kein Signal.
3. Im Fenster: lineare Regression ln y = α + β · ln x (kleinste Quadrate). Residuen e = ln y − α − β ln x, Standardabweichung σ der Residuen.
4. z_t = (ln y_t − α − β ln x_t) / σ mit den Werten aus dem Fenster bis t−1.
5. Ist β ≤ 0 oder σ ≤ 0, gibt es an t kein Signal.

### 4.2 Varianten (vorab festgelegt, 4 Stück)

| Variante | Fenster W | Kointegrationsfilter |
|---|---|---|
| S14-W168 | 168 h (7 Tage) | aus |
| S14-W168-K | 168 h | an |
| S14-W720 | 720 h (30 Tage) | aus |
| S14-W720-K | 720 h | an |

Kointegrationsfilter (Engle-Granger): Dickey-Fuller-Regression auf den Residuen des Fensters, Δe_s = γ · e_{s−1} + φ · Δe_{s−1} + u_s (ohne Konstante, ein verzögerter Differenzterm). Das Signal zählt nur, wenn die t-Statistik von γ ≤ **−3,34** ist (asymptotischer 5-%-Wert für zwei Variablen mit Konstante, MacKinnon 2010). Die Nachbarschaftsregel 7.3 gilt für W (168 und 720 sind Nachbarn); der Filter ist eine Kategorie.

### 4.3 Einstieg und Ausstieg

1. **Einstieg:** z kreuzt an einem 1h-Schluss die Schwelle 2, also |z_{t−1}| < 2 (mit dem Fenster von t−1) und |z_t| ≥ 2, und für das Paar ist keine Position offen. Bei z ≥ 2 Short-Spread (y verkaufen, x kaufen), bei z ≤ −2 Long-Spread (y kaufen, x verkaufen). Einstieg beider Beine zur Eröffnung der nächsten 1h-Kerze (Taker, Slippage).
2. **Gewichte:** Bein y mit Nominalwert 1, Bein x mit Nominalwert β (Wert-Absicherung aus der Log-Regression). α, β und σ werden beim Einstieg **eingefroren**; der z-Wert während des Trades nutzt diese Werte.
3. **Ausstieg** an einem 1h-Schluss, ausgeführt zur Eröffnung der nächsten Kerze (Taker):
   - Rückkehr: z hat 0 erreicht oder gekreuzt (Short-Spread: z ≤ 0, Long-Spread: z ≥ 0);
   - Stop: |z| ≥ 4 in Gegenrichtung (Short-Spread z ≥ 4, Long-Spread z ≤ −4). Geprüft nur auf Stundenschlüssen, nicht innerhalb der Kerze (Abweichung zu Einzelinstrumenten, wird im Bericht genannt);
   - Zeit: 120 Stunden nach dem Einstieg;
   - Lücke: fehlt die nächste Stunde in einem Bein, Schluss beider Beine zum letzten gemeinsamen Schlusskurs (`gap`).
4. Pro Paar höchstens eine Position. Kein neuer Einstieg auf der Ausstiegskerze; der nächste Einstieg braucht ein neues Kreuzen von 2.

### 4.4 R-Einheit und Kosten

- **1 R = (4 − 2) · σ = 2σ**, der Abstand vom Einstiegs- zum Stop-Schwellwert in Log-Einheiten des Spreads bei Nominalwert 1 im Bein y.
- Ergebnis = Gewinn beider Beine (Bein y: Seite s, Gewicht 1; Bein x: Seite −s, Gewicht β), minus Gebühren beider Beine auf Ein- und Ausstieg, minus Funding je Bein (8-h-Zeitpunkte während des Trades, Vorzeichen wie Protokoll 4.4), geteilt durch 2σ.
- Gebühren und Slippage nach Protokoll 4.4 je Bein und Seite (vier Füllungen je Trade). Doppelte Kosten werden zusätzlich berichtet.

## 5. Erfolgskriterien

K1–K5 aus dem Protokoll, Horizont „Short“: Training ≥ 500 Trades, E[R] > 0, p < 0,10 gegen Zufall; Validierung ≥ 250 Trades, E[R] > 0, p < 0,05, Profitfaktor > 1,1, Drawdown ≤ 20 % (1 % Risiko je Trade), Jahresstabilität, Walk-Forward > 0, Nachbarschaft für W. Wie bei S13 zusätzlich n_eff ≥ 160 im Training und ≥ 183 in der Validierung (Designeffekt aus dem Tagescluster über alle Paare). Gepoolt über die drei Paare; ETH/BTC allein wird beschreibend berichtet.

### 5.1 Machbarkeits-Gate (vor jedem Ergebnis)

Ergebnisblinder Zähllauf: nur die Einstiegssignale (Kreuzen von |z| = 2, mit Filter je Variante), keine Ausstiege, kein R. Weil offene Positionen weitere Signale sperren, ist die Zahl eine **Obergrenze** der Trades. Eine Variante wird nur ausgewertet, wenn sie gepoolt im Training ≥ 500 und in der Validierung ≥ 250 Signale an mindestens 160 bzw. 183 verschiedenen Tagen hat. Besteht keine Variante, endet S14 dort. Das Gate wird nicht gelockert.

## 6. Zufallsvergleich

Protokoll 7.1 mit Pool-Methode nach R4(a): zufällige Einstiege nur an Stunden, an denen die Variante ein Signal hätte geben **können** (Fenster vollständig, β > 0, Filter erfüllt), gleiche Variante, gleiches Paar, gleicher Abschnitt. Richtung aus den echten Trades gezogen, danach exakt derselbe Ausstieg 4.3 mit den an dieser Stunde eingefrorenen α, β, σ. 10 000 Läufe, Seed 20261102. Als Code: `src/research_lab/studies/s14_random.py` (Tests `tests/test_research_lab_s14_run.py`; ein zufälliger Trade auf einer echten Signalstunde ergibt exakt den echten Trade).

## 7. Bis zur Erstellung gesehene Daten

Für S14 wurden keine Kurse ausgewertet. Gesehen sind nur das Reel und das in Abschnitt 2 genannte Allgemeinwissen.

### 7.1 Zähllauf 5.1 (01.11.2026, ergebnisblind)

Bericht `../reports/s14_count_2026-11-01T2250Z.md` (Commit `56fcd10`, Datensatz-Hash `182b222e…`, auf dem Mac). Gezählt wurden nur Einstiegssignale, keine Ausstiege und kein R.

| Variante | Training Signale (Tage) | Validierung Signale (Tage) | Gate |
|---|---:|---:|---|
| S14-W168 | 1725 (645) | 1433 (501) | bestanden |
| S14-W168-K | 161 (106) | 149 (98) | nicht bestanden |
| S14-W720 | 754 (348) | 663 (289) | bestanden |
| S14-W720-K | 54 (33) | 28 (16) | nicht bestanden |

Der Kointegrationsfilter lässt nur 10 % (W168) bzw. 6 % (W720) der Signale durch. Beide K-Varianten scheiden damit vor jedem Ergebnis aus und werden nicht ausgewertet. Das Gate wird nicht gelockert. Für die Nachbarschaftsregel bleiben W168 und W720 ohne Filter.

## 8. Offene Punkte vor Version 1.0

1. ~~Einordnung~~ entschieden: eigene Familie (Uzi 02.11.2026).
2. ~~Zähllauf 5.1 auf dem Mac~~ erledigt (7.1).
3. ~~Zufallsvergleich und Auswertung als Code~~ erledigt: `s14_random.py`, `s14_eval.py`, `scripts/research_lab_s14.py run` (nur W168 und W720). Nachbarschaft: W168 braucht E[R] > 0 im Training von W720 und umgekehrt.
4. ~~Einfrieren~~ erledigt (1.0, Commit `f26a6d8`). Danach ein Lauf mit R auf dem Mac (`python scripts/research_lab_s14.py run`).

## Änderungsprotokoll

- 0.1 (01.11.2026): Entwurf auf Uzis „go“. Regeln als Code, Zählskript. Nichts registriert, keine Marktdaten ausgewertet.
- 0.2 (01.11.2026): Zähllauf 5.1 eingetragen (7.1). W168 und W720 bestehen das Gate, W168-K und W720-K nicht. Weiter kein R gesehen.
- 0.3 (01.11.2026): Zufallsvergleich und Auswertung als Code (Abschnitt 6, 8). Keine Regeländerung, kein R gesehen.
- 1.0 (02.11.2026): Einordnung eigene Familie (Uzi), Regeln und Code mit Commit `f26a6d8` eingefroren. Kein R gesehen.
