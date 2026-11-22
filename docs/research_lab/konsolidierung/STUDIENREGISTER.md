# Studienregister der Konsolidierung (Stand 16.11.2026)

Quelle der Wahrheit ist `studienregister.json` (maschinenlesbar). Diese Datei wird daraus erzeugt (`python3 -m src.research_lab.konsolidierung.register`).
Vollständigkeit gilt nur im durchsuchten Umfang (Abschnitt „Nicht zugängliche oder nicht durchgesehene Quellen“).

## Zählung

- Einträge gesamt: **74**, davon gefundene Studien und Berichte: **69**, eigene Nachrechnungen dieser Konsolidierung: 5.
- Klassen (gefundene Studien): BELASTBAR 4, BEDINGT VERWERTBAR 31, EXPLORATIV 30, UNGÜLTIG 0, NICHT REPRODUZIERBAR 4.
- Prüftiefe (gefundene Studien): A 2, B 8, C+ 23, C 29, D 7.
- Art (gefundene Studien): Carry 1; Filterstudie 8; Handelsregel oder Regelfamilie (gerechnet) 23; Plattform, Prüfbericht, Meta 7; Prognose-, Beobachtungs- oder Kalibrierstudie 18; Prospektive oder reale Beobachtung 8; Sonstiges (Entwurf, Gate, Zähllauf) 4.
- Urteil des Labors laut Logbuch (erstes Wort): aborted 1, candidate 2, confirmed 2, failed 22, no_proof 1, not_proven 1, not_testable 8, reported 13, running 11, stopped 1, waiting 7.

## Prüftiefen

- **A**: Regelcode und Rohdaten unabhängig neu gerechnet; Handelsliste des Labors reproduziert
- **B**: Rohe Handelsliste oder Rohergebnis des Labors neu ausgewertet (Kennzahlen, Bootstrap)
- **C+**: Ergebnisdatei gelesen und die Zahlen des Logbuchs darin wiedergefunden (Konsistenz, keine Neuberechnung)
- **C**: Präregistrierung oder Bericht gelesen, keine Zahlenprüfung
- **D**: Nur Logbuchzeile und Kopf der Präregistrierung

## Qualitätsklassen

- **BELASTBAR**: Rechnung unabhängig bestätigt (Prüftiefe A oder B), Regel vorab festgelegt, keine bekannte Verzerrung, die das Urteil kippen würde. Sagt nichts über die Richtung: auch ein Negativbefund kann belastbar sein.
- **BEDINGT VERWERTBAR**: Methode im Kern sauber, aber mit benannter Einschränkung (kleine oder mehrfach verbrauchte Stichprobe, nicht unabhängig nachgerechnet, Annahmen). Nutzbar nur mit dieser Einschränkung.
- **EXPLORATIV**: Hinweis ohne vorab festgelegte Bestehensregel, zu wenige Fälle, nur Gate/Zähllauf oder noch nicht ausgewertet. Nur zur Hypothesenbildung.
- **UNGÜLTIG**: Methodischer Fehler oder fehlende Voraussetzung, sodass die Aussage nicht als Evidenz zählt (z. B. Kriterium nach dem Ergebnis geändert, Blick nach vorn, Datenlücke).
- **NICHT REPRODUZIERBAR**: Ergebnis lässt sich aus Repo und Daten nicht nachvollziehen (Datei oder Daten fehlen, nur Erinnerung).
- Regel: `BELASTBAR` setzt Prüftiefe A oder B voraus. Aussagen werden einzeln gekennzeichnet: VERIFIZIERT (selbst nachgerechnet oder in der Ergebnisdatei gefunden), NUR BERICHTET, ANNAHME, NICHT PRÜFBAR.

## Datenüberschneidung (Cluster)

- **TREND-4H**: Binance USD-M 4h BTC/ETH/SOL 2020–2024, Donchian/SMA200-Regel (S7, S7b). S7b-Makro und S25 verwenden dieselbe Handelsliste, S32 dieselbe Regel auf anderen Märkten. Eine Evidenzquelle für die Regel, nicht fünf. Einträge: S7, S7b, S7b-Makro, S7b-Sonde, S25, S32.
- **BTC-1H**: BTC 1h, S8-Minutenbalken-Datensatz (SHA-256 9083b6ae…), Standard-Trades. Die Validierung 2023–2024 wurde von S20–S28 wiederholt verwendet; die Studien sind nicht unabhängig voneinander. Einträge: S20, S21, S22, S23, S24, S26, S27, S28, E0/E1.
- **OF-MIN**: S8-Minutenbalken (Orderflow/Footprint, BTC 2020–2024). OF2, S31 (B1–B5 sind OF2-Modelle), OFX, S19, S17 und die Move-Kalibrierung teilen dieselben Daten. Einträge: S2, S8, S19, OF2, OFX, S31, S31b, S29, OF2-Kostengrenze, Bitunix-Edge.
- **LEVEL-INTRADAY**: BTC/ETH/SOL 1m–15m aus Binance-Archiven, Training 2020–2022/23; S30, S34–S38 und die VWAP-Beschreibung testen Level-Ideen auf überlappenden Zeiträumen. Einträge: S30, S34, S35a, S36, S37, S38, VWAP-1W-2sigma.
- **FRÜH**: Frühe Studien (Sept.–Nov. 2026) auf BTC/ETH/SOL 2020–2024 mit Protokoll 1.x: R4 (48 Varianten), S4, S6, S9, S10, S13, S14. Einträge: R4, S1, S4, S6, S9, S10, S13, S14.
- **CARRY**: Funding-Carry: S5 (nicht testbar), S33-Carry (nur Training), eigene Prüfung T11. Einträge: S5, S33-Carry.
- **PROSPEKTIV**: Papier-Journale, Schatten und Echtgeld-Mini-Test: einzelne Beobachtungsfenster ab Oktober/November 2026, kleine Stichproben. Einträge: S7b-Forward, K1, Plan-Journale, OF-Schatten, Exit-Schatten, Stop-Analyse-30m, Kraken-Kosten, Bitunix-Konto, Kraken-Echtgeldtest.
- **OPTIONEN**: Deribit-Optionen/Gamma: Entwürfe, nur vorwärts; keine Historie. Einträge: S33, GEX-Wand.
- **PROGNOSE**: Prognose-, Verteilungs- und KI-Studien ohne oder mit Papiertrades: Risiko- und Anzeigebausteine, keine Gewinnaussage. Einträge: S15, L1, S12, S16, S17, S18, KI1, T07, Move-Kalibrierung, S39.
- **INFRA**: Plattform-, Daten- und Software-Abnahmen: prüfen Pipeline und Governance, nicht Profitabilität. Einträge: V2, F4, V1-Juli, tim-master-P1, Prüfberichte-Chart, Überzeugungsregister.
- **EIGEN**: Eigene Nachrechnungen dieser Konsolidierung (Protokoll 1.0, eingefroren). Einträge: K-C1, K-Carry, K-Ref, K-Bitunix, K-T15.

## Übersicht

| Id | Titel | Cluster | Labor | Prüftiefe | Klasse | Richtung | Stichprobe |
|---|---|---|---|---|---|---|---|
| R4 | 48 Orderflow- und Struktur-Varianten mit Glückstest (SPA/StepM) | FRÜH | failed | C+ | BEDINGT VERWERTBAR | negativ | 48 Varianten |
| S1 | BTC-Schwankung an CPI-Terminen | FRÜH | confirmed | C+ | BEDINGT VERWERTBAR | keine Handelsaussage | CPI-Termine, Anzahl siehe Bericht |
| S2 | TIMs Live-Orderflow-Regeln als Hypothese | OF-MIN | not_testable | C | EXPLORATIV | keine Aussage | Zähllauf bestanden, Power-Gate nicht |
| S4 | Trefferquote 75 % mit Ziel 0,75 R (Sweep, Delta, Regime) | FRÜH | not_testable | C+ | BEDINGT VERWERTBAR | negativ | 10 Varianten; Erkundung z. B. 4.795 Trades (H1-N2… |
| S5 | Trefferquote 95 % mit Funding-Carry (Perp-Wechsel) | CARRY | not_testable | C+ | EXPLORATIV | keine Aussage | zu wenige Episoden (2022 keine) |
| S6 | Trefferquote 95 % mit Maker-Limits an der VWAP-Abweichung | FRÜH | failed | C+ | BEDINGT VERWERTBAR | negativ | Trades siehe Bericht |
| S7 | Trendfolge-Ausbruch 3–4 R (Donchian, SMA200), BTC/ETH/SOL 4h, Positionen je Symbol | TREND-4H | failed | A | BEDINGT VERWERTBAR | positiv (Erwartung), Risikokriterium ve… | Training und Validierung: z. B. D20-T3 557 / 420 … |
| S7b | Trendfolge-Ausbruch 3–4 R mit höchstens einer Position (BTC > ETH > SOL) | TREND-4H | candidate | A | BEDINGT VERWERTBAR | positiv (Kandidat) | D20-T3: Training 292, Validierung 207 Trades (D20… |
| S7b-Makro | S7b-Makrofilter F1–F5 (Realzins, Dollar, Liquidität u. a.) als Filter auf S7b-Trades | TREND-4H | candidate | C | EXPLORATIV | unklar (Mehrfachtest nicht bestanden) | Trades der S7b-Liste |
| S7b-Forward | S7b Papier-Vorwärtsjournal auf Live-Kerzen ab 01.11.2026 (D20-T3, D20-T4) | PROSPEKTIV | running | B | EXPLORATIV | positiv (n viel zu klein) | D20-T3 4 geschlossene Trades, D20-T4 3 (Stand 16.… |
| S7b-Sonde | S7b Sondenlauf 04.07.–01.11.2026 (zufällig gesehen, in der Präregistrierung vermerkt) | TREND-4H | reported | C | EXPLORATIV | negativ (n klein) | D20-T3 35 Trades, D20-T4 30 Trades |
| S25 | Positionsgröße nach GARCH-4h-Prognose für S7b-D20-T3 | TREND-4H | failed | C+ | BEDINGT VERWERTBAR | negativ | n 139 / 207 |
| S32 | Korb-Trendfolge: S7b-D20-T3 unverändert auf Top-25-Perps ohne BTC/ETH/SOL, 4h | TREND-4H | failed | C+ | BEDINGT VERWERTBAR | negativ | Training 4.682, Validierung 3.311 Trades |
| S15 | GARCH(1,1)-Volatilitätsprognose gegen 14-Tage-Varianz, BTC/ETH/SOL, 4h und 1d | PROGNOSE | confirmed | C+ | BEDINGT VERWERTBAR | keine Handelsaussage (Risikoschicht) | mehrere Jahre, drei Coins |
| S9 | CHoCH, Retest-Band, Reaktionsschluss auf 15m (Signalgruppe-Lernheft) | FRÜH | not_testable | C | EXPLORATIV | keine Aussage | höchstens 11 Signale statt 500 |
| S10 | IB-Ausbruch New York mit Retest an POC/Value-Kante | FRÜH | not_testable | C+ | EXPLORATIV | keine Aussage | S10-P 241 von 500, S10-O 15 |
| S13 | Noise-Band-Ausbruch (Intraday-Momentum nach Zarattini/Aziz/Barbon 2024), NY-Sitzung und U… | FRÜH | failed | C+ | BEDINGT VERWERTBAR | negativ | S13-NY 1.732, S13-UTC 9.554 Trades (Training) |
| S14 | Paar-Handel (Statistical Arbitrage) ETH/BTC, SOL/BTC, SOL/ETH, 1h | FRÜH | failed | C+ | BEDINGT VERWERTBAR | negativ | W168: 750 / 620 Trades, W720: 232 / 195 |
| K1 | Kosten-Schwelle 0,25 R für Plan-Journal-Pläne | PROSPEKTIV | waiting | C | EXPLORATIV | keine Aussage | 2 geschlossene Pläne, 30 nötig |
| V2 | V2-Qualifizierungskampagne (1000 unabhängige Fälle) | INFRA | aborted | D | NICHT REPRODUZIERBAR | keine Aussage | 54 von 1000 Fällen |
| F4 | Perp-Daten: 48-h-Probe der Futures-Trades neben Spot | INFRA | running | D | EXPLORATIV | keine Aussage | 48 Stunden |
| S20 | Flip-Wahrscheinlichkeit aus der Kerzenstruktur, BTC 1h, Bruch von Swing-Linien | BTC-1H | failed | C+ | BEDINGT VERWERTBAR | negativ | 561 / 216 Ereignisse |
| S21 | Orderflow und Funding am Flip (CVD, Volumentrend, Footprint, Funding gegen den Abstand zu… | BTC-1H | failed | C+ | BEDINGT VERWERTBAR | negativ | Ereignisse K 561/216, F 318/216, G 308/216 |
| S22 | Chart-Urteil im Rückblick: sortieren die Kerzen-Regeln R1–R5 Standard-Trades, BTC 1h | BTC-1H | failed | C+ | BEDINGT VERWERTBAR | negativ | Validierung: NEHMEN 4.228 / AUSLASSEN 13.295 Trad… |
| S23 | Open Interest am Flip: hält ein Bruch besser mit OI als mit dem Abstand allein, BTC 1h | BTC-1H | waiting | D | EXPLORATIV | keine Aussage | Gate ≥ 200 / ≥ 150 Ereignisse |
| S24 | Alle Indikatoren mit Historie zusammen (C/K/F/G/T/V, M1 Stimmen, M2 Logit) auf Standard-T… | BTC-1H | failed | C+ | BEDINGT VERWERTBAR | negativ (sortiert, aber nach Kosten ver… | 34.848 Trades in der Validierung |
| S26 | Aufwand gegen Ergebnis: Absorption, Initiative und Book Sweep je 1h-Kerze, BTC | BTC-1H | failed | C+ | BEDINGT VERWERTBAR | negativ | Absorption 307, Initiative 666 Trades (Validierun… |
| S27 | Alle Indikatoren (S24) auf größeren Trades: Stop 3 ATR, Ziel 6 ATR, 168 h, BTC 1h | BTC-1H | failed | C+ | BEDINGT VERWERTBAR | negativ | 34.368 Trades in der Validierung |
| S28 | Positionierung aus dem Binance-Metrics-Archiv (OI, Top-Trader, Taker-Verhältnis) auf S27-… | BTC-1H | failed | C+ | BEDINGT VERWERTBAR | negativ | Validierung 17.129 Momente je Richtung (Auswertun… |
| S8 | Orderflow-KI: Richtung der nächsten 5 Minuten aus Orderflow-Merkmalen (prospektiv) | OF-MIN | running | D | EXPLORATIV | keine Aussage | keine Auswertung |
| S19 | Orderflow-Schwellen BTC (Imbalance, Auktionsrand, Absorption, dünnes Extrem, Exhaustion) | OF-MIN | no_proof | C | BEDINGT VERWERTBAR | negativ / ohne Nachweis | Training n bis 8.420 je Flag, Validierung n bis 5… |
| OF2 | Orderflow-Engine nach Mentor-Modellen M1–M7, jede Session handelbar (Training 2020–2022) | OF-MIN | not_proven | B | BEDINGT VERWERTBAR | positiv (Training, n 56, nicht belegt) | 56 OF-Trades in 1.096 Tagen (0,051/Tag) |
| OFX | PS5-Dauerforschung: Suche nach besseren OF2-Varianten mit Sieb und Reality-Check (Trainin… | OF-MIN | running | B | BEDINGT VERWERTBAR | negativ (Suche ohne Ergebnis) | 27.023 Konfigurationen × 300 Filter = 8.106.900 V… |
| S31 | Mentor-Bootcamp-Orderflow-Regeln B1–B8, BTCUSDT 15m/1h | OF-MIN | not_testable | C+ | EXPLORATIV | keine Aussage | B1 34, B2 13, B3/B4 2, B5 1/6, B6 0, B7 18 (OF) /… |
| S31b | Orderflow-Regeln M1–M7 (OF2) und B6/B7 auf 1h- und 4h-Kerzen, BTC | OF-MIN | not_testable | C+ | EXPLORATIV | keine Aussage | höchster Wert B7 1h 39 Trades (Preis-Zwilling 117) |
| S29 | Nachspielen der Journal-Regel (Setup-Pfad-Planer rückwirkend), BTC | OF-MIN | running | D | NICHT REPRODUZIERBAR | keine Aussage | unbekannt |
| L1 | Lernschleife Champion/Herausforderer für die Orderflow-KI (Prognosegüte) | PROGNOSE | waiting | C | EXPLORATIV | keine Aussage | keine |
| S12 | Trifft die geschätzte Liquidations-Heatmap echte Liquidationen? (Kalibrierung eines Anzei… | PROGNOSE | running | C | EXPLORATIV | keine Aussage | Sammler seit 02.11.2026 |
| S30 | Level-Reaktion am Kerzen-Level: Fade-Raster (12 Regeln) und Ausbruch, BTC 4h | LEVEL-INTRADAY | failed | C+ | EXPLORATIV | negativ | Raster 12 Varianten, n je Variante 450–910 |
| E0/E1 | E0 Kosten-Zerlegung der BTC-1h-Studien (S22, S24, S27) und E1 Zählung von Level-Ereigniss… | BTC-1H | reported | C+ | BEDINGT VERWERTBAR | negativ | 50.438 / 34.848 Trades je Studie |
| S34 | LVN am Wochen-VAH/VAL plus ≥ 2 σ vom Tages-VWAP, Rückkehr zum VWAP, BTC 5m | LEVEL-INTRADAY | failed | B | BELASTBAR | negativ | 53 Trades |
| S35a | Level plus Orderflow-Bestätigung, Rückprall und Ausbruch (Extrem, VWAP-Band, Vortagsprofi… | LEVEL-INTRADAY | failed | B | BELASTBAR | negativ | n 2.218–5.248 je Variante |
| S36 | SFP mit Orderflow-Konfluenz, HTF→Exec, Varianten M (Markt) und L (Limit), BTC/ETH/SOL | LEVEL-INTRADAY | failed | B | BELASTBAR | negativ | SFP-alle-M 425, L 438 Trades |
| S37 | Fade-Checkliste (Flowread) Teil a ohne Gamma: Fade zum Tages-VWAP mit Vortags-VA, ±2 σ un… | LEVEL-INTRADAY | not_testable | B | EXPLORATIV | keine Aussage | 1–5 Trades je Variante |
| S38 | Enger Vortag, danach Ausbruch am Folgetag (T-045/T-060/T-075), BTC/ETH/SOL 1m | LEVEL-INTRADAY | failed | B | BELASTBAR | knapp positiv, nicht von null untersche… | T-045 191, T-060 584, T-075 982, T-alle 2.399 Tra… |
| S33-Carry | Funding-Carry BTC (Perp short gegen Spot long), Training | CARRY | failed | C+ | EXPLORATIV | positiv (Kapitalrendite, kein Handelsvo… | ein Instrument |
| S33 | Optionsflow als Filter auf S27-Trades (R1–R6) und Spannenprognose (V1–V2), BTC, vorwärts | OPTIONEN | waiting | C | EXPLORATIV | keine Aussage | keine |
| GEX-Wand | Reaktion an Call Wall und Put Wall (Gamma, BTC) | OPTIONEN | waiting | C | EXPLORATIV | keine Aussage | keine |
| S16 | Funding-Extreme als Kontraindikator (Verteilung) | PROGNOSE | failed | C | BEDINGT VERWERTBAR | negativ | oben 523, unten 815 Ereignisse (entclustert) |
| S17 | Kosten in R nach Tageszeit (UTC-Stunden, Wochentage) | PROGNOSE | failed | C | BEDINGT VERWERTBAR | keine Handelsaussage | 26.047 / 17.527 Fälle |
| S18 | Kronos-Pfadfächer für BTC: Trifft die 24-Stunden-Spanne so oft, wie sie verspricht, und s… | PROGNOSE | running | C | EXPLORATIV | keine Aussage | läuft |
| KI1 | KI-Filter vor TIM-Trades (NEHMEN/AUSLASSEN durch ein lokales Sprachmodell) | PROGNOSE | waiting | C | EXPLORATIV | keine Aussage | keine |
| T07 | KI-Zusatznutzen gegen einfache Alternativen messen (Benchmark-Spezifikation) | PROGNOSE | waiting | C | EXPLORATIV | keine Aussage | 120 Fragen geplant |
| Move-Kalibrierung | Kalibrierung des Bewegungs-Detektors (move-context 0.2): wie oft schlägt er an | PROGNOSE | reported | C | BEDINGT VERWERTBAR | keine Handelsaussage | 43.814 Stunden |
| S39 | Preisbewegungen erklären: Ergebnis nach Marktereignis-Typ (Etikett am Papier-Trade, P5) | PROGNOSE | running | C | EXPLORATIV | keine Aussage | Training 69 Bewegungen, n 14–22 je Typ; 2024 nur … |
| Plan-Journale | Plan-Journale (Papier) 30m/15m/1h/level/perp: Journal-Prüfung 1 (12.11.2026) | PROSPEKTIV | running | C | EXPLORATIV | unklar (Intervalle schließen null ein) | 84 geschlossene Pläne |
| OF-Schatten | Orderflow-Schatten (Gate und Orderflow-Ausstieg) auf den Plänen 15m/1h | PROSPEKTIV | running | C | EXPLORATIV | unklar (n 25, eine Marktphase) | 25 geschlossene Pläne zum Zeitpunkt der Regel |
| Exit-Schatten | Läufer statt festem TP3 (Schatten-Journal Exit-Varianten), Papier | PROSPEKTIV | running | C | EXPLORATIV | unklar (n 7) | 7 Trades mit TP2 |
| Stop-Analyse-30m | Stop-Analyse der 30m-Testtrades (11 geschlossene Trades) | PROSPEKTIV | reported | C | EXPLORATIV | negativ (n 11) | 11 Trades |
| VWAP-1W-2sigma | 1W VWAP −2σ: Wie oft wird das Band getroffen und was folgt (BTC 1h, Beschreibung) | LEVEL-INTRADAY | reported | C | EXPLORATIV | negativ vor Kosten | 208 / 53 Wochen |
| OF2-Kostengrenze | OF2: Wie viele Trades am Tag sind am profitabelsten (Kostengrenze max_cost_r variiert) | OF-MIN | reported | C | EXPLORATIV | positiv knapp / sinkend mit n | 56–397 OF-Trades je Einstellung |
| Bitunix-Edge | Bitunix-Edge Phasen 1–6: Fähigkeits-Audit, API-Prüfung, Hebel, 50-USDT-Modell (11.11.2026) | OF-MIN | reported | C | BEDINGT VERWERTBAR | keine Edge belegt | 56 OF2-Trades |
| Kraken-Kosten | Echte Handelskosten bei Kraken (Messung 01.–04.11.2026, 22 Füllungen) | PROSPEKTIV | reported | C | BEDINGT VERWERTBAR | keine Handelsaussage | 22 Füllungen, Ordergrößen 50–85 USD |
| Bitunix-Konto | Bitunix-Konto von Uzi, letzte 365 Tage (nur berichtet) | PROSPEKTIV | reported | D | NICHT REPRODUZIERBAR | negativ (nur berichtet) | nicht bekannt |
| Kraken-Echtgeldtest | Kraken-Live-Trader (Echtgeld-Test) und Journal auto.jsonl | PROSPEKTIV | stopped | D | NICHT REPRODUZIERBAR | keine Aussage | 133 Journalzeilen (Stand 09.11.), 7 Auto-Trades b… |
| V1-Juli | TIM V1 Juli 2026: Wissenschaftliche Validierung, 72h-Abnahme, Abgleichsbericht, Orderflow… | INFRA | reported | C | BEDINGT VERWERTBAR | keine Handelsaussage | 165 voll validierte Fälle (22.07.), 1.339 (23.07.) |
| tim-master-P1 | tim-master: P1 Plan-Journal mit Evidenz-Gate (Software, 23.10.2026) | INFRA | reported | C | BEDINGT VERWERTBAR | keine Handelsaussage | 108 gezielte Tests grün |
| Prüfberichte-Chart | Indikator-Prüfung (31.10./04.11.), Orderflow-Kontrolle (06.11.), Master-Analyse Mentor (0… | INFRA | reported | C | BEDINGT VERWERTBAR | keine Handelsaussage | 331 Einzelprüfungen (04.11.) |
| Überzeugungsregister | TIM-Gedächtnis: Überzeugungsregister v0 (253 Aussagen, 12.11.2026) und Aussagenliste | INFRA | reported | C | BEDINGT VERWERTBAR | keine Handelsaussage | 253 Aussagen (64 Live-Regeln, 99 Forschung, 90 ex… |
| K-C1 | Konsolidierung C1: S7b-D20-T3 unverändert (BTC/ETH/SOL 4h), unabhängig neu gerechnet und … | EIGEN | reported | A | BEDINGT VERWERTBAR | positiv (historisch), G7 und G8 verfehlt | 499 Trades (292 / 207) |
| K-Carry | Konsolidierung T11: Funding-Carry BTC+ETH (Spot long, Perp short) nach Protokoll, plus Se… | EIGEN | reported | A | BEDINGT VERWERTBAR | positiv aber Kapitalrendite (nicht Edge) | 2 Instrumente |
| K-Ref | Konsolidierung T10: risikogleiche einfache Referenzen R1 (Korb Buy&Hold) und R2 (SMA200 l… | EIGEN | reported | A | BEDINGT VERWERTBAR | kein Vorsprung gegen einfache Referenz | Tagesreihen 2020–2024 |
| K-Bitunix | Konsolidierung T13: Bitunix-Kerzen und Kontraktdaten gegen Binance (Übertragbarkeit) | EIGEN | reported | A | BEDINGT VERWERTBAR | kein Unterschied zu Binance | 269 gegen 264 Trades, 252 gemeinsame Signale |
| K-T15 | Konsolidierung T15: Trendregel C3 (S7b-D20-T3 auf BTC/ETH) außerhalb des Entwicklungszeit… | EIGEN | reported | A | BEDINGT VERWERTBAR | positiv, nicht signifikant | 157 Trades (K2) |

## Einträge

### R4: 48 Orderflow- und Struktur-Varianten mit Glückstest (SPA/StepM)

- Cluster / Art / Beginn: FRÜH / Regelfamilie (Test) / 2026-09-29
- Quellen: `docs/research_lab/reports/r4_2026-09-29T2219Z.md`; `docs/research_lab/reports/r4_2026-09-29T2219Z.json`; `docs/research_lab/REGISTER.jsonl`; `/mnt/project-files/analysen/glueckstest-r4-2026-10-24.md (Probelauf, nicht im Repo)`
- Daten: BTC/ETH/SOL, Binance, 2020–2024
- Aufteilung: Training / Validierung (Holdout ab 2025 gesperrt)
- Kosten: Protokoll 1.x
- Register: 48 Registerplätze (L1 6, L2 6, M1 4, M2 4, M3 14, S1 4, S2 4, T1–T3 je 2), Stand Register: 42 im Training, 6 in der Validierung gescheitert, keine bestanden
- Stichprobe: 48 Varianten
- Ergebnis: Kein Vorteil in Training und Validierung; SPA p 0,46 / 0,43, StepM wählt keine Variante.
- Urteil des Labors: failed
- **Prüftiefe C+, Klasse BEDINGT VERWERTBAR, Richtung: negativ**
- Begründung: Die Zahlen des Logbuchs stehen in der Ergebnisdatei. Familie ist breit (48 Varianten) und mit Glückstest ausgewertet; nicht einzeln nachgerechnet.
- Mängel: Nicht einzeln nachgerechnet; Teil der frühen Protokollversion; Kosten- und Stopmodell nach Protokoll 1.x
- Aussagen: Kein Vorteil in Training und Validierung (SPA p 0,46 / 0,43) [NUR BERICHTET]; Zahlen des Logbuchs stehen in der Ergebnisdatei [VERIFIZIERT]; Registerstatus der 48 Varianten: 42 failed_train, 6 failed_validation [VERIFIZIERT]; Glückstest-Probelauf 24.10.: SPA p 0,36/0,46/0,53 (Training), 0,34/0,43/0,53 (Validierung), StepM keine Variante [NUR BERICHTET]
- Verwendung in der Konsolidierung: Negativbefund für Orderflow-/Struktur-Regeln der Familie; füllt 48 der 58 belegten Registerplätze (zählt für den Mehrfachtest-Zähler).

### S1: BTC-Schwankung an CPI-Terminen

- Cluster / Art / Beginn: FRÜH / Beobachtungsstudie (Volatilität) / 2026-10-13
- Quellen: `docs/research_lab/studien/S1_CPI_VOLATILITAET.md`; `docs/research_lab/reports/s1_cpi_volatility.md`; `docs/research_lab/reports/s1_cpi_volatility.json`
- Daten: BTC 1h/4h/24h, CPI-Termine
- Aufteilung: ein Fenster
- Kosten: keine (beschreibend)
- Register: kein Registerplatz (die Registerfamilien S1/S2 gehören zu R4 und sind andere Hypothesen)
- Stichprobe: CPI-Termine, Anzahl siehe Bericht
- Ergebnis: CPI-Stunde: Schwankung im Median 1,40-mal so groß wie sonst; 4h und 24h nicht bestätigt.
- Urteil des Labors: confirmed
- **Prüftiefe C+, Klasse BEDINGT VERWERTBAR, Richtung: keine Handelsaussage**
- Begründung: Beschreibende Volatilitätsaussage, keine Richtung und keine Rendite; für die Frage nach einem Handelsvorteil ohne Beitrag.
- Mängel: Keine Handelsregel, keine Kosten
- Aussagen: CPI-Stunde 1,40-fach (Median) [NUR BERICHTET]; Zahl steht in Ergebnisdatei [VERIFIZIERT]
- Verwendung in der Konsolidierung: Nur als Begründung für die Sperrzeit um Termine; nicht als Handelsvorteil gezählt.

### S2: TIMs Live-Orderflow-Regeln als Hypothese

- Cluster / Art / Beginn: OF-MIN / Regelfamilie (Test) / 2026-10-22
- Quellen: `docs/research_lab/studien/S2_ORDERFLOW_REGELN_PRAEREGISTRIERUNG.md`; `docs/research_lab/reports/s2_count_2026-10-25T2249Z.md`; `docs/research_lab/reports/s2_power_2026-10-25T2345Z.md`
- Daten: BTC, Orderflow-Merkmale (aggTrades)
- Aufteilung: Training / Validierung
- Kosten: Protokoll 1.x
- Register: kein Registerplatz (die Registerfamilie S2 gehört zu R4)
- Stichprobe: Zähllauf bestanden, Power-Gate nicht
- Ergebnis: Nicht beurteilbar: keine der sechs gerichteten Arten erreicht in allen Szenarien 90 % Power; beendet auf Uzis Entscheid am 26.10.2026. Die Live-Orderflow-Regeln gelten als Beobachtungen, nicht als Signale.
- Urteil des Labors: not_testable
- **Prüftiefe C, Klasse EXPLORATIV, Richtung: keine Aussage**
- Begründung: Das Power-Gate scheiterte: Die Studie konnte einen realistischen Effekt gar nicht nachweisen. Das ist weder Beleg noch Gegenbeleg.
- Mängel: Zu geringe Teststärke
- Aussagen: Power-Gate nicht bestanden [NUR BERICHTET]
- Verwendung in der Konsolidierung: Kein Beitrag; belegt nur, dass die Fallzahl nicht reichte.

### S4: Trefferquote 75 % mit Ziel 0,75 R (Sweep, Delta, Regime)

- Cluster / Art / Beginn: FRÜH / Regelfamilie (Gate + Erkundung) / 2026-10-25
- Quellen: `docs/research_lab/studien/S4_TREFFERQUOTE_75_PRAEREGISTRIERUNG.md`; `docs/research_lab/reports/s4_count_2026-10-25T1620Z.md`; `docs/research_lab/reports/s4_explore_2026-10-25T1630Z.md`; `docs/research_lab/reports/s4_hitrate95_2026-10-25T1733Z.md`
- Daten: BTC, 1h/4h
- Aufteilung: Zähllauf auf Training; Erkundung danach
- Kosten: Protokoll 1.x
- Register: kein Registerplatz belegt
- Stichprobe: 10 Varianten; Erkundung z. B. 4.795 Trades (H1-N24)
- Ergebnis: Gate gescheitert (keine der 10 Varianten genug Trades). Erkundung: alle Varianten verlieren nach Kosten (E[R] −0,12 bis −0,23 R), Trefferquote unter 54 %.
- Urteil des Labors: not_testable
- **Prüftiefe C+, Klasse BEDINGT VERWERTBAR, Richtung: negativ**
- Begründung: Zeigt für die Winrate-Frage: Das Ziel von 75 % wurde mit diesen Regeln nicht annähernd erreicht (höchste Trefferquote 52,5 %, obere Intervallgrenze überall unter 54 %), und jede Variante verliert nach Kosten. Die Erkundung ist ausdrücklich keine bestandene Studie.
- Mängel: Erkundung nach dem Gate-Scheitern, nicht vorab festgelegt
- Aussagen: Erkundung: E[R] −0,12 bis −0,23 R je Trade, Profit Factor 0,58 bis 0,74 [VERIFIZIERT]; Höchste Trefferquote 52,5 % (H1-N24, n 4.795; Wilson-Obergrenze unter 54 %) [VERIFIZIERT]; Zahlen im Erkundungsbericht gelesen, Rohdaten nicht neu gerechnet [VERIFIZIERT]
- Verwendung in der Konsolidierung: Beleg, dass 75 % Trefferquote mit diesen Regeln nicht erreichbar war und die erreichbaren Quoten (um 50 %) nach Kosten verlieren. Die Aussage „hohe Trefferquote ≠ Vorteil“ stützt S6, nicht S4.

### S5: Trefferquote 95 % mit Funding-Carry (Perp-Wechsel)

- Cluster / Art / Beginn: CARRY / Regelfamilie (Gate) / 2026-10-25
- Quellen: `docs/research_lab/studien/S5_WINRATE_95_FUNDING_CARRY_PRAEREGISTRIERUNG.md`; `docs/research_lab/reports/s5_count_2026-10-25T1836Z.md`
- Daten: BTC, Funding-Historie
- Aufteilung: Zähllauf Training
- Kosten: —
- Register: kein Registerplatz belegt
- Stichprobe: zu wenige Episoden (2022 keine)
- Ergebnis: Nicht testbar: zu wenige Episoden, weil die Funding-Rate 2022 nie über 0,01 % lag.
- Urteil des Labors: not_testable
- **Prüftiefe C+, Klasse EXPLORATIV, Richtung: keine Aussage**
- Begründung: Die Studie konnte nicht rechnen; die Carry-Frage wurde später in S33-Carry und in dieser Konsolidierung (T11) anders gestellt.
- Mängel: Auslöser-Schwelle an die Funding-Rate gebunden
- Aussagen: Nicht testbar (zu wenige Episoden) [NUR BERICHTET]
- Verwendung in der Konsolidierung: Kein Beitrag.

### S6: Trefferquote 95 % mit Maker-Limits an der VWAP-Abweichung

- Cluster / Art / Beginn: FRÜH / Handelsregel (Test) / 2026-10-25
- Quellen: `docs/research_lab/studien/S6_WINRATE_95_MAKER_MEAN_REVERSION_PRAEREGISTRIERUNG.md`; `docs/research_lab/reports/s6_train_2026-10-25T2338Z.md`; `docs/research_lab/reports/s6_count_2026-10-25T2229Z.md`; `docs/research_lab/reports/s6_latency_2026-10-25T2257Z.md`
- Daten: BTC/ETH/SOL, 1m–1h
- Aufteilung: Training
- Kosten: Protokoll 1.x, Maker-Gebühren
- Register: 6 Registerplätze (S6)
- Stichprobe: Trades siehe Bericht
- Ergebnis: Nicht bestanden: Treffer 71,7–81,9 % (Training), Erwartung −0,07 bis −0,11 R; Zufallseinstiege mit gleicher Geometrie treffen genauso oft (82,0 % gegen 81,9 % bei k = 2, T = 0,15).
- Urteil des Labors: failed
- **Prüftiefe C+, Klasse BEDINGT VERWERTBAR, Richtung: negativ**
- Begründung: Das Zufallsvergleichsverfahren zeigt, dass die Trefferquote aus dem Verhältnis von Ziel zu Stop kommt. Das ist die methodisch wichtigste Lehre für die Winrate-Frage.
- Mängel: Maker-Füllung wird in der Simulation angenommen (Latenz-Bericht vorhanden)
- Aussagen: Trefferquote 72–82 %, E[R] −0,07 bis −0,11 R [NUR BERICHTET]; Zufallseinstiege mit gleicher Geometrie treffen genauso oft [NUR BERICHTET]; Zahlen in Ergebnisdatei [VERIFIZIERT]
- Verwendung in der Konsolidierung: Beleg: hohe Trefferquote ≠ Vorteil. Zählt gegen jede Winrate-Zielvorgabe.

### S7: Trendfolge-Ausbruch 3–4 R (Donchian, SMA200), BTC/ETH/SOL 4h, Positionen je Symbol

- Cluster / Art / Beginn: TREND-4H / Handelsregel (Test) / 2026-10-26
- Quellen: `docs/research_lab/studien/S7_3_4R_TRENDFOLGE_AUSBRUCH_PRAEREGISTRIERUNG.md`; `docs/research_lab/reports/s7_train_2026-10-26T1049Z.md`; `docs/research_lab/reports/s7_train_2026-10-26T1049Z.json`; `src/research_lab/konsolidierung/s7b_nachrechnung.py`
- Daten: Binance USD-M 4h BTC/ETH/SOL, 2020–2024
- Aufteilung: Training < 2023, Validierung 2023–2024, Holdout gesperrt
- Kosten: Protokoll 1.3 (Gebühr 5 bp, Schlupf 3 bp, Stop-Schlupf 5 bp je Seite) plus Funding
- Register: 2 Registerplätze (S7)
- Stichprobe: Training und Validierung: z. B. D20-T3 557 / 420 Trades
- Ergebnis: Nicht bestanden: Erwartung positiv (D20-T3 / D20-T4: Training +0,232 / +0,284 R, Validierung +0,190 / +0,243 R), Drawdown in der Validierung 30,2 / 30,8 R über der Grenze von 20 R.
- Urteil des Labors: failed
- **Prüftiefe A, Klasse BEDINGT VERWERTBAR, Richtung: positiv (Erwartung), Risikokriterium verfehlt**
- Begründung: Die gespeicherten Handelslisten wurden aus Rohkerzen exakt neu erzeugt (T1). Die Erwartung ist rechnerisch belegt, aber der Drawdown überschritt die vorab gesetzte Grenze.
- Mängel: Mehrere Positionen gleichzeitig (Drawdown 30 R); Gleiche Kerzendaten wie S7b, S25, S32 (Datenüberschneidung)
- Aussagen: Handelsliste exakt reproduziert (4.879 Trades S7/S7b, max. Abweichung 0 R) [VERIFIZIERT]; Erwartung D20-T3 / D20-T4: Training +0,232 / +0,284 R, Validierung +0,190 / +0,243 R; Drawdown Validierung 30,2 / 30,8 R [VERIFIZIERT]
- Verwendung in der Konsolidierung: Mechanik-Nachweis; führte zu S7b.

### S7b: Trendfolge-Ausbruch 3–4 R mit höchstens einer Position (BTC > ETH > SOL)

- Cluster / Art / Beginn: TREND-4H / Handelsregel (Test) / 2026-10-26
- Quellen: `docs/research_lab/studien/S7B_EINE_POSITION_PRAEREGISTRIERUNG.md`; `docs/research_lab/reports/s7b_train_2026-10-26T1305Z.md`; `docs/research_lab/reports/s7b_train_2026-10-26T1305Z.json`; `docs/research_lab/konsolidierung/ergebnisse/t01_reproduktion.json`
- Daten: Binance USD-M 4h BTC/ETH/SOL, 2020–2024
- Aufteilung: Training < 2023, Validierung 2023–2024, Holdout auf Uzis Wahl nicht benutzt
- Kosten: Protokoll 1.3 plus Funding
- Register: 2 Registerplätze (S7b)
- Stichprobe: D20-T3: Training 292, Validierung 207 Trades (D20-T4 266 / 189)
- Ergebnis: Training und Validierung bestanden (D20-T3: E +0,27 R, PF 1,45, DD 10,9 R). Kandidat, keine bestätigte Strategie, nicht für Live.
- Urteil des Labors: candidate
- **Prüftiefe A, Klasse BEDINGT VERWERTBAR, Richtung: positiv (Kandidat)**
- Begründung: Rechnung unabhängig reproduziert und gegen Kosten, Raster, Zufallseinstiege und Konzentration geprüft (T1–T9). Offen bleiben Mehrfachtest (DSR 0,78 gepoolt), Übertragung auf andere Coins (S32 negativ), Verzögerungsempfindlichkeit (Validierung −0,007 R bei einer Kerze Verzögerung) und die Auswahl der drei Coins im Nachhinein.
- Mängel: Mehrfach verbrauchte Validierung 2023–2024 (S7b, S25, S32, S7b-Makro verwenden dieselbe Handelsliste); Survivorship: BTC/ETH/SOL erst 2026 gewählt; Zufallseinstiege in SMA200-Richtung erzielen im Training schon +0,097 R (eigene Rechnung T3, K1); Kein ungesehener Abschlusstest
- Aussagen: Handelsliste reproduziert (T1) [VERIFIZIERT]; Nettoerwartung K1 Training +0,22 / Validierung +0,26 R [VERIFIZIERT]; Zufalls-p gepoolt 0,002 [VERIFIZIERT]; DSR (N=64) gepoolt 0,78 unter 0,95 [VERIFIZIERT]; Bestätigung außerhalb der Entwicklung fehlt [VERIFIZIERT]
- Verwendung in der Konsolidierung: Kernkandidat C1 (und C3, C2) der Konsolidierung.

### S7b-Makro: S7b-Makrofilter F1–F5 (Realzins, Dollar, Liquidität u. a.) als Filter auf S7b-Trades

- Cluster / Art / Beginn: TREND-4H / Filterstudie / 2026-11-03
- Quellen: `docs/research_lab/studien/S7B_MAKRO_FILTER.md`; `docs/research_lab/KONSOLEN_TEST_VORWAERTS_LOG.md`; `docs/research_lab/EINFLUSS_BAROMETER.md`
- Daten: FRED-Makroreihen, S7b-Trades 2020–2024
- Aufteilung: Training / Validierung
- Kosten: wie S7b
- Register: kein Registerplatz belegt
- Stichprobe: Trades der S7b-Liste
- Ergebnis: F5 besteht nach fünf Versuchen; Glückstest über fünf Filter p = 0,066, damit nur Kandidat für Vorwärts-Log; F1–F4 nicht bestanden.
- Urteil des Labors: candidate
- **Prüftiefe C, Klasse EXPLORATIV, Richtung: unklar (Mehrfachtest nicht bestanden)**
- Begründung: Fünf Filter an derselben Handelsliste; der Glückstest über alle fünf ist nicht bestanden. Ein Treffer nach mehreren Versuchen ist ein Hinweis, kein Beleg.
- Mängel: Fünf Versuche, Filter nach Ansicht der Ergebnisse weiterverfolgt; Gleiche Handelsliste wie S7b
- Aussagen: F5 besteht, Glückstest über fünf Filter p = 0,066 [NUR BERICHTET]
- Verwendung in der Konsolidierung: Nicht verwendet; Filter F5 läuft als Vorwärts-Log.

### S7b-Forward: S7b Papier-Vorwärtsjournal auf Live-Kerzen ab 01.11.2026 (D20-T3, D20-T4)

- Cluster / Art / Beginn: PROSPEKTIV / Prospektives Papier-Journal / 2026-11-01
- Quellen: `docs/research_lab/studien/S7B_EINE_POSITION_PRAEREGISTRIERUNG.md (Abschnitt 14)`; `Kopie des Journals (journal.jsonl, SHA-256 852cfb98…)`
- Daten: Live-4h-Kerzen BTC/ETH/SOL ab 2026-11-01 12:00
- Aufteilung: vorwärts, einmalig
- Kosten: wie S7b (Papier)
- Register: Teil der S7b-Familie
- Stichprobe: D20-T3 4 geschlossene Trades, D20-T4 3 (Stand 16.11. 13:32)
- Ergebnis: D20-T3: +2,95 / −1,06 / +2,93 / −1,06 R, netto +3,771 R, ein offener Short; D20-T4: +6,847 R; alle Trades Short. Mindestzahl laut Vorgabe 100.
- Urteil des Labors: running
- **Prüftiefe B, Klasse EXPLORATIV, Richtung: positiv (n viel zu klein)**
- Begründung: Hash-Kette lückenlos (verifiziert). Mit 4 und 3 Trades keine Aussage; die Summe liegt im Rahmen von Glück.
- Mängel: n = 4 bzw. 3; Nur Short-Trades, ein Marktabschnitt
- Aussagen: Hash-Kette lückenlos, Zahlen nachgerechnet [VERIFIZIERT]; Aussagekraft: keine [VERIFIZIERT]
- Verwendung in der Konsolidierung: Wird als beobachtet gemeldet; zählt weder für noch gegen den Kandidaten. Basis für den prospektiven Test.

### S7b-Sonde: S7b Sondenlauf 04.07.–01.11.2026 (zufällig gesehen, in der Präregistrierung vermerkt)

- Cluster / Art / Beginn: TREND-4H / Probelauf (nur berichtet) / 2026-11-01
- Quellen: `docs/research_lab/studien/S7B_EINE_POSITION_PRAEREGISTRIERUNG.md (Abschnitt 14)`
- Daten: BTC/ETH/SOL 4h, 2026-07-04 bis 2026-11-01
- Aufteilung: außerhalb der Entwicklung, aber vor dem Start gesehen
- Kosten: wie S7b
- Register: —
- Stichprobe: D20-T3 35 Trades, D20-T4 30 Trades
- Ergebnis: D20-T3: −5,8 R (−0,17 R je Trade), D20-T4: −6,1 R; Drawdown 12,1 R je Variante. In der Präregistrierung als zufällig gesehen vermerkt.
- Urteil des Labors: reported
- **Prüftiefe C, Klasse EXPLORATIV, Richtung: negativ (n klein)**
- Begründung: Außerhalb des Entwicklungszeitraums, aber nach der Ansicht nicht als Test zu zählen. Spricht gegen eine Erwartung von +0,22 R, ist mit 35 Trades aber statistisch nicht trennscharf.
- Mängel: Vorab gesehen; n = 35
- Aussagen: −0,17 R je Trade bei 35 Trades (D20-T3) [NUR BERICHTET]
- Verwendung in der Konsolidierung: Wird als Gegenindiz offen genannt; zählt nicht als Test.

### S25: Positionsgröße nach GARCH-4h-Prognose für S7b-D20-T3

- Cluster / Art / Beginn: TREND-4H / Größenregel (Test) / 2026-11-11
- Quellen: `docs/research_lab/reports/s25_run_2026-11-12T0926Z.md`; `docs/research_lab/reports/s25_run_2026-11-12T0926Z.json`; `docs/research_lab/studien/S25_GARCH_GROESSE_S7B_PRAEREGISTRIERUNG_ENTWURF.md`
- Daten: S7b-Handelsliste D20-T3, GARCH-Prognose
- Aufteilung: Training (ab Q2 2021, n 139) / Validierung (n 207)
- Kosten: Protokoll
- Register: kein Registerplatz (zählt für DSR, N = 65)
- Stichprobe: n 139 / 207
- Ergebnis: Nicht bestanden: Drawdown Validierung 11,63 R mit GARCH gegen 10,95 R fest; Placebo p 0,67; Training ebenfalls höher.
- Urteil des Labors: failed
- **Prüftiefe C+, Klasse BEDINGT VERWERTBAR, Richtung: negativ**
- Begründung: Klein, aber die Richtung ist eindeutig und deckt sich mit dem Befund, dass der ATR-Stop schon an die Schwankung anpasst.
- Mängel: Gleiche Handelsliste wie S7b; n 139 / 207
- Aussagen: Drawdown mit GARCH höher in beiden Abschnitten [NUR BERICHTET]; Zahlen in Ergebnisdatei [VERIFIZIERT]
- Verwendung in der Konsolidierung: Kein Beitrag zu C1–C3; Größenregel entfällt.

### S32: Korb-Trendfolge: S7b-D20-T3 unverändert auf Top-25-Perps ohne BTC/ETH/SOL, 4h

- Cluster / Art / Beginn: TREND-4H / Übertragungstest / 2026-11-12
- Quellen: `docs/research_lab/studien/S32_KORB_TRENDFOLGE_PRAEREGISTRIERUNG.md`; `PS5: results/s32/validierung/s32_validierung_2026-11-14.json (SHA-256 dc00bd4a…)`
- Daten: Top-25-Perps ohne BTC/ETH/SOL, 4h, 2020-07 bis 2024
- Aufteilung: Training 2020-07–2022, Validierung 2023–2024 (ein Lauf), Holdout nie geladen
- Kosten: Protokoll 1.3 plus Funding
- Register: Präregistrierung 1.0 eingefroren (PR #254, 12.11.), Familie außerhalb des Holdout-Registers
- Stichprobe: Training 4.682, Validierung 3.311 Trades
- Ergebnis: Nicht bestanden: Validierung brutto +0,023, Kosten 0,048, netto −0,026 R, Bootstrap [−0,150, +0,101], Zufalls-p 0,55; Training +0,066 R hielt nicht.
- Urteil des Labors: failed
- **Prüftiefe C+, Klasse BEDINGT VERWERTBAR, Richtung: negativ**
- Begründung: Gleiche Regel, andere Märkte, vorab eingefroren, ein einziger Validierungslauf: die einzige Teilprüfung der S7b-Regel mit unabhängigen Märkten. Ergebnis: kein Übertrag.
- Mängel: Training im Altcoin-Aufwärtsmarkt; Universum je Monat nach Handelsvolumen der 30 Vortage bestimmt, aber nur aus Symbolen mit Archivdateien: Survivorship möglich; Nur teilweise unabhängig von BTC/ETH/SOL (gleiche Jahre, korrelierte Märkte); Handelsliste lag nicht vor (nur Aggregate gelesen)
- Aussagen: netto −0,026 R, Bootstrap [−0,150, +0,101], Zufalls-p 0,55 [VERIFIZIERT]; Zahlen in Ergebnisdatei [VERIFIZIERT]
- Verwendung in der Konsolidierung: Gegenbeleg G8 gegen die Übertragbarkeit der S7b-Regel.

### S15: GARCH(1,1)-Volatilitätsprognose gegen 14-Tage-Varianz, BTC/ETH/SOL, 4h und 1d

- Cluster / Art / Beginn: PROGNOSE / Prognosestudie (ohne Trades) / 2026-11-02
- Quellen: `docs/research_lab/reports/s15_run_2026-11-02T1815Z.md`; `docs/research_lab/reports/s15_run_2026-11-02T1815Z.json`; `docs/research_lab/studien/S15_GARCH_VOLATILITAET_PRAEREGISTRIERUNG.md`
- Daten: BTC/ETH/SOL 4h und 1d
- Aufteilung: Training / Validierung 2023–2024
- Kosten: —
- Register: kein Registerplatz (Prognosestudie)
- Stichprobe: mehrere Jahre, drei Coins
- Ergebnis: 4h bestanden (QLIKE Validierung 0,522 statt 0,758, p 0,026); 1d nicht bestanden (p 0,108).
- Urteil des Labors: confirmed
- **Prüftiefe C+, Klasse BEDINGT VERWERTBAR, Richtung: keine Handelsaussage (Risikoschicht)**
- Begründung: Statistisch belegte Prognose der 4h-Schwankung; sie enthält keinen Handelsvorteil, und die Nutzung für die Positionsgröße ist in S25 nicht bestanden.
- Mängel: Kein Gewinn-Edge; Persistenz bei BTC an der Grenze
- Aussagen: 4h besser als 14-Tage-Varianz (p 0,026) [NUR BERICHTET]; Zahlen in Ergebnisdatei [VERIFIZIERT]
- Verwendung in der Konsolidierung: Nur Risikobaustein; kein Beitrag zum Nettoertrag.

### S9: CHoCH, Retest-Band, Reaktionsschluss auf 15m (Signalgruppe-Lernheft)

- Cluster / Art / Beginn: FRÜH / Regelfamilie (Gate) / 2026-10-27
- Quellen: `docs/research_lab/reports/s9_count_2026-10-27T1849Z.md`; `docs/research_lab/studien/S9_CHOCH_RETEST_PRAEREGISTRIERUNG.md`
- Daten: BTCUSDT 15m (175.392 Kerzen bis 2024-12)
- Aufteilung: Zähllauf Training
- Kosten: —
- Register: kein Registerplatz
- Stichprobe: höchstens 11 Signale statt 500
- Ergebnis: Am Machbarkeits-Gate gescheitert: höchstens 11 Signale im Training statt 500 (Validierung höchstens 6 statt 250).
- Urteil des Labors: not_testable
- **Prüftiefe C, Klasse EXPLORATIV, Richtung: keine Aussage**
- Begründung: Mechanisch übersetzte Lernheft-Regeln erzeugen zu wenige Fälle; kein Beleg in irgendeine Richtung.
- Mängel: Zu wenige Fälle; Zählfehler in der Diagnosetabelle (Spalten CHoCH bis R:R in der Validierung zählen ab 2020), vom Labor im Nachtrag vom 27.10. benannt und im Code behoben; Signalzahlen und Gate sind nicht betroffen
- Aussagen: Gate gescheitert (11 / 6 Signale statt 500 / 250) [NUR BERICHTET]; Zählfehler der Diagnosetabelle im Bericht selbst benannt, Gate unberührt [VERIFIZIERT]
- Verwendung in der Konsolidierung: Kein Beitrag.

### S10: IB-Ausbruch New York mit Retest an POC/Value-Kante

- Cluster / Art / Beginn: FRÜH / Regelfamilie (Gate) / 2026-10-28
- Quellen: `docs/research_lab/reports/s10_count_2026-10-28T0105Z.md`; `docs/research_lab/reports/s10_count_2026-10-28T0105Z.json`; `docs/research_lab/studien/S10_IB_AUSBRUCH_POC_RETEST_PRAEREGISTRIERUNG.md`
- Daten: BTC/ETH/SOL, 1m–15m
- Aufteilung: Zähllauf Training
- Kosten: —
- Register: kein Registerplatz
- Stichprobe: S10-P 241 von 500, S10-O 15
- Ergebnis: Am Machbarkeits-Gate gescheitert: S10-P 241 von 500 nötigen Signalen, S10-O 15; der IB-Filter streicht rund 70 % der Tage.
- Urteil des Labors: not_testable
- **Prüftiefe C+, Klasse EXPLORATIV, Richtung: keine Aussage**
- Begründung: Zähllauf ohne Rendite; Gate verfehlt. Eine Variante ohne Filter (S11) wurde von Uzi abgelehnt.
- Mängel: Zu wenige Fälle
- Aussagen: Gate gescheitert, Zahlen in Ergebnisdatei [VERIFIZIERT]
- Verwendung in der Konsolidierung: Kein Beitrag.

### S13: Noise-Band-Ausbruch (Intraday-Momentum nach Zarattini/Aziz/Barbon 2024), NY-Sitzung und UTC-Tag

- Cluster / Art / Beginn: FRÜH / Handelsregel (Test) / 2026-11-01
- Quellen: `docs/research_lab/reports/s13_run_2026-11-01T1844Z.md`; `docs/research_lab/reports/s13_run_2026-11-01T1844Z.json`; `docs/research_lab/studien/S13_NOISE_BAND_INTRADAY_MOMENTUM_PRAEREGISTRIERUNG.md`
- Daten: BTC/ETH/SOL 1m, 2020–2024
- Aufteilung: Training / Validierung / Walk-Forward
- Kosten: Protokoll, Stress mit doppelten Kosten
- Register: kein Registerplatz (eigene Familie)
- Stichprobe: S13-NY 1.732, S13-UTC 9.554 Trades (Training)
- Ergebnis: Nicht bestanden: beide Varianten im Training negativ nach Kosten (−0,044 / −0,042 R); S13-NY Validierung +0,030 R, aber Drawdown 29 % über der Grenze; Walk-Forward −0,021 R.
- Urteil des Labors: failed
- **Prüftiefe C+, Klasse BEDINGT VERWERTBAR, Richtung: negativ**
- Begründung: Ein publiziertes Ergebnis (SPY) überträgt sich nicht auf BTC/ETH/SOL; mit doppelten Kosten alle Abschnitte negativ.
- Mängel: Nicht einzeln nachgerechnet
- Aussagen: Training beide Varianten negativ netto [NUR BERICHTET]; Zahlen in Ergebnisdatei [VERIFIZIERT]
- Verwendung in der Konsolidierung: Negativbefund Intraday-Momentum.

### S14: Paar-Handel (Statistical Arbitrage) ETH/BTC, SOL/BTC, SOL/ETH, 1h

- Cluster / Art / Beginn: FRÜH / Handelsregel (Test) / 2026-11-01
- Quellen: `docs/research_lab/reports/s14_run_2026-11-01T2308Z.md`; `docs/research_lab/reports/s14_run_2026-11-01T2308Z.json`; `docs/research_lab/studien/S14_PAAR_HANDEL_KOINTEGRATION_PRAEREGISTRIERUNG.md`
- Daten: BTC/ETH/SOL 1h, Fenster 7 und 30 Tage
- Aufteilung: Training / Validierung / Walk-Forward
- Kosten: Protokoll
- Register: kein Registerplatz (eigene Familie)
- Stichprobe: W168: 750 / 620 Trades, W720: 232 / 195
- Ergebnis: Nicht bestanden: beide Varianten verlieren nach Kosten (W168 −0,241 / −0,357 R; W720 −0,189 / −0,209 R); Walk-Forward −0,182 R; Kointegrationsvarianten scheiterten am Zähl-Gate.
- Urteil des Labors: failed
- **Prüftiefe C+, Klasse BEDINGT VERWERTBAR, Richtung: negativ**
- Begründung: Eindeutig negativ in jedem Paar und Jahr; 57–60 % der W168-Trades enden am Stop bei 4σ.
- Mängel: Nicht einzeln nachgerechnet
- Aussagen: Beide Varianten negativ in Training und Validierung [NUR BERICHTET]; Zahlen in Ergebnisdatei [VERIFIZIERT]
- Verwendung in der Konsolidierung: Negativbefund Paarhandel.

### K1: Kosten-Schwelle 0,25 R für Plan-Journal-Pläne

- Cluster / Art / Beginn: PROSPEKTIV / Parameterstudie (beschreibend) / 2026-10-25
- Quellen: `docs/research_lab/studien/K1_KOSTEN_SCHWELLE.md`; `docs/research_lab/reports/k1_kosten_schwelle_2026-10-25.md`
- Daten: geschlossene Plan-Journal-Einträge
- Aufteilung: vorwärts
- Kosten: Protokoll 1.1 und Stressfall (doppelte Sätze)
- Register: kein Registerplatz
- Stichprobe: 2 geschlossene Pläne, 30 nötig
- Ergebnis: Zu wenige Fälle (2 geschlossene, 30 nötig); in etwa vier Wochen erneut auswerten.
- Urteil des Labors: waiting
- **Prüftiefe C, Klasse EXPLORATIV, Richtung: keine Aussage**
- Begründung: Keine Auswertung möglich. Die Studie legt Varianten vorab fest und wählt keine Grenze aus den Daten. Der Bericht enthält nur Formelrechnung (Mindest-Stopabstand je Grenze, Stressfall 1,43 % für 0,25 R) und die Prüfung der Anzeige, keine Marktdaten.
- Mängel: Zu wenige Fälle
- Aussagen: Zu wenige Fälle (2 geschlossene, 30 nötig) [NUR BERICHTET]; Mindest-Stopabstand für 0,25 R: 0,72 % (Basis) bzw. 1,43 % (doppelte Kosten), reine Formelrechnung des Berichts [NUR BERICHTET]
- Verwendung in der Konsolidierung: Kein Beitrag.

### V2: V2-Qualifizierungskampagne (1000 unabhängige Fälle)

- Cluster / Art / Beginn: INFRA / Datenkampagne / 2026-10-20
- Quellen: `Logbuch V2, Seiten unter System → Archiv V2 (nicht im Repo)`
- Daten: Live-Beobachtungen
- Aufteilung: —
- Kosten: —
- Register: —
- Stichprobe: 54 von 1000 Fällen
- Ergebnis: Am 22.10. auf Uzis Wunsch abgebrochen, 54 von 1000 unabhängigen Fällen. Zählt nicht.
- Urteil des Labors: aborted
- **Prüftiefe D, Klasse NICHT REPRODUZIERBAR, Richtung: keine Aussage**
- Begründung: Abgebrochen; Archivseiten nicht im Repo zugänglich.
- Mängel: Abgebrochen
- Aussagen: Abgebrochen bei 54 von 1000 Fällen [NUR BERICHTET]
- Verwendung in der Konsolidierung: Kein Beitrag.

### F4: Perp-Daten: 48-h-Probe der Futures-Trades neben Spot

- Cluster / Art / Beginn: INFRA / Datenprobe / 2026-10-29
- Quellen: `Logbuch F4`
- Daten: Binance Futures-Trades
- Aufteilung: —
- Kosten: —
- Register: —
- Stichprobe: 48 Stunden
- Ergebnis: Läuft bis 31.10.; prüft, ob sich Perp-Trades lückenlos sammeln lassen.
- Urteil des Labors: running
- **Prüftiefe D, Klasse EXPLORATIV, Richtung: keine Aussage**
- Begründung: Datenmachbarkeit, kein Ergebnis zur Handelbarkeit.
- Mängel: Ergebnis nicht im Logbuch nachgetragen
- Aussagen: Laufend, kein Ergebnis im Logbuch [NICHT PRÜFBAR]
- Verwendung in der Konsolidierung: Kein Beitrag.

### S20: Flip-Wahrscheinlichkeit aus der Kerzenstruktur, BTC 1h, Bruch von Swing-Linien

- Cluster / Art / Beginn: BTC-1H / Beobachtungsstudie (Prognose, ohne Trades) / 2026-11-09
- Quellen: `docs/research_lab/reports/s20_ergebnis_2026-11-11.md`; `docs/research_lab/reports/s20_evaluate_2026-11-10T2345Z.json`
- Daten: BTC 1h Binance, 2020–2024 (Datensatz-SHA-256 a9f525df…)
- Aufteilung: Training / Validierung 2023–2024
- Kosten: —
- Register: kein Registerplatz
- Stichprobe: 561 / 216 Ereignisse
- Ergebnis: Nicht bestanden: das Kerzenmodell aus 12 Merkmalen ist in der Validierung 8,3 % schlechter als das Mechanik-Modell (nur Abstand zur Linie), p 0,999. Nur etwa ein Drittel der klaren Brüche hält 24 Stunden.
- Urteil des Labors: failed
- **Prüftiefe C+, Klasse BEDINGT VERWERTBAR, Richtung: negativ**
- Begründung: Beobachtungsstudie ohne Handelsregel und ohne Kosten. Sie sagt nur: Kerzenmerkmale ordnen Brüche nicht besser als der Abstand zur Linie.
- Mängel: Keine Trades, keine Kosten; Validierung 2023–2024 wird von allen BTC-1h-Studien erneut verwendet
- Aussagen: Modell schlechter als Mechanik (−8,3 %, p 0,999) [NUR BERICHTET]; Zahlen in Ergebnisdatei [VERIFIZIERT]
- Verwendung in der Konsolidierung: Negativbefund; kein Beitrag zu einem Handelsvorteil.

### S21: Orderflow und Funding am Flip (CVD, Volumentrend, Footprint, Funding gegen den Abstand zur Linie), BTC 1h

- Cluster / Art / Beginn: BTC-1H / Beobachtungsstudie (Prognose, ohne Trades) / 2026-11-11
- Quellen: `docs/research_lab/reports/s21_ergebnis_2026-11-11.md`; `docs/research_lab/reports/s21_evaluate_2026-11-11T1438Z.json`
- Daten: BTC 1h, Ereignisse und Label aus S20
- Aufteilung: Training / Validierung 2023–2024
- Kosten: —
- Register: kein Registerplatz
- Stichprobe: Ereignisse K 561/216, F 318/216, G 308/216
- Ergebnis: Nicht bestanden: keine der drei Familien verbessert das Mechanik-Modell in der Validierung (Log-Verlust K −0,5 %, F −1,3 %, G −0,7 %; p 0,90 / 0,78 / 0,66).
- Urteil des Labors: failed
- **Prüftiefe C+, Klasse BEDINGT VERWERTBAR, Richtung: negativ**
- Begründung: Dasselbe Prüfschema wie S20 mit Orderflow- und Funding-Merkmalen; Ergebnis negativ in allen Familien.
- Mängel: Keine Trades, keine Kosten; Dritte Verwendung derselben Validierung
- Aussagen: Keine Familie verbessert das Mechanik-Modell [NUR BERICHTET]; Zahlen in Ergebnisdatei [VERIFIZIERT]
- Verwendung in der Konsolidierung: Negativbefund; Flip-Frage mit Kerze, Orderflow, Footprint und Funding ausgeschöpft.

### S22: Chart-Urteil im Rückblick: sortieren die Kerzen-Regeln R1–R5 Standard-Trades, BTC 1h

- Cluster / Art / Beginn: BTC-1H / Filterstudie (Beobachtung) / 2026-11-11
- Quellen: `docs/research_lab/studien/S22_CHART_URTEIL_RUECKBLICK_PRAEREGISTRIERUNG.md`; `PS5 (Kopie): results/s22/s22_evaluate_2026-11-11T1841Z.json`; `PS5 (Kopie): results/e0/s22_e0_2026-11-12T1227Z.json`
- Daten: BTC 1h Standard-Trades (Stop 1 ATR), Datensatz-SHA-256 9083b6ae… (gemeinsam mit S22–S28, E0, E1)
- Aufteilung: Training 2020–2022 (25.219 Momente) / Validierung 2023–2024 (17.424)
- Kosten: Bitunix-Kosten, Funding veröffentlicht
- Register: kein Registerplatz
- Stichprobe: Validierung: NEHMEN 4.228 / AUSLASSEN 13.295 Trades; Training 50.438 Zeilen
- Ergebnis: Nicht bestanden: Validierung NEHMEN −0,173 R, AUSLASSEN −0,288 R, alle −0,213 R; Abstand H1 +0,115 R (p 0,051). E0-Zerlegung: brutto −0,03 R, Kosten 0,12–0,20 R je Trade.
- Urteil des Labors: failed
- **Prüftiefe C+, Klasse BEDINGT VERWERTBAR, Richtung: negativ**
- Begründung: Trifft die Zahlen des Labors (Ergebnisdatei und Logbuch stimmen überein). Zwei Zeilen je Moment (Long/Short) überlappen stark; die Auswertung nutzt Wochenblöcke.
- Mängel: Überlappende Standard-Trades; Beobachtungsstudie ohne Registerplatz; Validierung mehrfach verbraucht
- Aussagen: NEHMEN nach Kosten −0,173 R in der Validierung [VERIFIZIERT]; Brutto etwa 0, Kosten 0,12–0,20 R je Trade (E0) [VERIFIZIERT]
- Verwendung in der Konsolidierung: Belegt: Das Chart-Urteil trennt Standard-Trades nicht nach Kosten. Brutto ist im Mittel null.

### S23: Open Interest am Flip: hält ein Bruch besser mit OI als mit dem Abstand allein, BTC 1h

- Cluster / Art / Beginn: BTC-1H / Beobachtungsstudie (Entwurf) / 2026-11-11
- Quellen: `docs/research_lab/studien/S23_OPEN_INTEREST_AM_FLIP_PRAEREGISTRIERUNG_ENTWURF.md`
- Daten: BTC 1h, Ereignisse aus S20
- Aufteilung: Training / Validierung
- Kosten: —
- Register: Entwurf 0.1, nicht eingefroren
- Stichprobe: Gate ≥ 200 / ≥ 150 Ereignisse
- Ergebnis: Noch nichts gerechnet: Entwurf mit Code und Tests, kein Zähllauf für diese Frage.
- Urteil des Labors: waiting
- **Prüftiefe D, Klasse EXPLORATIV, Richtung: keine Aussage**
- Begründung: Ungerechneter Entwurf. Die PS5-Datei s23_count gehört zur Alle-Indikatoren-Studie (heute S24).
- Mängel: Nicht gerechnet
- Aussagen: Nichts gerechnet [NUR BERICHTET]
- Verwendung in der Konsolidierung: Kein Beitrag.

### S24: Alle Indikatoren mit Historie zusammen (C/K/F/G/T/V, M1 Stimmen, M2 Logit) auf Standard-Trades, BTC 1h

- Cluster / Art / Beginn: BTC-1H / Filterstudie (Test) / 2026-11-11
- Quellen: `docs/research_lab/studien/S24_ALLE_INDIKATOREN_PRAEREGISTRIERUNG.md`; `PS5 (Kopie): results/s24/s24_evaluate_2026-11-11T2200Z.json`; `PS5 (Kopie): results/e0/s24_e0_2026-11-12T1227Z.json`
- Daten: BTC 1h Standard-Trades (Stop 1 ATR), Datensatz-SHA-256 9083b6ae… (gemeinsam mit S22–S28, E0, E1)
- Aufteilung: Training 2020–2022 / Validierung 2023–2024 (106 Wochen)
- Kosten: Bitunix: Taker 0,06 %, Schlupf 0,03 %, Stop-Schlupf 0,05 %, Funding
- Register: kein Registerplatz
- Stichprobe: 34.848 Trades in der Validierung
- Ergebnis: Nicht bestanden: M2 sortiert echt (Abstand 0,135 R, p 0,004), aber NEHMEN verliert nach Kosten −0,378 R (n 11.181); alle Trades −0,435 R; M1 Abstand 0,010 R.
- Urteil des Labors: failed
- **Prüftiefe C+, Klasse BEDINGT VERWERTBAR, Richtung: negativ (sortiert, aber nach Kosten verlustreich)**
- Begründung: Wichtigster Beleg für die Kostenwirkung: ein echter Sortiereffekt von 0,135 R reicht nicht, wenn alle Trades im Mittel −0,435 R verlieren (Kosten 0,26–0,42 R je Trade bei Stop 1 ATR).
- Mängel: Stop 1 ATR auf 1h ist gegen Gebühren zu eng; Überlappende Trades
- Aussagen: M2 Abstand 0,135 R, NEHMEN −0,378 R (n 11.181) [VERIFIZIERT]; Brutto −0,02 R, Kosten 0,26–0,42 R (E0) [VERIFIZIERT]
- Verwendung in der Konsolidierung: Zeigt: Sortieren ≠ Gewinn. Beleg für die Kostenschwelle (S27 geht daraus hervor).

### S26: Aufwand gegen Ergebnis: Absorption, Initiative und Book Sweep je 1h-Kerze, BTC

- Cluster / Art / Beginn: BTC-1H / Filterstudie (Test) / 2026-11-11
- Quellen: `docs/research_lab/studien/S26_AUFWAND_GEGEN_ERGEBNIS_PRAEREGISTRIERUNG.md`; `PS5 (Kopie): results/s26/s26_evaluate_2026-11-12T0923Z.json`
- Daten: BTC 1h, Delta aus Binance-Spot-Kerzen, Datensatz-SHA-256 9083b6ae… (gemeinsam mit S22–S28, E0, E1)
- Aufteilung: Training / Validierung 2023–2024
- Kosten: Bitunix-Kosten
- Register: kein Registerplatz
- Stichprobe: Absorption 307, Initiative 666 Trades (Validierung)
- Ergebnis: Nicht bestanden: Absorption −0,48 R (Abstand −0,05 R, p 0,69); Initiative −0,44 R (Abstand −0,00 R, p 0,56); Sweep 11/19 Treffer unter dem Gate.
- Urteil des Labors: failed
- **Prüftiefe C+, Klasse BEDINGT VERWERTBAR, Richtung: negativ**
- Begründung: Schwellen aus einem Video, runde Werte ohne Suche: kein Mehrfachtest-Problem, aber auch keine Optimierung. Kein Effekt.
- Mängel: Delta aus Kerzen statt Orderbuch; Sweep nicht testbar
- Aussagen: Absorption und Initiative ohne Abstand, nach Kosten stark negativ [VERIFIZIERT]
- Verwendung in der Konsolidierung: Negativbefund.

### S27: Alle Indikatoren (S24) auf größeren Trades: Stop 3 ATR, Ziel 6 ATR, 168 h, BTC 1h

- Cluster / Art / Beginn: BTC-1H / Filterstudie (Test) / 2026-11-11
- Quellen: `docs/research_lab/studien/S27_GROESSERE_TRADES_PRAEREGISTRIERUNG.md`; `PS5 (Kopie): results/s27/s27_evaluate_2026-11-12T0934Z.json`; `PS5 (Kopie): results/e0/s27_e0_2026-11-12T1227Z.json`
- Daten: BTC 1h, Stop 3 ATR, Ziel 6 ATR, Haltedauer 168 h, Datensatz-SHA-256 9083b6ae… (gemeinsam mit S22–S28, E0, E1)
- Aufteilung: Training / Validierung 2023–2024 (105 Wochen)
- Kosten: Bitunix-Kosten, Funding
- Register: kein Registerplatz
- Stichprobe: 34.368 Trades in der Validierung
- Ergebnis: Nicht bestanden: alle Trades −0,10 R; M1 NEHMEN −0,049 R (n 4.340, p 0,39), M2 NEHMEN −0,098 R (n 12.003, p 0,38). Folge M1: 275 Trades +0,05 R als einzige erfüllte Bedingung.
- Urteil des Labors: failed
- **Prüftiefe C+, Klasse BEDINGT VERWERTBAR, Richtung: negativ**
- Begründung: Weiter Stop senkt den Verlust je Trade von 0,44 auf 0,10 R: Die Kosten waren der Hauptgrund für S24. Brutto +0,04 R, Kosten 0,14 R. Die Stop-Weite wurde nach dem S24-Ergebnis gewählt.
- Mängel: Stop-Weite nach Ansicht von S24 gewählt; Folge-M1 275 Trades ist eine nachträgliche Teilmenge
- Aussagen: Alle Trades −0,10 R, NEHMEN −0,05 bis −0,10 R [VERIFIZIERT]; Brutto +0,04 R, Kosten 0,14 R (E0) [VERIFIZIERT]
- Verwendung in der Konsolidierung: Bestätigt: ohne Kosten bleibt auf BTC-1h-Standardtrades kein Vorteil.

### S28: Positionierung aus dem Binance-Metrics-Archiv (OI, Top-Trader, Taker-Verhältnis) auf S27-Trades, BTC 1h

- Cluster / Art / Beginn: BTC-1H / Filterstudie (Test) / 2026-11-12
- Quellen: `docs/research_lab/studien/S28_POSITIONIERUNG_METRICS_PRAEREGISTRIERUNG.md`; `PS5 (Kopie): results/s28/s28_evaluate_2026-11-12T1535Z.json`; `PS5 (Kopie): results/s28/s28_count_2026-11-12T1310Z.json`
- Daten: BTC 1h, Binance-Metrics-Archiv (Familie O), S27-Trades
- Aufteilung: Training / Validierung 2023–2024
- Kosten: Bitunix-Kosten
- Register: kein Registerplatz, Holm über 4
- Stichprobe: Validierung 17.129 Momente je Richtung (Auswertung), 17.369 im Zähllauf
- Ergebnis: Nicht bestanden: A:M2 Abstand +0,135 R, p 0,076, Holm nicht bestanden, NEHMEN −0,04 R nach Kosten; B:M1 +0,118 R (p 0,197), B:M2 −0,002 R.
- Urteil des Labors: failed
- **Prüftiefe C+, Klasse BEDINGT VERWERTBAR, Richtung: negativ**
- Begründung: Zähllauf und Auswertung nennen leicht unterschiedliche Momentzahlen (17.369 gegen 17.129; 11.950 gegen 10.938). Das ändert kein Urteil, ist aber ein Dokumentationsmangel.
- Mängel: Abweichende Fallzahlen zwischen Zähllauf und Auswertung; Zeitraum der Familie O: Training nur 80 Wochen
- Aussagen: Alle vier Varianten nicht bestanden, Holm-p ≥ 0,076 [VERIFIZIERT]
- Verwendung in der Konsolidierung: Negativbefund.

### S8: Orderflow-KI: Richtung der nächsten 5 Minuten aus Orderflow-Merkmalen (prospektiv)

- Cluster / Art / Beginn: OF-MIN / Prognosestudie (prospektiv) / 2026-10-26
- Quellen: `docs/research_lab/studien/S8_ORDERFLOW_PROGNOSE_PRAEREGISTRIERUNG.md`; `docs/research_lab/studien/S8_SEQUENCE_PLAN.json`
- Daten: BTC, S8-Minutenbalken (Merkmale 1.1 mit Volume Profile und TPO)
- Aufteilung: prospektiv
- Kosten: —
- Register: eigene Familie ohne Registerplatz
- Stichprobe: keine Auswertung
- Ergebnis: Läuft. Archivlauf 2020–2024 auf dem Mac; wird prospektiv geprüft; noch keine Auswertung.
- Urteil des Labors: running
- **Prüftiefe D, Klasse EXPLORATIV, Richtung: keine Aussage**
- Begründung: Keine Ergebnisse, nur Datenbasis. Prognosegüte, kein Nettoertrag.
- Mängel: Nicht ausgewertet
- Aussagen: Keine Auswertung vorhanden [NUR BERICHTET]
- Verwendung in der Konsolidierung: Datenbasis (S8-Minutenbalken) für S19, OF2, OFX, Move-Kalibrierung.

### S19: Orderflow-Schwellen BTC (Imbalance, Auktionsrand, Absorption, dünnes Extrem, Exhaustion)

- Cluster / Art / Beginn: OF-MIN / Prognosestudie (Lift) / 2026-11-09
- Quellen: `PS5 (Kopie): results/s19/s19_evaluate_20261110T1025Z.md`; `PS5 (Kopie): results/s19/s19_count_20261109T2349Z.json`; `docs/research_lab/studien/S19_ORDERFLOW_SCHWELLEN_BTC_PRAEREGISTRIERUNG.md`
- Daten: BTC, S8-Minutenbalken
- Aufteilung: Training / Validierung, Holm über 112 Hypothesen
- Kosten: —
- Register: Familie ohne Registerplatz
- Stichprobe: Training n bis 8.420 je Flag, Validierung n bis 5.828
- Ergebnis: Ohne Nachweis: Familien T, H, E ohne Nachweis; I, A, C am Gate nicht testbar. Einzelne Flags zeigen Lift von 2–4 Prozentpunkten, aber nicht in beiden Abschnitten Holm-signifikant.
- Urteil des Labors: no_proof (nicht im Logbuch)
- **Prüftiefe C, Klasse BEDINGT VERWERTBAR, Richtung: negativ / ohne Nachweis**
- Begründung: Gemessen wird ein Lift der Trefferwahrscheinlichkeit, keine Rendite nach Kosten. Der Nachweis scheitert schon vor den Kosten.
- Mängel: Lift statt Rendite; 112 Hypothesen, Holm nötig
- Aussagen: Keine Familie nachgewiesen (Holm über 112) [VERIFIZIERT]
- Verwendung in der Konsolidierung: Negativbefund für Footprint-/Absorptions-Schwellen.

### OF2: Orderflow-Engine nach Mentor-Modellen M1–M7, jede Session handelbar (Training 2020–2022)

- Cluster / Art / Beginn: OF-MIN / Handelsregel (Test, nur Training) / 2026-11-10
- Quellen: `docs/research_lab/studien/OF2_ORDERFLOW_ENGINE_PRAEREGISTRIERUNG.md`; `docs/research_lab/reports/bitunix/of2_training_of_trades_aa853e1.json`; `docs/research_lab/reports/bitunix/target_50usd_of2_training.json`; `PS5 (Kopie): results/of2/run_aa853e1/training.json`
- Daten: BTC, S8-Minutenbalken (Training 1.096 Tage)
- Aufteilung: nur Training 2020–2022 gerechnet; Validierung nie geöffnet
- Kosten: Bitunix Taker 0,06 % + Schlupf, Funding 0,01 %/8 h (unbestätigt)
- Register: eigene Familie außerhalb des Holdout-Registers
- Stichprobe: 56 OF-Trades in 1.096 Tagen (0,051/Tag)
- Ergebnis: Training: 56 Trades, Treffer 39 %, Ø Gewinn +1,96 R, Ø Verlust −0,83 R, Mittel +0,27 R (eigener Monatsblock-Bootstrap: 95 %-Band −0,20 bis +0,66 R, 86 % der Ziehungen positiv); Median −0,35 R, beste 5 % der Trades = 108 % der Summe, größter Rückgang 7,9 R über 671 Tage; Zufallseinstiege −0,09 R, p 0,006 (Labor).
- Urteil des Labors: not_proven (nicht im Logbuch)
- **Prüftiefe B, Klasse BEDINGT VERWERTBAR, Richtung: positiv (Training, n 56, nicht belegt)**
- Begründung: Aus der Rohliste neu ausgewertet: Mittel +0,2688 R. Weniger als 100 Trades, Gewinn von wenigen Trades getragen (13 Zielerreichungen = +35,6 R, 21 Stopps = −23,3 R), kein ungesehener Abschnitt, DSR (N=64) etwa 0,06. Die Kalibrierung der Schwellen lief auf dem Training.
- Mängel: n 56 unter dem Mindestumfang von 100; Keine Validierung; Kosten nicht bestätigt; Mehrere Registerlose nach dem Einfrieren (OFX-Suche auf derselben Engine)
- Aussagen: Mittel +0,2688 R, n 56 aus Rohliste [VERIFIZIERT]; DSR (N=64) etwa 0,06 [VERIFIZIERT]; Bitunix-Gebühren unbestätigt [ANNAHME]
- Verwendung in der Konsolidierung: Zeigt Richtung, trägt keinen Beleg. Kapital für 50 USDT/Tag bei Edge +0,27 R und 0,05 Trades/Tag: 364.000 USDT (1 % Risiko) bis 1,46 Mio. USDT (0,25 %).

### OFX: PS5-Dauerforschung: Suche nach besseren OF2-Varianten mit Sieb und Reality-Check (Training 2020–2023)

- Cluster / Art / Beginn: OF-MIN / Suchprozess (Mehrfachtest) / 2026-11-10
- Quellen: `docs/research_lab/studien/OFX_BAUPLAN.md`; `PS5 (Kopie): results/ofx/lauf1, lauf2, probe (konfigurationen.jsonl, state.json)`
- Daten: BTC, S8-Minutenbalken Training 2020–2023
- Aufteilung: Suche nur im Training; Validierung 2024 und Schlusstest 2025+ nur für Sieb-Bestandene
- Kosten: Bitunix Taker + Schlupf
- Register: eigene Familie, jede Variante zählt im Reality-Check
- Stichprobe: 27.023 Konfigurationen × 300 Filter = 8.106.900 Varianten (Stand der Kopie vom 16.11.)
- Ergebnis: Kein Kandidat: 0 von 27.023 Konfigurationen bestehen das Sieb (n ≥ 130, ≥ +0,10 R, jedes Jahr im Plus, DD ≤ 15 R, Zufall p ≤ 0,01, Nachbarn, Reality-Check). In den 135.100 Bestenlisten-Einträgen ist der Median n = 5; 216 Einträge haben n ≥ 130 und scheitern alle am Reality-Check (73 nur daran). Bestes Mittel bei n ≥ 130: +0,42 R (n 130, t 2,16); bestes t: 2,66 (+0,30 R, n 149).
- Urteil des Labors: running (Stand der Kopie vom 16.11.)
- **Prüftiefe B, Klasse BEDINGT VERWERTBAR, Richtung: negativ (Suche ohne Ergebnis)**
- Begründung: Aus dem Suchprotokoll neu gezählt (alle Zeilen, Summe der Bestandenen = 0). Das Sieb lehnt zu kleine Stichproben ab; das passt zu den Werten des Zufalls bei Millionen Varianten. Eine Behauptung wie „beste ~150 Trades +0,37 R“ (Phase-1-Bericht) hat keine Handelsliste und wurde zu Recht gestrichen.
- Mängel: Das Sieb selbst ist nur durch eigene Tests des Labors abgesichert, nicht unabhängig geprüft; Zeitrahmen 1m–1h (4h/1d aus), BTC allein; Validierung 2024 und Schlusstest 2025+ nicht berührt (kein Kandidat); Zufallsziehung mit festem Seed, nicht erschöpfendes Raster
- Aussagen: 0 bestanden bei 8,1 Mio. Varianten [VERIFIZIERT]; Bestes t bei n ≥ 130: 2,66; 73 Varianten scheitern nur am Reality-Check [VERIFIZIERT]; Kein Kandidat heißt nicht: Kein Vorteil existiert (Suchraum begrenzt) [VERIFIZIERT]
- Verwendung in der Konsolidierung: Zählt vollständig für den Mehrfachtest-Zähler der gesamten Forschung (N ≥ 26.707 Konfigurationen).

### S31: Mentor-Bootcamp-Orderflow-Regeln B1–B8, BTCUSDT 15m/1h

- Cluster / Art / Beginn: OF-MIN / Regelfamilie (Gate) / 2026-11-12
- Quellen: `docs/research_lab/studien/S31_MENTOR_REGELN_PRAEREGISTRIERUNG.md`; `docs/research_lab/studien/S31_ZAEHLLAUF_ERGEBNIS.md`; `PS5 (Kopie): results/s31/count_training.json`
- Daten: BTC 15m/1h, Training 2020–2022
- Aufteilung: Zähllauf Training
- Kosten: Bitunix-Kosten, Kostengate
- Register: eigene Familie
- Stichprobe: B1 34, B2 13, B3/B4 2, B5 1/6, B6 0, B7 18 (OF) / 80 (Preis)
- Ergebnis: Nicht prüfbar: keine Regel erreicht n ≥ 100. B1 34 Trades (+0,33 R), B2 13 (+0,44 R); B6: alle 1.958 Kandidaten am Kostengate verworfen.
- Urteil des Labors: not_testable
- **Prüftiefe C+, Klasse EXPLORATIV, Richtung: keine Aussage**
- Begründung: Zähllauf ohne Bestehensentscheidung; R-Werte bei n 13–34 sind Zufallsschwankung, keine Evidenz. B1–B5 sind OF2-Modelle, nicht doppelt zählen.
- Mängel: Gate nicht erreicht; Teilmengen von OF2
- Aussagen: Keine Regel erreicht n ≥ 100 [VERIFIZIERT]
- Verwendung in der Konsolidierung: Kein Beitrag; Teilmenge von OF2 (nicht doppelt zählen).

### S31b: Orderflow-Regeln M1–M7 (OF2) und B6/B7 auf 1h- und 4h-Kerzen, BTC

- Cluster / Art / Beginn: OF-MIN / Regelfamilie (Gate) / 2026-11-12
- Quellen: `docs/research_lab/studien/S31B_GROESSERE_ZEITRAHMEN_PRAEREGISTRIERUNG.md`; `docs/research_lab/studien/S31B_ZAEHLLAUF_ERGEBNIS.md`; `PS5 (Kopie): results/s31/countb_tf60.json`; `PS5 (Kopie): results/s31/countb_tf240.json`
- Daten: BTC 1h/4h Training 2020–2022
- Aufteilung: Zähllauf Training
- Kosten: —
- Register: eigene Familie
- Stichprobe: höchster Wert B7 1h 39 Trades (Preis-Zwilling 117)
- Ergebnis: Nicht prüfbar: keine Variante erreicht n ≥ 100 (B7 1h 39 Trades, M1 16 auf 1h, 1 auf 4h).
- Urteil des Labors: not_testable
- **Prüftiefe C+, Klasse EXPLORATIV, Richtung: keine Aussage**
- Begründung: Größere Kerzen senken die Kosten in R, aber die Signalzahl fällt stärker.
- Mängel: Gate nicht erreicht
- Aussagen: Keine Variante erreicht n ≥ 100 [VERIFIZIERT]
- Verwendung in der Konsolidierung: Kein Beitrag.

### S29: Nachspielen der Journal-Regel (Setup-Pfad-Planer rückwirkend), BTC

- Cluster / Art / Beginn: OF-MIN / Nachspielstudie / 2026-11-12
- Quellen: `/mnt/project-files/analysen/planer-nachspielen-2026-11-12/bauplan.md (Bauplan)`
- Daten: BTC (Volume-Profile nur geschätzt, Gamma fehlt)
- Aufteilung: —
- Kosten: —
- Register: —
- Stichprobe: unbekannt
- Ergebnis: Unbekannt: Laut Gedächtnis läuft der Lauf auf der PS5; keine Ergebnisdatei und kein späterer Stand bekannt.
- Urteil des Labors: running
- **Prüftiefe D, Klasse NICHT REPRODUZIERBAR, Richtung: keine Aussage**
- Begründung: Es liegt kein Ergebnis vor, das sich prüfen ließe.
- Mängel: Kein Ergebnis auffindbar
- Aussagen: Ergebnis nicht auffindbar [NICHT PRÜFBAR]
- Verwendung in der Konsolidierung: Kein Beitrag.

### L1: Lernschleife Champion/Herausforderer für die Orderflow-KI (Prognosegüte)

- Cluster / Art / Beginn: PROGNOSE / Prospektiver Entwurf / 2026-10-31
- Quellen: `docs/research_lab/studien/L1_LERNSCHLEIFE_PRAEREGISTRIERUNG.md`
- Daten: S8-Modelle, Live-Daten
- Aufteilung: prospektiv
- Kosten: —
- Register: Entwurf 0.1, Familie nicht eingetragen
- Stichprobe: keine
- Ergebnis: Entwurf: keine Auswertung, keine Ergebnisse. Gemessen würde Prognosegüte, kein Nettoertrag.
- Urteil des Labors: waiting
- **Prüftiefe C, Klasse EXPLORATIV, Richtung: keine Aussage**
- Begründung: Nur Regeln der Lernschleife.
- Mängel: Nicht gestartet
- Aussagen: Keine Ergebnisse [NUR BERICHTET]
- Verwendung in der Konsolidierung: Kein Beitrag.

### S12: Trifft die geschätzte Liquidations-Heatmap echte Liquidationen? (Kalibrierung eines Anzeigemodells)

- Cluster / Art / Beginn: PROGNOSE / Prospektive Kalibrierung / 2026-11-02
- Quellen: `docs/research_lab/studien/S12_LIQUIDATIONS_HEATMAP_KALIBRIERUNG_PRAEREGISTRIERUNG.md`
- Daten: Binance/Bybit-Liquidationen ab 02.11.2026, OI
- Aufteilung: prospektiv
- Kosten: —
- Register: prospektive Familie ohne Registerplatz
- Stichprobe: Sammler seit 02.11.2026
- Ergebnis: Version 1.0 freigegeben am 01.11.2026, Start 02.11.2026; kein Ergebnis im Repo. Keine Handelsregel.
- Urteil des Labors: running
- **Prüftiefe C, Klasse EXPLORATIV, Richtung: keine Aussage**
- Begründung: Keine Handelsregel; Ergebnis liegt nicht vor.
- Mängel: Kein Ergebnis auffindbar
- Aussagen: Kein Ergebnis auffindbar [NICHT PRÜFBAR]
- Verwendung in der Konsolidierung: Kein Beitrag.

### S30: Level-Reaktion am Kerzen-Level: Fade-Raster (12 Regeln) und Ausbruch, BTC 4h

- Cluster / Art / Beginn: LEVEL-INTRADAY / Handelsregel (explorativ) / 2026-11-12
- Quellen: `PS5 (Kopie): results/s30/s30_raster_train_2026-11-12.json`; `PS5 (Kopie): results/s30/s30_ausbruch_train_2026-11-12.json`; `PS5 (Kopie): results/s30/s30_ausbruch_v02_train_2026-11-12.json`; `Bericht nur am Mac: ~/Documents/TIM/evidence/E0E1-2026-11-12.md (nicht gelesen)`
- Daten: BTC 4h Training 2020–2022, Datensatz-SHA-256 9083b6ae… (gemeinsam mit S22–S28, E0, E1)
- Aufteilung: nur Training
- Kosten: Bitunix-Kosten
- Register: Entwurf nur als Artifact, nicht im Repo
- Stichprobe: Raster 12 Varianten, n je Variante 450–910
- Ergebnis: Nicht bestanden: Fade-Raster (12 Varianten) netto negativ, brutto etwa −0,05 R, Kosten 0,12–0,17 R; Ausbruch nur eine Variante mit n ≥ 30, netto −0,25 R.
- Urteil des Labors: failed
- **Prüftiefe C+, Klasse EXPLORATIV, Richtung: negativ**
- Begründung: Das Raster ist laut Ergebnisdatei ausdrücklich explorativ („kein_urteil“). Die Präregistrierung liegt nicht im Repo, die Vorabfestlegung ist nicht nachprüfbar. Die Richtung (negativ) ist klar.
- Mängel: Präregistrierung nicht im Repo; Raster mit 12 Varianten explorativ
- Aussagen: Raster: brutto −0,05 bis −0,06 R, Kosten 0,12–0,17 R [VERIFIZIERT]; Präregistrierungszeitpunkt [NICHT PRÜFBAR]
- Verwendung in der Konsolidierung: Negativbefund Level-Reaktion auf Kerzenebene.

### E0/E1: E0 Kosten-Zerlegung der BTC-1h-Studien (S22, S24, S27) und E1 Zählung von Level-Ereignissen

- Cluster / Art / Beginn: BTC-1H / Zerlegung (beschreibend) / 2026-11-12
- Quellen: `PS5 (Kopie): results/e0/s22_e0_2026-11-12T1227Z.json`; `PS5 (Kopie): results/e0/s24_e0_2026-11-12T1227Z.json`; `PS5 (Kopie): results/e0/s27_e0_2026-11-12T1227Z.json`; `PS5 (Kopie): results/e1_level_count.json`
- Daten: BTC 1h, Datensatz-SHA-256 9083b6ae… (gemeinsam mit S22–S28, E0, E1)
- Aufteilung: Training / Validierung
- Kosten: Bitunix-Kosten
- Register: kein Registerplatz
- Stichprobe: 50.438 / 34.848 Trades je Studie
- Ergebnis: Brutto-Mittel je Trade: S22 −0,03 R (Training) / −0,02 R (Validierung); S24 −0,03 / −0,02 R; S27 −0,01 / +0,04 R. Kosten je Trade 0,09–0,42 R.
- Urteil des Labors: reported
- **Prüftiefe C+, Klasse BEDINGT VERWERTBAR, Richtung: negativ**
- Begründung: Zerlegung ohne neue Statistik: Bruttoerwartung der Standardtrades ist null, die Kosten sind der Unterschied zwischen null und minus 0,1 bis 0,4 R.
- Mängel: Beschreibend, keine Hypothese
- Aussagen: Brutto etwa 0, Kosten 0,09–0,42 R je Trade [VERIFIZIERT]
- Verwendung in der Konsolidierung: Beleg für Aussage: Ohne Kantenvorteil frisst Kosten den Ertrag.

### S34: LVN am Wochen-VAH/VAL plus ≥ 2 σ vom Tages-VWAP, Rückkehr zum VWAP, BTC 5m

- Cluster / Art / Beginn: LEVEL-INTRADAY / Handelsregel (Test) / 2026-11-13
- Quellen: `docs/research_lab/studien/S34_LVN_VWAP_FADE_PRAEREGISTRIERUNG.md`; `PS5 (Kopie): results/s34/s34_train_2026-11-14.json`; `docs/research_lab/konsolidierung/ergebnisse/studien_kennzahlen.json`
- Daten: BTC 5m Training 2020–2023
- Aufteilung: nur Training
- Kosten: Bitunix-Kosten
- Register: eigene Familie
- Stichprobe: 53 Trades
- Ergebnis: Nicht bestanden: 53 Trades, brutto −0,02 R, netto −1,21 R je Trade (Stop im Mittel 0,20 %, Kosten 1,2 R), Bootstrap-Untergrenze −1,57 R, Zufallskontrolle p 0,47.
- Urteil des Labors: failed
- **Prüftiefe B, Klasse BELASTBAR, Richtung: negativ**
- Begründung: Aus der Handelsliste neu ausgewertet (E[R] −1,213, Kosten 1,2 R). Die Aussage ist eindeutig: der Stop ist so eng, dass die Kosten jede Kante überdecken.
- Mängel: n 53
- Aussagen: E[R] −1,213 R aus Handelsliste neu ausgewertet [VERIFIZIERT]
- Verwendung in der Konsolidierung: Negativbefund; enge Stops sind unter Kosten nicht handelbar.

### S35a: Level plus Orderflow-Bestätigung, Rückprall und Ausbruch (Extrem, VWAP-Band, Vortagsprofil), BTC/ETH/SOL 5m/15m

- Cluster / Art / Beginn: LEVEL-INTRADAY / Handelsregel (Test, 12 Varianten) / 2026-11-13
- Quellen: `docs/research_lab/studien/S35A_LEVEL_ORDERFLOW_PRAEREGISTRIERUNG.md`; `PS5 (Kopie): results/s35a/s35a_train_2026-11-14.trades.json`
- Daten: BTC/ETH/SOL 5m/15m, Training 2020–2022
- Aufteilung: nur Training
- Kosten: Bitunix-Kosten
- Register: eigene Familie
- Stichprobe: n 2.218–5.248 je Variante
- Ergebnis: Nicht bestanden: alle 12 Varianten netto negativ (−0,25 bis −0,41 R je Trade), beste E-break-15m −0,25 R (brutto +0,06 R).
- Urteil des Labors: failed
- **Prüftiefe B, Klasse BELASTBAR, Richtung: negativ**
- Begründung: Aus der Handelsliste neu ausgewertet; alle 12 Varianten negativ, Kosten 0,31–0,36 R je Trade.
- Mängel: Training nur 3 Jahre
- Aussagen: 12 Varianten E[R] −0,25…−0,41 aus Handelsliste [VERIFIZIERT]
- Verwendung in der Konsolidierung: Negativbefund Level+Orderflow auf 5m/15m.

### S36: SFP mit Orderflow-Konfluenz, HTF→Exec, Varianten M (Markt) und L (Limit), BTC/ETH/SOL

- Cluster / Art / Beginn: LEVEL-INTRADAY / Handelsregel (Test) / 2026-11-14
- Quellen: `docs/research_lab/studien/S36_SFP_PRAEREGISTRIERUNG.md`; `PS5 (Kopie): results/s36/train.trades.json`
- Daten: BTC/ETH/SOL, Training 2020–2023
- Aufteilung: nur Training
- Kosten: Bitunix-Kosten (M Markt, L Limit)
- Register: eigene Familie
- Stichprobe: SFP-alle-M 425, L 438 Trades
- Ergebnis: Nicht bestanden: M brutto +0,10 R, Kosten 0,15 R, netto −0,05 R (Untergrenze −0,22 R); L netto −0,09 R (−0,26 R).
- Urteil des Labors: failed
- **Prüftiefe B, Klasse BELASTBAR, Richtung: negativ**
- Begründung: Aus der Handelsliste neu ausgewertet (M −0,051, L −0,094). Nach Kosten knapp negativ; Bruttoerwartung klein positiv.
- Mängel: Zähllauf: alle 15 Konfigurationen unter n = 60, deshalb auf SFP gepoolt (nach dem Zähllauf, vor dem R-Wert)
- Aussagen: M −0,051 R, L −0,094 R aus Handelsliste [VERIFIZIERT]
- Verwendung in der Konsolidierung: Negativbefund SFP.

### S37: Fade-Checkliste (Flowread) Teil a ohne Gamma: Fade zum Tages-VWAP mit Vortags-VA, ±2 σ und Absorption, BTC/ETH/SOL 5m/15m

- Cluster / Art / Beginn: LEVEL-INTRADAY / Handelsregel (Gate) / 2026-11-15
- Quellen: `docs/research_lab/studien/S37_FADE_CHECKLISTE_PRAEREGISTRIERUNG.md`; `PS5 (Kopie): results/s37/s37_train_2026-11-15.trades.json`
- Daten: BTC/ETH/SOL 5m/15m, Training 2020–2022
- Aufteilung: nur Training
- Kosten: Bitunix-Kosten
- Register: eigene Familie
- Stichprobe: 1–5 Trades je Variante
- Ergebnis: Nicht prüfbar: nur 1–5 Trades je Variante, keine erfüllt die Mindestzahl.
- Urteil des Labors: not_testable
- **Prüftiefe B, Klasse EXPLORATIV, Richtung: keine Aussage**
- Begründung: Die Checkliste feuert fast nie; mit dieser Häufigkeit ist nichts prüfbar.
- Mängel: n 1–5
- Aussagen: n 1–5 je Variante aus Handelsliste [VERIFIZIERT]
- Verwendung in der Konsolidierung: Kein Beitrag.

### S38: Enger Vortag, danach Ausbruch am Folgetag (T-045/T-060/T-075), BTC/ETH/SOL 1m

- Cluster / Art / Beginn: LEVEL-INTRADAY / Handelsregel (Test) / 2026-11-15
- Quellen: `docs/research_lab/studien/S38_TIGHT_DAY_AUSBRUCH_PRAEREGISTRIERUNG.md`; `PS5 (Kopie): results/s38/s38_train_2026-11-15.trades.json`
- Daten: BTC/ETH/SOL 1m, Training 2020–2022
- Aufteilung: nur Training
- Kosten: Bitunix-Kosten
- Register: eigene Familie
- Stichprobe: T-045 191, T-060 584, T-075 982, T-alle 2.399 Trades
- Ergebnis: Nicht bestanden: netto +0,09 / +0,05 / +0,02 R je Trade, alle Bootstrap-Untergrenzen unter 0; T-alle +0,005 R.
- Urteil des Labors: failed
- **Prüftiefe B, Klasse BELASTBAR, Richtung: knapp positiv, nicht von null unterscheidbar**
- Begründung: Aus der Handelsliste neu ausgewertet (+0,087 / +0,045 / +0,020 / +0,0047). Knapp positiv, aber nicht von null unterscheidbar; keine Nachsuche an den Schwellen.
- Mängel: Training 3 Jahre; Validierung nicht geöffnet
- Aussagen: +0,087 / +0,045 / +0,020 R, Untergrenzen < 0, aus Handelsliste [VERIFIZIERT]
- Verwendung in der Konsolidierung: Hinweis ohne Beleg; nicht verwendet.

### S33-Carry: Funding-Carry BTC (Perp short gegen Spot long), Training

- Cluster / Art / Beginn: CARRY / Carry-Rechnung (Entwurf, nur Training) / 2026-11-12
- Quellen: `PS5 (Kopie): results/s33/carry_train_2026-11-12.json`; `Entwurf nur am Mac: ~/Documents/TIM/evidence/S33-*.md (nicht gelesen)`
- Daten: Binance Spot/Perp BTC, Training 2020–2022, Funding-Historie
- Aufteilung: nur Training
- Kosten: Perp- und Spot-Gebühren, Wechselregeln
- Register: keine Präregistrierung im Repo
- Stichprobe: ein Instrument
- Ergebnis: Immer in Position +8,5 % je Jahr auf beide Beine, 2022 nur +2 %; Wechselregeln kosten mehr als sie sparen; BTC-Funding im Training 85 % positiv, Mittel 0,0158 % je 8 h. Kapital für 50 USDT/Tag: rund 215.000 USDT.
- Urteil des Labors: failed
- **Prüftiefe C+, Klasse EXPLORATIV, Richtung: positiv (Kapitalrendite, kein Handelsvorteil)**
- Begründung: Ohne eingefrorene Bestehensregel; das Urteil „failed“ ist eine Lesart des Entwurfs. Die Nummer S33 wurde doppelt vergeben (Optionsflow-Entwurf am 13.11.).
- Mängel: Keine Präregistrierung im Repo; Nur Training; Nummer doppelt vergeben
- Aussagen: Nur Training gerechnet, ohne Präregistrierung [NUR BERICHTET]; Funding im Training 85 % positiv [NUR BERICHTET]
- Verwendung in der Konsolidierung: Anstoß für die eigene Carry-Prüfung T11.

### S33: Optionsflow als Filter auf S27-Trades (R1–R6) und Spannenprognose (V1–V2), BTC, vorwärts

- Cluster / Art / Beginn: OPTIONEN / Filterstudie (Entwurf, vorwärts) / 2026-11-13
- Quellen: `docs/research_lab/studien/S33_OPTIONSFLOW_FILTER_PRAEREGISTRIERUNG_ENTWURF.md`; `docs/research_lab/studien/OPTIONSFLOW_REGELKATALOG.md`; `docs/research_lab/OPTIONSFLOW_DATENVERTRAG.md`
- Daten: Deribit-Optionen ab Dienststart (keine Historie 2020–2024)
- Aufteilung: vorwärts: 60 Tage Kalibrierung ab Dienststart (frühestens ~12.01.2027), danach Testfenster
- Kosten: —
- Register: Entwurf 0.1, Holm über 8
- Stichprobe: keine
- Ergebnis: Noch nichts gerechnet: Entwurf, nicht eingefroren. Der Regelkatalog (R1–R6) besteht aus Hypothesen aus allgemeinem Wissen, keine eigene Messung.
- Urteil des Labors: waiting
- **Prüftiefe C, Klasse EXPLORATIV, Richtung: keine Aussage**
- Begründung: Reine Planung; keine Evidenz.
- Mängel: Nicht gestartet; Keine Historie
- Aussagen: Noch nichts gerechnet [NUR BERICHTET]
- Verwendung in der Konsolidierung: Kein Beitrag.

### GEX-Wand: Reaktion an Call Wall und Put Wall (Gamma, BTC)

- Cluster / Art / Beginn: OPTIONEN / Beobachtungsstudie (Entwurf, Datensammlung) / 2026-11-04
- Quellen: `docs/research_lab/studien/GEX_WAND_REAKTION_ENTWURF.md`
- Daten: Deribit-Gamma-Schnappschüsse alle 5 min ab 04.11.2026, BTC 1m
- Aufteilung: vorwärts
- Kosten: —
- Register: Entwurf ohne Registerplatz
- Stichprobe: keine
- Ergebnis: Entwurf: bis zur Datensammlung wird nichts ausgewertet und nichts angepasst.
- Urteil des Labors: waiting
- **Prüftiefe C, Klasse EXPLORATIV, Richtung: keine Aussage**
- Begründung: Nur Plan.
- Mängel: Nicht gestartet
- Aussagen: Keine Auswertung [NUR BERICHTET]
- Verwendung in der Konsolidierung: Kein Beitrag.

### S16: Funding-Extreme als Kontraindikator (Verteilung)

- Cluster / Art / Beginn: PROGNOSE / Beobachtungsstudie (Verteilung, Papier) / 2026-11-06
- Quellen: `docs/research_lab/reports/s16_result_2026-11-06.md`; `docs/research_lab/reports/s16_result_2026-11-06.json`; `docs/research_lab/studien/S16_FUNDING_EXTREME_ALS_KONTRAINDIKATOR_VERTEILUNG_PRAEREGISTRIERUNG_ENTWURF.md`
- Daten: BTC/ETH/SOL 1h, Funding 2020–2024 (Datensatz-SHA-256 38c92dce…)
- Aufteilung: Training / Validierung (Holdout nicht geladen)
- Kosten: — (Verteilung, keine Trades)
- Register: Version 1.0, Code eingefroren Commit 41ca70f5, Holm über 4
- Stichprobe: oben 523, unten 815 Ereignisse (entclustert)
- Ergebnis: NICHT BESTANDEN: nur oben/Rückschlag in der Validierung Holm-signifikant (Δ −0,74 Prozentpunkte), im Training nicht (p 0,063); Renditevergleiche nirgends signifikant.
- Urteil des Labors: failed
- **Prüftiefe C, Klasse BEDINGT VERWERTBAR, Richtung: negativ**
- Begründung: Sauber eingefrorene Verteilungsstudie; der einzige Treffer verfehlt die Bestehensregel (beide Abschnitte).
- Mängel: Verteilungsstudie ohne Kosten und Trades
- Aussagen: Keine Renditewirkung, ein Rückschlag-Effekt nur in der Validierung [VERIFIZIERT]
- Verwendung in der Konsolidierung: Gegenbeleg gegen Funding-Schwellen als Signal.

### S17: Kosten in R nach Tageszeit (UTC-Stunden, Wochentage)

- Cluster / Art / Beginn: PROGNOSE / Kostenstudie (Papier) / 2026-11-07
- Quellen: `docs/research_lab/reports/s17_result_2026-11-07.md`; `docs/research_lab/reports/s17_result_2026-11-07.json`; `docs/research_lab/studien/S17_KOSTEN_IN_R_NACH_TAGESZEIT_PRAEREGISTRIERUNG_ENTWURF.md`
- Daten: BTC Spot, S8-Minutenbalken 2020–2024
- Aufteilung: Training 2020–2022 / Validierung 2023–2024, Gruppen vorab eingefroren
- Kosten: Kosten in R je Stunde
- Register: Version 1.0, Code eingefroren Commit e8a3d530
- Stichprobe: 26.047 / 17.527 Fälle
- Ergebnis: NICHT BESTANDEN: Das Muster ist stabil (Spearman 0,74–0,98), aber klein: teure minus günstige Stunden Δ 0,015 R (Training) und 0,042 R (Validierung), unter der vorab gesetzten Schwelle von 0,05 R; Sonntag minus Donnerstag Δ 0,035 / 0,119 R.
- Urteil des Labors: failed
- **Prüftiefe C, Klasse BEDINGT VERWERTBAR, Richtung: keine Handelsaussage**
- Begründung: Eine echte, aber kleine Tageszeit-Wirkung auf die Kosten. Für die Ausführung (Bitunix) bedeutet das höchstens 0,04–0,12 R Spielraum, kein Vorteil.
- Mängel: Spot-Kosten, nicht Bitunix
- Aussagen: Δ Stunden 0,015 / 0,042 R, Wochentag 0,035 / 0,119 R [VERIFIZIERT]
- Verwendung in der Konsolidierung: Nur Hinweis zur Ausführungszeit.

### S18: Kronos-Pfadfächer für BTC: Trifft die 24-Stunden-Spanne so oft, wie sie verspricht, und schlägt sie einfache Bänder?

- Cluster / Art / Beginn: PROGNOSE / Prognosestudie (prospektiv) / 2026-11-08
- Quellen: `docs/research_lab/studien/S18_KRONOS_PFADFAECHER_KALIBRIERUNG_PRAEREGISTRIERUNG_ENTWURF.md`
- Daten: BTC 1h, prospektiv ab 10.11.2026
- Aufteilung: prospektiv
- Kosten: —
- Register: Version 1.0 eingefroren mit dem Merge am 08.11.
- Stichprobe: läuft
- Ergebnis: Läuft laut Gedächtnis ab 10.11. (Ergebnis nicht vor Januar); kein Ergebnis vorhanden. Prüft keinen Richtungs- oder Gewinn-Edge.
- Urteil des Labors: running
- **Prüftiefe C, Klasse EXPLORATIV, Richtung: keine Aussage**
- Begründung: Prognose der Spanne, kein Handelssignal.
- Mängel: Läuft
- Aussagen: Kein Ergebnis [NICHT PRÜFBAR]
- Verwendung in der Konsolidierung: Kein Beitrag.

### KI1: KI-Filter vor TIM-Trades (NEHMEN/AUSLASSEN durch ein lokales Sprachmodell)

- Cluster / Art / Beginn: PROGNOSE / Filterstudie (Entwurf, prospektiv) / 2026-11-07
- Quellen: `docs/research_lab/studien/KI1_KI_FILTER_PRAEREGISTRIERUNG_ENTWURF.md`
- Daten: Papier-Journale 15m/1h/1d
- Aufteilung: prospektiv
- Kosten: Kraken-Test-Kosten
- Register: Entwurf 0.1, Version 1.0 vor erster Auswertung
- Stichprobe: keine
- Ergebnis: Entwurf: keine Ergebnisse.
- Urteil des Labors: waiting
- **Prüftiefe C, Klasse EXPLORATIV, Richtung: keine Aussage**
- Begründung: Nur Plan.
- Mängel: Nicht ausgewertet
- Aussagen: Keine Ergebnisse [NUR BERICHTET]
- Verwendung in der Konsolidierung: Kein Beitrag.

### T07: KI-Zusatznutzen gegen einfache Alternativen messen (Benchmark-Spezifikation)

- Cluster / Art / Beginn: PROGNOSE / Benchmark-Spezifikation (Entwurf) / 2026-10-22
- Quellen: `docs/research_lab/studien/KI_VERGLEICH_BENCHMARK_T07.md`
- Daten: 120 Pilotfragen über TIM-Beobachtungen
- Aufteilung: —
- Kosten: —
- Register: Entwurf
- Stichprobe: 120 Fragen geplant
- Ergebnis: Entwurf: keine Messung. Misst Antwortqualität einer KI-Auskunft, keinen Handelsvorteil.
- Urteil des Labors: waiting
- **Prüftiefe C, Klasse EXPLORATIV, Richtung: keine Aussage**
- Begründung: Kein Handelsbezug.
- Mängel: Nicht gemessen
- Aussagen: Keine Messung [NUR BERICHTET]
- Verwendung in der Konsolidierung: Kein Beitrag.

### Move-Kalibrierung: Kalibrierung des Bewegungs-Detektors (move-context 0.2): wie oft schlägt er an

- Cluster / Art / Beginn: PROGNOSE / Kalibrierung (beschreibend) / 2026-11-16
- Quellen: `docs/research_lab/MOVE_CONTEXT_KALIBRIERUNG.md`; `PS5 (Kopie): results/move-calibration-2026-11-16-v2/move_calibration.json`
- Daten: S8-Minutenbalken 2020–2024
- Aufteilung: Training 2020–2023 / Validierung 2024 (Holdout nicht gelesen)
- Kosten: keine Rendite
- Register: kein Registerplatz
- Stichprobe: 43.814 Stunden
- Ergebnis: Gewählte Regel: 1h ≥ 15× Median und mind. 1,5 %, 4h ≥ 5 σ; Training im Mittel 20,0 Bewegungen je Jahr, Validierung 2024: 13.
- Urteil des Labors: reported
- **Prüftiefe C, Klasse BEDINGT VERWERTBAR, Richtung: keine Handelsaussage**
- Begründung: Zählt nur Häufigkeiten; kein Urteil über Ergebnisse.
- Mängel: Beschreibend
- Aussagen: 20,0 je Jahr Training, 13 in 2024 [VERIFIZIERT]
- Verwendung in der Konsolidierung: Grundlage für S39.

### S39: Preisbewegungen erklären: Ergebnis nach Marktereignis-Typ (Etikett am Papier-Trade, P5)

- Cluster / Art / Beginn: PROGNOSE / Beobachtungsstudie (Typen) / 2026-11-16
- Quellen: `docs/research_lab/studien/S39_BEWEGUNG_FORTSETZUNG_UMKEHR_PRAEREGISTRIERUNG.md`; `docs/research_lab/studien/S39_BERICHT.md`
- Daten: BTC, große Bewegungen 2020–2024 (Datensatz-SHA-256 bc0e59e8…)
- Aufteilung: Training / Validierung 2024 einmal
- Kosten: —
- Register: Präregistrierung
- Stichprobe: Training 69 Bewegungen, n 14–22 je Typ; 2024 nur 11
- Ergebnis: Kein Typ belegt: kein Holm-p unter 0,05 (kleinstes 0,224); drei Typen unter der Mindestzahl von 20.
- Urteil des Labors: running
- **Prüftiefe C, Klasse EXPLORATIV, Richtung: keine Aussage**
- Begründung: Zu wenige Fälle für jede Aussage über Fortsetzung oder Umkehr.
- Mängel: n 14–22 je Typ
- Aussagen: Kein Typ belegt (Holm-p ≥ 0,224) [VERIFIZIERT]
- Verwendung in der Konsolidierung: Kein Beitrag.

### Plan-Journale: Plan-Journale (Papier) 30m/15m/1h/level/perp: Journal-Prüfung 1 (12.11.2026)

- Cluster / Art / Beginn: PROSPEKTIV / Prospektives Papier-Journal / 2026-10-23
- Quellen: `docs/research_lab/gedaechtnis/v0/journal-pruefung-2026-11-12.md`; `docs/research_lab/gedaechtnis/v0/belief_register_v0_zusammenfassung.md`
- Daten: Live-Kerzen BTC, 4 Kalenderwochen
- Aufteilung: vorwärts
- Kosten: Protokoll 1.1 (5/3/5 bp)
- Register: kein Registerplatz
- Stichprobe: 84 geschlossene Pläne
- Ergebnis: Gesamt −9,32 R (−0,111 R je Plan, KI90 −0,36 bis +0,12); ohne das Level-Journal 76 Pläne +8,39 R (+0,110 R, KI90 −0,10 bis +0,18). Score und Grade streuen nicht (alle Grade C), nicht prüfbar.
- Urteil des Labors: running
- **Prüftiefe C, Klasse EXPLORATIV, Richtung: unklar (Intervalle schließen null ein)**
- Begründung: Laut Überzeugungsregister kippt das Hauptjournal durch 27 Ausschlüsse (Korrekturdatei) von −27,6 R auf +0,9 R. Das Ergebnis hängt an dieser Auswahl und an vier Wochen.
- Mängel: 27 Ausschlüsse laut Korrekturdatei bestimmen das Vorzeichen des Hauptjournals; 4 Wochen, Papier; Alle Pläne Grade C
- Aussagen: 84 Pläne −9,32 R; 76 Pläne +8,39 R [NUR BERICHTET]; Ausschlüsse verändern das Ergebnis stark [NUR BERICHTET]
- Verwendung in der Konsolidierung: Prospektive Beobachtung ohne Beweiskraft.

### OF-Schatten: Orderflow-Schatten (Gate und Orderflow-Ausstieg) auf den Plänen 15m/1h

- Cluster / Art / Beginn: PROSPEKTIV / Prospektives Schatten-Journal / 2026-11-08
- Quellen: `docs/research_lab/studien/OF_SCHATTEN_AUSWERTUNGSREGEL.md`
- Daten: Live-Pläne BTC ab 08.11.2026 14:34
- Aufteilung: vorwärts
- Kosten: wie Journal (ungleich, siehe Bericht)
- Register: Auswertungsregel 1.2 vor Plan 30
- Stichprobe: 25 geschlossene Pläne zum Zeitpunkt der Regel
- Ergebnis: Zwischenstand von 25 Plänen: Gate NEUTRAL n 10 −5,23 R, GEGEN n 11 −4,30 R, BESTÄTIGT n 4 −1,91 R; Orderflow-Ausstieg n 25: Schatten −0,23 R gegen Journal −11,44 R (ungleiche Kosten). Alle 25 Pläne LONG in einer fallenden Marktphase.
- Urteil des Labors: running
- **Prüftiefe C, Klasse EXPLORATIV, Richtung: unklar (n 25, eine Marktphase)**
- Begründung: Die Auswertungsregel wurde nach Ansicht der 25 Zwischenstände geschrieben (offen vermerkt). Pläne sind 15m/1h-Duplikate desselben Marktgeschehens.
- Mängel: n 25, nur Long, eine Marktphase; Regel nach Ansicht der Zwischenstände; Überlappende Pläne
- Aussagen: Zwischenstände von 25 Plänen gelesen [NUR BERICHTET]
- Verwendung in der Konsolidierung: Beobachtung; zählt nicht.

### Exit-Schatten: Läufer statt festem TP3 (Schatten-Journal Exit-Varianten), Papier

- Cluster / Art / Beginn: PROSPEKTIV / Prospektives Schatten-Journal / 2026-11-04
- Quellen: `/mnt/project-files/analysen/orderflow-ziele-2026-11-04/bericht.md`
- Daten: Journale 15m/1h/30m, Spot-1m ab 27.10.
- Aufteilung: vorwärts
- Kosten: Kraken 5 bp je Seite
- Register: —
- Stichprobe: 7 Trades mit TP2
- Ergebnis: MID 1h 9 Trades: fest +3,71 R, Läufer +3,82 R; SHORT 15m 17 Trades: +0,77 / +0,77 R; 30m 23 Trades: +0,15 / +0,20 R. Nur 7 verschiedene Trades erreichten TP2.
- Urteil des Labors: running
- **Prüftiefe C, Klasse EXPLORATIV, Richtung: unklar (n 7)**
- Begründung: Bericht nennt selbst „kein Beleg, nur eine Richtung“.
- Mängel: n 7 mit TP2
- Aussagen: Bericht sagt: kein Beleg [NUR BERICHTET]
- Verwendung in der Konsolidierung: Kein Beitrag.

### Stop-Analyse-30m: Stop-Analyse der 30m-Testtrades (11 geschlossene Trades)

- Cluster / Art / Beginn: PROSPEKTIV / Fallanalyse / 2026-10-27
- Quellen: `/mnt/project-files/analysen/stop-analyse-30m-2026-10-27.md`
- Daten: Journale tim/1, struct/1, level/1, Binance 30m
- Aufteilung: —
- Kosten: ca. 140 USD je Trade
- Register: —
- Stichprobe: 11 Trades
- Ergebnis: 9 von 11 Trades endeten im Stop; bei 8 lief der Preis danach bis TP1. Hauptursache: zu enge Stops (0,1–0,15 %, Kosten 2,4–2,8 R je Stopp). Weiterer Stop verkleinert Verluste, macht sie in der Stichprobe nicht positiv.
- Urteil des Labors: reported
- **Prüftiefe C, Klasse EXPLORATIV, Richtung: negativ (n 11)**
- Begründung: Fallstudie mit 11 Trades; liefert die Begründung für Kostengate und Mindeststop.
- Mängel: n 11
- Aussagen: 9 von 11 gestoppt [NUR BERICHTET]
- Verwendung in der Konsolidierung: Beleg: Enge Stops sind unter Kosten nicht handelbar (deckt sich mit S34).

### VWAP-1W-2sigma: 1W VWAP −2σ: Wie oft wird das Band getroffen und was folgt (BTC 1h, Beschreibung)

- Cluster / Art / Beginn: LEVEL-INTRADAY / Beschreibung (keine registrierte Studie) / 2026-11-12
- Quellen: `/mnt/project-files/analysen/vwap-1w-2sigma-2026-11-12/ergebnis.md`
- Daten: BTC Spot 1h 2020–2024
- Aufteilung: Training 2020–2023 / Validierung 2024
- Kosten: keine Kosten
- Register: —
- Stichprobe: 208 / 53 Wochen
- Ergebnis: Band wird in etwa 2 von 3 Wochen berührt; als Kaufsignal allein trägt es nicht (Docht ≈ Münzwurf, Schluss darunter eher Fortsetzung), schon vor Kosten.
- Urteil des Labors: reported
- **Prüftiefe C, Klasse EXPLORATIV, Richtung: negativ vor Kosten**
- Begründung: Beschreibung ohne Kosten und ohne Bestehensregel.
- Mängel: Keine Kosten; Nicht registriert
- Aussagen: Docht ≈ Münzwurf, nicht als Signal tragfähig [NUR BERICHTET]
- Verwendung in der Konsolidierung: Kein Beitrag.

### OF2-Kostengrenze: OF2: Wie viele Trades am Tag sind am profitabelsten (Kostengrenze max_cost_r variiert)

- Cluster / Art / Beginn: OF-MIN / Erkundung (nur Training) / 2026-11-10
- Quellen: `/mnt/project-files/analysen/of2-trades-pro-tag/ergebnis_20261110.md`; `PS5 (Kopie): results/of2/sweep_kosten/sweep.json`
- Daten: BTC S8-Minutenbalken, Training 2020–2022
- Aufteilung: nur Training
- Kosten: Bitunix Taker; Maker 0,02 % (optimistisch)
- Register: —
- Stichprobe: 56–397 OF-Trades je Einstellung
- Ergebnis: Mehr Trades kosten Geld: Kostengrenze 0,15: 56 Trades +0,27 R je Trade; 0,25: 124 Trades +0,16 R (+19,4 R); 0,35: −0,05 R; ab 0,5: −0,12 R und schlechter. Beste Wahl auf denselben Daten auszusuchen sei Überanpassung (Bericht).
- Urteil des Labors: reported
- **Prüftiefe C, Klasse EXPLORATIV, Richtung: positiv knapp / sinkend mit n**
- Begründung: Erkundung auf dem Training; der Bericht warnt selbst vor Überanpassung.
- Mängel: Erkundung; Gleiche Daten wie OF2
- Aussagen: Erkundung sagt: ~1 Trade pro Woche am profitabelsten [NUR BERICHTET]
- Verwendung in der Konsolidierung: Stützt: Häufigkeit × Edge ist das Problem für 50 USDT/Tag.

### Bitunix-Edge: Bitunix-Edge Phasen 1–6: Fähigkeits-Audit, API-Prüfung, Hebel, 50-USDT-Modell (11.11.2026)

- Cluster / Art / Beginn: OF-MIN / Audit und Modellrechnung / 2026-11-11
- Quellen: `/mnt/project-files/analysen/bitunix-edge-2026-11-11/phase1-audit.md`; `/mnt/project-files/analysen/bitunix-edge-2026-11-11/phase4-6-bericht.md`; `docs/research_lab/reports/bitunix/target_50usd_of2_training.json`
- Daten: Bitunix öffentliche API (Mac), OF2-Training
- Aufteilung: —
- Kosten: Bitunix: Gebühren unbestätigt (0,06 % Taker, 0,02 % Maker nur laut Uzi), Funding 8 h, Kappe ±0,3 %
- Register: —
- Stichprobe: 56 OF2-Trades
- Ergebnis: TARGET NOT PROVEN: 56 Trades in 1.096 Tagen; pro Kalendertag +0,0137 R, 95 %-Band −0,009 bis +0,043 R; Kapital für 50 USDT/Tag 364.000 USDT (1 % Risiko) bis 1,46 Mio. (0,25 %). 200x nicht freigegeben (Liquidation vor Stop). Bitunix liefert keine historischen Trades (nur Live-Aufzeichnung).
- Urteil des Labors: reported
- **Prüftiefe C, Klasse BEDINGT VERWERTBAR, Richtung: keine Edge belegt**
- Begründung: Methodisch ehrlich (Korrekturen im Nachtrag, OFX-Zahl gestrichen). Die Modellrechnung beruht auf OF2-Training mit n 56 und ist deshalb nur eine Größenordnung.
- Mängel: Bitunix-Gebühren unbestätigt; n 56; Keine Bitunix-Historie
- Aussagen: Kapitalbedarf rechnerisch aus OF2-Training [VERIFIZIERT]; Bitunix-Gebühren 0,06 % / 0,02 % [ANNAHME]
- Verwendung in der Konsolidierung: Quelle für Abschnitt Bitunix-Übertragbarkeit.

### Kraken-Kosten: Echte Handelskosten bei Kraken (Messung 01.–04.11.2026, 22 Füllungen)

- Cluster / Art / Beginn: PROSPEKTIV / Kostenmessung (Echtgeld, klein) / 2026-11-04
- Quellen: `/mnt/project-files/analysen/kraken-kosten-2026-11-04/bericht.md`
- Daten: Kraken PF_XBTUSD, 7 Auto-Trades + 1 Minitrade
- Aufteilung: —
- Kosten: gemessen: Gebühr 5,0 bp Taker, Einstiegsschlupf −0,4 bp, Roundtrip ≈ 10 bp (Annahme 18 bp)
- Register: —
- Stichprobe: 22 Füllungen, Ordergrößen 50–85 USD
- Ergebnis: Annahmen des Protokolls sind eher zu vorsichtig; Basis Binance↔Kraken konstant 15–18 bp darunter (Börsen-Stops lösen ca. 15 bp früher aus als geplant).
- Urteil des Labors: reported
- **Prüftiefe C, Klasse BEDINGT VERWERTBAR, Richtung: keine Handelsaussage**
- Begründung: Echte Messung, aber klein, Kraken (nicht Bitunix), Mini-Ordergrößen.
- Mängel: n 22 Füllungen; Venue ≠ Bitunix
- Aussagen: Roundtrip ≈ 10 bp bei Kraken [NUR BERICHTET]; Auf Bitunix übertragbar [NICHT PRÜFBAR]
- Verwendung in der Konsolidierung: Begründet die Kostenstufe K0 (günstig); nicht für Bitunix gültig.

### Bitunix-Konto: Bitunix-Konto von Uzi, letzte 365 Tage (nur berichtet)

- Cluster / Art / Beginn: PROSPEKTIV / Realisierte Handelsbilanz (nicht zugänglich) / 2026-11-12
- Quellen: `/mnt/project-files/analysen/ziel-50usd-2026-11-12/kapitalrechnung.md (Erwähnung)`
- Daten: Bitunix-Konto, diskretionär
- Aufteilung: —
- Kosten: Gebühren 1.024 USDT
- Register: —
- Stichprobe: nicht bekannt
- Ergebnis: Netto ca. −1.900 USDT in 365 Tagen, Gebühren 1.024 USDT (laut Kapitalrechnung 12.11.). Keine Kontoauszüge zugänglich.
- Urteil des Labors: reported
- **Prüftiefe D, Klasse NICHT REPRODUZIERBAR, Richtung: negativ (nur berichtet)**
- Begründung: Die Zahl steht in einem Bericht; weder Datensatz noch Kontoauszug liegen vor. Sie ist ein diskretionäres, nicht TIM-bezogenes Konto.
- Mängel: Nicht prüfbar
- Aussagen: −1.900 USDT netto, 1.024 USDT Gebühren [NUR BERICHTET]; Zugrunde liegende Auszüge [NICHT PRÜFBAR]
- Verwendung in der Konsolidierung: Nur als Hinweis auf reale Gebührenlast; kein Beleg.

### Kraken-Echtgeldtest: Kraken-Live-Trader (Echtgeld-Test) und Journal auto.jsonl

- Cluster / Art / Beginn: PROSPEKTIV / Live-Test (nicht zugänglich) / 2026-11-01
- Quellen: `/mnt/project-files/analysen/master-analyse-mentor-2026-11-09/bericht.md (Erwähnung: 133 Zeilen, 01.–09.11.)`
- Daten: Kraken PF_XBTUSD
- Aufteilung: vorwärts
- Kosten: Kraken-gemessen
- Register: —
- Stichprobe: 133 Journalzeilen (Stand 09.11.), 7 Auto-Trades bis 04.11.
- Ergebnis: Ergebnisse nicht zugänglich (Mac-Datei). Live-Trader seit 11.11. gestoppt.
- Urteil des Labors: stopped
- **Prüftiefe D, Klasse NICHT REPRODUZIERBAR, Richtung: keine Aussage**
- Begründung: Live-Journal liegt nur auf dem Mac und wurde nicht gelesen; ein paar Trades ohnehin ohne Statistik.
- Mängel: Nicht gelesen; kleine Stichprobe
- Aussagen: Ergebnisse [NICHT PRÜFBAR]
- Verwendung in der Konsolidierung: Kein Beitrag.

### V1-Juli: TIM V1 Juli 2026: Wissenschaftliche Validierung, 72h-Abnahme, Abgleichsbericht, Orderflow-Nachprüfung 5/15/30 min und 1h/4h/24h

- Cluster / Art / Beginn: INFRA / Plattform-Validierung (Datenpipeline) / 2026-07-23
- Quellen: `docs/TIM_V1_SCIENTIFIC_VALIDATION_2026-07-23.md`; `docs/TIM_FINAL_SCIENTIFIC_RECONCILIATION_REPORT.md`; `docs/TIM_72H_ACCEPTANCE_REPORT.md`; `docs/VALIDATION_REPORT_2026-07-19.md`; `docs/ORDERFLOW_VALIDATION_PHASE4.md`; `docs/ORDERFLOW_VALIDATION_LONG.md`
- Daten: Binance Spot BTCUSDT Live-Beobachtungen Juli 2026
- Aufteilung: Forward-only, ein Fenster
- Kosten: keine
- Register: —
- Stichprobe: 165 voll validierte Fälle (22.07.), 1.339 (23.07.)
- Ergebnis: NOT_COMPLETE / NO-GO / NOT_READY_FOR_V2: 1-Minuten-Abdeckung 42,6 % (22.07.) bzw. 60,7 % (23.07.); 1.339 von 1.000 geforderten Fällen erreicht, aber 63 ungeklärte Datenlücken, OUTPUT_HASH_MISMATCH. Keine Handelsaussage: „Papier-Stichproben dürfen nicht als Edge gelesen werden“.
- Urteil des Labors: reported
- **Prüftiefe C, Klasse BEDINGT VERWERTBAR, Richtung: keine Handelsaussage**
- Begründung: Prüft Datenpipeline und Provenienz, nicht Profitabilität. Als Edge-Beleg ungültig, als Datenqualitätsnachweis nützlich: Juli-Daten haben große Lücken.
- Mängel: Datenlücken 39–57 %; Keine Kosten, keine Handelsregel
- Aussagen: Datenabdeckung 42,6 % / 60,7 % [VERIFIZIERT]; Kein Edge-Beleg enthalten [VERIFIZIERT]
- Verwendung in der Konsolidierung: Nur als Warnung, dass Live-Juli-Daten nicht als Test taugen.

### tim-master-P1: tim-master: P1 Plan-Journal mit Evidenz-Gate (Software, 23.10.2026)

- Cluster / Art / Beginn: INFRA / Software-Abnahme / 2026-10-23
- Quellen: `tim-master: evidence/claude-p1-journal-evidence-gate.md`; `tim-master: docs/ACCEPTANCE.md`
- Daten: —
- Aufteilung: —
- Kosten: Protokoll 1.1
- Register: —
- Stichprobe: 108 gezielte Tests grün
- Ergebnis: STATUS: IMPLEMENTED + TESTED (isoliert), nicht integriert, nicht runtime-verifiziert. Befund: kein Setup mit positiver Evidenz im Register (48 Varianten, 0 Kandidaten).
- Urteil des Labors: reported
- **Prüftiefe C, Klasse BEDINGT VERWERTBAR, Richtung: keine Handelsaussage**
- Begründung: Software- und Governance-Nachweis; die Aussage „kein belegtes Setup“ stimmt mit dem Register überein.
- Mängel: Nicht integriert
- Aussagen: Register 48 Varianten, 0 Kandidaten (Stand 23.10.) [VERIFIZIERT]
- Verwendung in der Konsolidierung: Bestätigt: kein Journal-Eintrag darf als belegtes Setup gelten.

### Prüfberichte-Chart: Indikator-Prüfung (31.10./04.11.), Orderflow-Kontrolle (06.11.), Master-Analyse Mentor (09.11.), Orderflow-Research-Bewertung (28.10.), quantfinancetogo (02.11.)

- Cluster / Art / Beginn: INFRA / Prüf- und Bewertungsberichte (kein Handelstest) / 2026-10-31
- Quellen: `/mnt/project-files/analysen/indikator-pruefung-2026-11-04/bericht.md`; `/mnt/project-files/analysen/orderflow-kontrolle-2026-11-06/bericht.md`; `/mnt/project-files/analysen/master-analyse-mentor-2026-11-09/bericht.md`; `/mnt/project-files/analysen/orderflow-research-2026-10-28/bewertung.md`; `/mnt/project-files/analysen/quantfinancetogo-2026-11-02/bericht.md`
- Daten: Binance-Rohdaten, TIM-Chart
- Aufteilung: —
- Kosten: —
- Register: —
- Stichprobe: 331 Einzelprüfungen (04.11.)
- Ergebnis: Indikator-Prüfung 04.11.: 331 Prüfungen, 295 PASS, 8 FAIL (keiner ein falscher Indikator), 28 Hinweise; die Entscheidungslogik bekommt die meisten Indikatoren nicht zu sehen. Orderflow-Kontrolle 06.11.: PASS mit 3 bestätigten Code-/Doku-Fehlern. Deep-Research-Bericht belegt „keinen Edge“ und sagt das selbst.
- Urteil des Labors: reported
- **Prüftiefe C, Klasse BEDINGT VERWERTBAR, Richtung: keine Handelsaussage**
- Begründung: Prüfen Implementierung, Daten und Quellen, keine Handelsergebnisse.
- Mängel: Nicht einzeln nachgerechnet
- Aussagen: 295 von 331 Prüfungen PASS [NUR BERICHTET]
- Verwendung in der Konsolidierung: Stützt Datenqualität der Indikatoren; kein Edge-Beleg.

### Überzeugungsregister: TIM-Gedächtnis: Überzeugungsregister v0 (253 Aussagen, 12.11.2026) und Aussagenliste

- Cluster / Art / Beginn: INFRA / Meta-Inventur / 2026-11-12
- Quellen: `docs/research_lab/gedaechtnis/v0/belief_register_v0_zusammenfassung.md`; `docs/research_lab/gedaechtnis/aussagen.jsonl`
- Daten: Repo, Studienberichte, externe Quellen
- Aufteilung: —
- Kosten: —
- Register: —
- Stichprobe: 253 Aussagen (64 Live-Regeln, 99 Forschung, 90 extern)
- Ergebnis: Kernbefund: Keine einzige Live-Regel stützt sich auf eine bestandene Studie; 7 Live-Regeln sind widerlegt; mehr als 150 Prüfungen auf BTC 2020–2024 ohne fortlaufenden Gesamtzähler; Validierung 2023–2024 mehrfach verbraucht (S7b, S9, S13–S27, OF2).
- Urteil des Labors: reported
- **Prüftiefe C, Klasse BEDINGT VERWERTBAR, Richtung: keine Handelsaussage**
- Begründung: Interne Inventur mit Querverweis; ihr Befund deckt sich mit dieser Konsolidierung und diente der Vollständigkeitsprüfung.
- Mängel: Eigenbewertung des Labors
- Aussagen: Keine Live-Regel auf bestandener Studie [NUR BERICHTET]
- Verwendung in der Konsolidierung: Vollständigkeits- und Mehrfachtest-Quelle.

### K-C1: Konsolidierung C1: S7b-D20-T3 unverändert (BTC/ETH/SOL 4h), unabhängig neu gerechnet und geprüft (T1–T9)

- Cluster / Art / Beginn: EIGEN / Eigene Nachrechnung (Protokoll 1.0 eingefroren) / 2026-11-16
- Quellen: `docs/research_lab/konsolidierung/ergebnisse/t01_reproduktion.json`; `docs/research_lab/konsolidierung/ergebnisse/t02_kosten.json`; `docs/research_lab/konsolidierung/ergebnisse/t03_zufall_C1.json`; `docs/research_lab/konsolidierung/ergebnisse/t04_raster_C1.json`; `docs/research_lab/konsolidierung/ergebnisse/t05_komponenten.json`; `docs/research_lab/konsolidierung/ergebnisse/t08_dsr_C1.json`; `docs/research_lab/konsolidierung/ergebnisse/kriterien.json`
- Daten: Binance USD-M 4h, 2020–2024
- Aufteilung: Training < 2023 / Validierung 2023–2024; kein ungesehener Abschnitt
- Kosten: K0–K4, L1 (siehe Protokoll)
- Register: Protokoll 1.0 (Commit 1e9270a), Kandidaten vor der Bewertung festgelegt
- Stichprobe: 499 Trades (292 / 207)
- Ergebnis: K2: E[R] Training +0,207, Validierung +0,237; Zufalls-p 0,035 / 0,001; Plateau 97,5 % / 100 % der Nachbarzellen positiv; DSR (N=64) 0,42 / 0,43 (gepoolt 0,78); mit einer Kerze Verzögerung Validierung −0,007 R; Nullpunkt der Kosten bei ≈ 4,35-fachen K1-Kosten.
- Urteil des Labors: reported
- **Prüftiefe A, Klasse BEDINGT VERWERTBAR, Richtung: positiv (historisch), G7 und G8 verfehlt**
- Begründung: Alle Tests des eingefrorenen Protokolls gelaufen, nichts weggelassen. G7 (Mehrfachtest) und G8 (Übertragung) scheitern; deshalb nur Stufe 2.
- Mängel: Kein ungesehener Abschlusstest; Survivorship BTC/ETH/SOL; Gleiche Daten wie S7b
- Aussagen: T1–T9 Ergebnisse siehe Dateien [VERIFIZIERT]
- Verwendung in der Konsolidierung: Kern der Abschnitte 4–6 der Studie.

### K-Carry: Konsolidierung T11: Funding-Carry BTC+ETH (Spot long, Perp short) nach Protokoll, plus Sensitivitäten

- Cluster / Art / Beginn: EIGEN / Eigene Nachrechnung / 2026-11-16
- Quellen: `docs/research_lab/konsolidierung/ergebnisse/t11_carry.json`; `docs/research_lab/konsolidierung/ergebnisse/t12_kombination.json`
- Daten: Binance Spot und USD-M 1h, Funding, 2020–2024
- Aufteilung: Training / Validierung
- Kosten: vier Füllungen, Gebühr + Schlupf; Spot-Gebühr Bitunix unbestätigt
- Register: Protokoll 1.0, Kandidat C2
- Stichprobe: 2 Instrumente
- Ergebnis: Konstante Stückzahl: Training +84,4 %/Jahr, Validierung +13,9 %/Jahr (formal bestanden, aber verdeckter Hebel: Notional ×14 BTC, ×37 ETH, ohne Nachschuss Liquidation 2020); monatlich neu abgesichert (konstantes Notional): +11,3 % / +5,3 %, gegen angenommenen Geldmarkt 0,8 % / 5,05 %.
- Urteil des Labors: reported
- **Prüftiefe A, Klasse BEDINGT VERWERTBAR, Richtung: positiv aber Kapitalrendite (nicht Edge)**
- Begründung: Das eingefrorene Protokoll („konstante Stückzahl“) erzeugt verdeckten Hebel. Das formale Ergebnis wird berichtet, die Prüfung mit konstantem Notional daneben gestellt, ohne die Kriterien zu ändern.
- Mängel: Geldmarktsatz ist Annahme; Basisspitzen ±250 bp; Bitunix-Spot-Gebühr unbestätigt
- Aussagen: Funding-Anteil positiv ca. 88 % [VERIFIZIERT]; Geldmarktsätze [ANNAHME]
- Verwendung in der Konsolidierung: Kandidat C2; Beitrag nur als Kapitalrendite.

### K-Ref: Konsolidierung T10: risikogleiche einfache Referenzen R1 (Korb Buy&Hold) und R2 (SMA200 long/flat)

- Cluster / Art / Beginn: EIGEN / Eigene Nachrechnung / 2026-11-16
- Quellen: `docs/research_lab/konsolidierung/ergebnisse/t10_referenzen.json`; `docs/research_lab/konsolidierung/ergebnisse/tagesreihen.json`
- Daten: BTC/ETH/SOL 4h/1d 2020–2024
- Aufteilung: gepoolt
- Kosten: 0,09 % je Seite auf Umschichtung
- Register: —
- Stichprobe: Tagesreihen 2020–2024
- Ergebnis: Gepoolt, auf die Tagesschwankung des Kandidaten skaliert (Hebel höchstens 3): C1 +119 %, Sharpe 1,36, Rückgang 20,9 %; R1 +113 %, Sharpe 1,28, 33,8 %; R2 +136 %, Sharpe 1,55, 25,0 %.
- Urteil des Labors: reported
- **Prüftiefe A, Klasse BEDINGT VERWERTBAR, Richtung: kein Vorsprung gegen einfache Referenz**
- Begründung: Auf denselben im Nachhinein gewählten Coins schlägt die Regel eine einfache SMA-Referenz nicht.
- Mängel: Gleiche Coins, gleiche Jahre
- Aussagen: R2 Sharpe 1,55 gegen C1 1,36 [VERIFIZIERT]
- Verwendung in der Konsolidierung: Gegenbeleg G9/G10-Kontext.

### K-Bitunix: Konsolidierung T13: Bitunix-Kerzen und Kontraktdaten gegen Binance (Übertragbarkeit)

- Cluster / Art / Beginn: EIGEN / Eigene Nachrechnung / 2026-11-16
- Quellen: `docs/research_lab/konsolidierung/ergebnisse/t13_bitunix.json`; `docs/research_lab/konsolidierung/ergebnisse/bitunix_tiefe_momentaufnahme.json`
- Daten: Bitunix Kerzen ab 2022-04-17, Tiefenschnappschuss
- Aufteilung: Zeitraum der Bitunix-Kerzen
- Kosten: Bitunix-Gebühren unbestätigt
- Register: —
- Stichprobe: 269 gegen 264 Trades, 252 gemeinsame Signale
- Ergebnis: E[R] Bitunix 0,2194 gegen Binance 0,2460 (Δ −0,027 R); Mindestkontrakt bei 1.000 USDT 100 % ausführbar; Spreads BTC 0,016 bp, ETH 0,056 bp, SOL 1,41 bp (Momentaufnahme ≈ 90 s).
- Urteil des Labors: reported
- **Prüftiefe A, Klasse BEDINGT VERWERTBAR, Richtung: kein Unterschied zu Binance**
- Begründung: Preisgleichheit der Kerzen ist belegt; Gebühren und Funding-Einheit bleiben offen. Spread-Momentaufnahme sagt nichts über Stressphasen.
- Mängel: Gebühren unbestätigt; Funding-Einheit unklar (Prozent?)
- Aussagen: Δ E[R] −0,027 R [VERIFIZIERT]; Gebühren [ANNAHME]
- Verwendung in der Konsolidierung: Abschnitt 9 (Bitunix).

### K-T15: Konsolidierung T15: Trendregel C3 (S7b-D20-T3 auf BTC/ETH) außerhalb des Entwicklungszeitraums, Binance Spot 4h 2017-08 bis 2019-12 (ein Lauf)

- Cluster / Art / Beginn: EIGEN / Eigene Nachrechnung (Zusatzprotokoll 1.1-T15) / 2026-11-16
- Quellen: `docs/research_lab/konsolidierung/ergebnisse/t15_datenaudit.json`; `docs/research_lab/konsolidierung/ergebnisse/t15_ausserhalb.json`
- Daten: Binance Spot 4h BTCUSDT/ETHUSDT 2017-08 bis 2019-12 (data.binance.vision, Prüfsummen belegt)
- Aufteilung: ein Zeitraum vor Training, Validierung und Holdout
- Kosten: K2 primär (Funding aus, keine Historie), K1 und K0 berichtet
- Register: Zusatzprotokoll 1.1-T15 (Commit ceed9f9) vor dem Laden der Daten, Code und Datenbericht vor dem Lauf festgehalten
- Stichprobe: 157 Trades (K2)
- Ergebnis: K2: E[R] +0,154 R (95-%-Band −0,056 bis +0,391), einseitiges p 0,079 (Schwelle 0,05): nicht bestätigt, Richtung positiv. K1 +0,146, K0 +0,152. Zufallseinstiege in SMA200-Richtung im Mittel +0,177 R (p 0,595). Je Jahr 2017 −0,03 / 2018 +0,15 / 2019 +0,24 R. Größter Rückgang 12,5 R. Nach Abzug des Funding-Anteils aus 2020–2024 (0,031 R) +0,123 R.
- Urteil des Labors: reported
- **Prüftiefe A, Klasse BEDINGT VERWERTBAR, Richtung: positiv, nicht signifikant**
- Begründung: Vorab festgelegter Einzellauf außerhalb des Entwicklungszeitraums mit demselben Code (T1 reproduziert die Laborlisten bit-genau). Aussagekraft begrenzt (n 157, Power etwa 50 %), Spot statt Perpetual, Funding fehlt, nur BTC/ETH.
- Mängel: Spot statt Perpetual, kein Funding; Nur BTC/ETH, im Nachhinein gewählt; Acht Datenlücken verkürzen den Zeitraum mit Signalmöglichkeit auf etwa 19,8 Monate; Marktregime 2017–2019 anders
- Aussagen: E[R] K2 +0,154 R, n 157, p 0,079 [VERIFIZIERT]; Zufallseinstiege im Mittel +0,177 R, p 0,595 [VERIFIZIERT]; Datenbericht: 5.185 Kerzen je Symbol, 0,31 % fehlen, Prüfsummen stimmen [VERIFIZIERT]
- Verwendung in der Konsolidierung: Evidenzzeile E1b; die Stufe „außerhalb der Entwicklung bestätigt“ ist nicht erreicht.

## Nicht zugängliche oder nicht durchgesehene Quellen

- **Mac-Dateien außerhalb des Repos**: ~/Documents/TIM/evidence/S33-*.md und E0E1-2026-11-12.md (Entwürfe und Bericht zu S30/S33-Carry), ~/TIM-live/data/journal/ (Roh-Journale, auto.jsonl), Hermes-Evals; nur über Berichte des Labors bekannt, nicht selbst gelesen.
- **Kraken-Echtgeldtest und Bitunix-Konto**: Kontoauszüge, Orderlisten und Journal des Live-Traders nicht zugänglich; nur Berichte (Kraken-Kosten 04.11., Kapitalrechnung 12.11.).
- **PS5/PS4-Rohdaten**: S8-Minutenbalken und die vollen OFX-Läufe sind nur als Ergebnisdateien kopiert (OFX: Suchprotokoll vollständig gezählt); keine eigene Neuberechnung der Orderflow-Studien.
- **V2-Archiv und Hermes**: V2-Kampagnenseiten (System → Archiv V2) und Hermes-Evals nicht im Repo; ohne Handelsbezug laut Gedächtnis.
- **Repos tim-ai-platform-private und tim-master**: Dateilisten verglichen und die einschlägigen Berichte gelesen (V1-Juli, Plan-Journal-Evidenz); keine vollständige Durchsicht der 2.041 bzw. 23 Dateien. Das private Repo enthält die Forschungsdateien ebenfalls (94 Dateien nur dort, überwiegend Infrastrukturbelege).
- **GitHub-Issues und Pull-Request-Diskussionen**: nicht gelesen; Studienstände nur aus Repo, Logbuch und Ergebnisdateien.
- **Holdout ab 2025-01-01**: bewusst nicht geladen (versiegelt; Freigabe nur durch Uzi, bei S7b auch Barti).
- **S29, S12, S18, S8, L1, KI1, GEX-Wand, S33-Optionsflow, S23**: kein Ergebnis vorhanden oder noch nicht ausgewertet; Status nicht prüfbar.
- **Projektordner /mnt/project-files/analysen**: rund 70 Unterordner; die studienrelevanten (Bitunix-Edge, Ziel 50 USDT, Indikator-/Orderflow-Prüfung, Läufer, VWAP, OF2-Kostengrenze, Stop-Analyse, Kraken-Kosten) wurden gelesen, Chart-/Layout-/Control-Center-Ordner nicht.
- **Externe Quellen**: Reels, Videos und Bootcamp-Material sind keine Messungen und wurden nur über TIMs Auswertungen (Bewertungsberichte) einbezogen.
