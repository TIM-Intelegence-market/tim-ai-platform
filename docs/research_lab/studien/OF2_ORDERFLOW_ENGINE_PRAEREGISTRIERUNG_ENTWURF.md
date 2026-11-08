# OF2: Orderflow-Engine nach Broncx-Modellen, jede Session handelbar (Präregistrierung, Entwurf 0.2)

| Feld | Wert |
|---|---|
| Studie | OF2 |
| Version | **0.2 – Entwurf** (08.11.2026; 0.1 vom 07.11., Uzi „go“ 18:24 Ortszeit für P0 und P1; P1b Footprint-Modelle auf Uzis Hinweis 08.11. 01:09). Freigabe 1.0 erst nach Abschluss der Kalibrierung P0 auf mehr als 40 Tagen, der Footprint-Kalibrierung auf dem Trainingsabschnitt und Uzis Wort; bis dahin kein Lauf auf Training oder Validierung |
| Auftrag | Uzi 07.11.2026: „ich brauch für TIM eine neue und überarbeitete Orderflow-Engine, mir gefällt nicht wie er tradet, ein Orderflow-Trader kann theoretisch jede Session traden“ |
| Grundlagen | Broncx-Bootcamp (193 S., vollständig gelesen 07.11.), MEGA-Bibliothek „Trading University“ (147 Dateien, Zusammenfassung `wissen/mega-orderflow-2026-11-07.md` im privaten Repo, 74 Regeln R01–R74), Orderflow-Kontrolle 06.11., S17 |
| Code | `src/research_lab/of2/` (Config, Kerzen, Level, Footprint, Modelle, Tracker, Engine, Vergleiche, CLI); Tests `tests/test_research_lab_of2.py` |
| Spezifikation | `Config().digest()` (SHA-256 über alle Parameter) steht in jeder Ergebnisdatei; Code-Stand wird vor dem ersten Datenzugriff als Commit festgehalten |
| Protokoll | `../PROTOKOLL.md` Version 1.3 |
| Holdout | ab 2025-01-01, nie geladen (S8-Store verweigert), nur mit Uzis ausdrücklichem Wort |
| Register | Eigene Familie außerhalb des Holdout-Registers (wie S8/S17), belegt keine Registerplätze |

## 1. Fragestellung

Handelt eine Orderflow-Engine, die wie ein Orderflow-Trader denkt (HTF-Ort → Regime → Liquiditätsereignis →
Orderflow-Bestätigung → Einstieg auf die Reaktion), nach Kosten besser als dieselben Orte ohne Orderflow und
besser als Zufall, und zwar in mehr als einer Session?

## 2. Hypothese und Herkunft

**H1 (Zusatznutzen des Flusses):** Die Signale der Modelle M1–M6 **mit** Orderflow-Bestätigung erzielen in der
Validierung im Mittel mindestens 0,05 R je Trade mehr netto als dieselben Signale ohne Bestätigung (Preis-Regel allein).

**H2 (jede Session):** Mindestens zwei der vier Session-Fenster sind einzeln netto positiv (Mittel ≥ 0 R, n ≥ 30).
Eine Session, die alles trägt, gilt nicht.

**H3 (gegen Zufall):** Das Mittel der bestätigten Trades schlägt zufällige Einstiege derselben Session, Richtung,
Stop-Distanz und Zielweite (Protokoll 7.1).

Herkunft: Bootcamp S. 46/51/53/78/95/102/103 (AMT-Regeln, Failed Auction, Akzeptanz mit Retest, SFP mit
gefangenen Tradern, BTC-Intraday-Modell), Dalton-80-%-Regel und Akzeptanz-Kriterien aus der Bibliothek (R29, R30),
relatives Volumen (R18), Zeitstopp (R70), Mindest-R:R (R72). Session-These von Uzi; das Bootcamp enthält keine
Session-Regel, die Bibliothek nur unbelegte Hypothesen (Abschnitt 10 der Wissensdatei).

Gegenargument: Keine TIM-Studie hat bisher nach Kosten einen Vorteil gezeigt (R0–R4, S4–S7b, S10, S13, S14).
Alle Schwellen der Quellen stammen aus ES/Bund/FX oder sind Selbstangaben; die Kalibrierung P0 (18 Spot-Tage)
zeigt, dass die Bootcamp-Schwellen auf BTC zu häufig anschlagen (Imbalance 400 % in 16–22 % der Stellen,
Relativvolumen 1,4 in ~20 % der Bars). Der Orderflow-Zusatz kann nach Kosten verschwinden.

## 3. Vorbelastung

- S8 hat Training und Validierung der S8-Minutenbalken bereits ausgewertet (Merkmale, Sequenzvergleich). Die Daten
  sind für OF2 nicht frisch; frisch ist nur der gesperrte Holdout und der spätere Schatten-Betrieb (P3).
- S17 hat die Kosten je Stunde auf denselben Daten gemessen (günstig 21–02 UTC, teuer 07–13 UTC). OF2 nutzt das
  nicht als Filter, berichtet aber je Stunde.
- S2 (Orderflow-Regeln, Beobachtung) und S4 H2 (Sweep mit Absorption): kein Edge bzw. nicht beurteilbar.
- Plan-Journal 15m/1h/1d (Papier seit 23.10.) und Kraken-Test handeln Kerzen-Pläne ohne Orderflow; sie bleiben unverändert.

## 4. Daten

- Hauptreihe: S8-Minutenbalken BTCUSDT Spot (`src/research_lab/orderflow_ml/bars.py`, Balkenversion 1.2.0) und
  S8-Tagesprofile (`DayProfile`, Volumen je Minute und Preisstufe), aus geprüften Binance-Archiven (Prüfsumme im Manifest).
- Zeitraum 2020-01-01 bis 2024-12-31 UTC. Training bis 2022-12-31, Validierung 2023-01-01 bis 2024-12-31 (Protokoll 3.2).
  Vorlauf 25 Tage je Abschnitt nur für Level und IB-Historie, deren Trades werden verworfen.
- **Abschnittsregel streng (3.2):** Ein Trade zählt zum Abschnitt seines Signals, nur wenn sein Ausstieg vor
  Abschnittsende feststand; sonst „offen“ und in keinem Abschnitt (`engine.section_trades`).
- Footprint historisch: das S8-Tagesprofil enthält je Minute und Preisstufe Kauf- und Verkaufsvolumen (Aggressor-Seite).
  Die Stufe ist je Tag etwa 0,05–0,1 % des ersten Preises (5 USD 2020, 20 USD 2022/23, 50 USD 2024) und damit 4- bis
  8-mal gröber als die P0-Messung (10 USD). Für M4–M6 werden die Stufen auf **0,1 % des Tages-Eröffnungspreises**
  zusammengefasst (`fp_step_pct`), damit 2020 und 2024 vergleichbar sind; eine Kerze braucht mindestens 4 Stufen
  (`fp_min_bins`), sonst gilt die Bestätigung als nicht lesbar (Signal nur PREIS). Ein feinerer Footprint (Weg B,
  Binance-Archive neu laden) ist eine spätere Option.
- Nicht verfügbar historisch: Perp-Delta, OI, Funding. M1–M3 nutzen Minuten-Delta und Volumen, M4–M6 den Footprint.

## 5. Regeln (fest, mit Entscheidung der Quellen-Widersprüche)

Alle Zahlen stehen in `src/research_lab/of2/config.py` (`Config`). Zeitrahmen: M1/M2 auf 30-min-Schlüssen, M3–M6 auf 15-min-Kerzen.

### 5.1 Ort (Level, nur aus abgeschlossenen Tagen und Sessions)

Vortages-Value-Area aus dem **Trade-Volumenprofil** (70 %, Einzelzeilenregel wie S8; TIM-Standard, nicht CBOT-Paarregel):
POC, VAL, VAH. Vortages-Hoch/-Tief. Naked POCs der letzten 5 Tage (POC, den kein späterer abgeschlossener Tag
durchhandelte; ein Intraday-Kontakt löscht ihn ab der nächsten Minute). Hoch/Tief der vorigen Session.

### 5.2 Sessions und Regime

Sessions UTC, überlappungsfrei zur Zuordnung: ASIA 00–07, LONDON 07–13, NY 13–21, SPAET 21–24. **Kein
Zeitfenster ist gesperrt** (auch nicht die NY-Eröffnung). Initial Balance = erste **60** Minuten jeder Session
(Entscheidung: Bibliotheksmehrheit statt Bootcamp 90; P0: ändert wenig). Regime je Session = IB-Range gegen das
Mittel der letzten 20 gleichnamigen Sessions: TREND < 0,5, RANGE > 1,5, sonst NEUTRAL; ohne Historie UNBEKANNT
(alles erlaubt). M1 nicht an TREND-Tagen, M2 und M5 nicht an RANGE-Tagen, M6 nicht an TREND-Tagen (Axia: Erschöpfung im
intakten Trend nicht faden). M3 und M4 ohne Regime-Sperre.

### 5.3 Modelle

| | M1 Failed Auction (80-%-Regel) | M2 Akzeptanz + Retest (Broncx BTC-Modell) | M3 SFP / gefangene Trader am HTF-Ort |
|---|---|---|---|
| Ort | Vortages-VAL (long) / VAH (short) | Vortages-VAH (long) / VAL (short) | VAL, VAH, POC, Tag-Hoch/-Tief, vorige Session Hoch/Tief, nPOCs |
| Auslöser | ein 30m-Schluss außerhalb der VA, danach **zwei** 30m-Schlüsse innen, der davor außen | **zwei** aufeinanderfolgende 30m-Schlüsse jenseits der Kante, der davor nicht (Akzeptanz-Kriterium d) | 15m-Kerze sticht durch das Level und schließt innen; Docht ≥ 50 % der Range, Körper ≤ 30 %; Vorkerze hatte das Level nicht berührt |
| Bestätigung (Struktur) | – | Retest der Kante innerhalb 8 Kerzen (4 h), kein 30m-Schluss zurück hinter die Kante (sonst Storno) | Folgekerze macht kein neues Extrem und schließt innen |
| **Orderflow-Bestätigung** | Delta der Extrem-Kerze außerhalb **gegen** den Trade (aggressive Verkäufer am Tief gefangen) | Summen-Delta der Akzeptanz-Kerzen **in** Trade-Richtung **und** Relativvolumen der ersten Akzeptanz-Kerze ≥ 2,0 | Delta der Sweep-Kerze **gegen** den Trade **und** Relativvolumen der Sweep-Kerze ≥ 2,0 |
| Einstieg | Stop-Order am Hoch (long) / Tief (short) der zweiten Innen-Kerze, gültig eine Kerze (Dalton; vermeidet Stop-Runs) | Limit an der Kante | Market zum Open der Minute nach der Bestätigungskerze (Entscheidung: Dante/TR, nicht Bootcamp-QM/OB) |
| Stopp | jenseits des Außen-Extrems + 0,05 % | jenseits des Swing-Extrems der Akzeptanz-Kerzen + 0,05 % | jenseits des Dochts + 0,05 % |
| Ziel | gegenüberliegende VA-Kante | nächster nPOC in Richtung, sonst Kante + eine VA-Breite | nächstes Gegenlevel mit R:R ≥ 1,5 (erstes Hindernis) |

Footprint-Modelle (P1b; Bausteine R01/R02 Imbalance und Stapel, R05 Absorption, R13 Finished/Unfinished Auction, M09/M11/M13
der Wissensdatei). Imbalance = Diagonalvergleich Kauf an Stufe b gegen Verkauf an Stufe b−1 (bzw. Verkauf an b gegen Kauf an
b+1), Verhältnis ≥ `fp_imbalance`, **beide Seiten > 0** („ohne Null“; Nullen sind ein eigener Baustein). Stapel = ≥ `fp_stack`
aufeinanderfolgende Stufen derselben Seite.

| | M4 Absorption am Level | M5 Stacked-Imbalance-Retest | M6 Stop-Run-Fade / Zeros |
|---|---|---|---|
| Ort | wie M3: VAL, VAH, POC, Tag-Hoch/-Tief, vorige Session Hoch/Tief, nPOCs | Ursprungsdrittel der Impulskerze muss ein Level derselben Liste halten oder berühren (Valtos: Imbalances am Ursprung, nie mitten im Move) | laufendes Tages-Hoch/-Tief aus den bisherigen 15m-Kerzen des Tages (mindestens 4) |
| Auslöser | 15m-Kerze berührt das Level innerhalb einer Stufe, ohne dahinter zu schließen; Vorkerze war mehr als eine Stufe entfernt; Schluss auf der Verteidigungsseite (long: Schluss ≥ Open) | Impulskerze mit Körper ≥ 60 % der Range; Zone = unteres (long) / oberes (short) Drittel | Kerze macht neues Tageshoch (-tief) und schließt wieder unter (über) dem alten Extrem |
| Bestätigung (Struktur) | Folgekerze hält das Extrem und schließt diesseits des Levels | Retest der Zone innerhalb 5 Kerzen; 15m-Schluss jenseits der Zone storniert | – (Einstieg auf den Schluss der Failure-Kerze) |
| **Orderflow-Bestätigung** | die 2 äußersten Stufen zeigen Angreifer ≥ 2 × Verteidiger (long: aggressive Verkäufer in haltende Gebote), beide Seiten gehandelt, **und** Kerzen-Delta gegen den Trade | Stapel von ≥ 3 Imbalances in Trade-Richtung innerhalb der Zone | die 2 äußersten Stufen drucken nur die jagende Seite (Gegenseite 0) **und** Kerzen-Delta in Laufrichtung (Jäger gefangen) |
| Einstieg | Market zum Open der Minute nach der Bestätigungskerze | Limit an der Zonenkante (long: Zonenoberkante) | Market zum Open der Folgeminute |
| Stopp | jenseits des Berührungs-Extrems + 0,05 % | jenseits der Zone + 0,05 % | jenseits des Run-Extrems + 0,05 % |
| Ziel | nächstes Gegenlevel mit R:R ≥ 1,5 | nächstes Gegenlevel mit R:R ≥ 1,5 | nächstes Gegenlevel mit R:R ≥ 1,5 |

Je Modell, Richtung und Tag höchstens ein Signal. Relativvolumen = Kerzenvolumen / Mittel der letzten 15 Kerzen
derselben Zeitebene (R18; P0: 2,0 trifft 7–9 % der Bars). Die Footprint-Schwellen (`fp_imbalance` 4,0, `fp_stack` 3,
`fp_absorb_ratio` 2,0, `fp_absorb_levels` 2, `fp_zero_levels` 2) sind PROVISORISCH: P0 maß mit 10-USD-Stufen 6,18x für 15m;
auf den gröberen 0,1-%-Stufen gibt es noch keine Messung. Sie werden vor Freigabe 1.0 auf dem **Trainingsabschnitt**
(2020–2022, nur Häufigkeiten, Ziel 5–15 % der Kerzen wie in P0) festgelegt und eingefroren; die Validierung bleibt unberührt.

### 5.4 Gates vor jedem Einstieg

R:R zum Ziel ≥ 1,5 (R72). Kosten-Gate: (2 × Gebühr + Slippage + Stop-Slippage) × Preis / Stop-Distanz ≤ 0,15 R.

### 5.5 Ausführung und Management (Tracker)

Fill auf 1m-Balken: Market = Open der Folgeminute; Stop/Limit = Trigger oder Open, wenn die Minute durchlückt.
Stopp vor Ziel in derselben Minute. Zeitstopp (R70): nach 8 Kerzen der Modell-Zeitebene ohne 0,5 R MFE → Ausstieg
zum Schluss der Minute. Maximal 24 h. Fill jenseits des eigenen Stopps = kein Trade.

### 5.6 Kosten

Protokoll 4.4 `BASE_COSTS`: Gebühr 0,05 % je Seite, Slippage 0,03 % je Seite, 0,05 % bei Stop-Ausführung;
Kosten in R = Kosten in Preis / Stop-Distanz (4.3). Zusätzlich beschreibend `STRESS_COSTS` (doppelt).

## 6. Messgröße und Entscheidung

- Messgröße: netto R je Trade (gross_r − fee_r − slippage_r), je Modell × Session × Bestätigung (OF / PREIS),
  je Stunde UTC, je Ausstiegsgrund.
- Mindestzahlen (Zähllauf vor jeder Auswertung): ≥ 100 bestätigte Trades je Abschnitt, ≥ 30 je bewerteter Session;
  sonst „nicht prüfbar“.
- **BESTANDEN** nur, wenn in der Validierung alle drei gelten: (1) Mittel OF ≥ +0,10 R je Trade; (2) Mittel OF −
  Mittel PREIS ≥ +0,05 R (H1); (3) H2 (zwei Sessions einzeln ≥ 0 R) und H3 (p ≤ 0,05 gegen Zufall, Holm über die
  drei Modelle, m = 3). Training ist notwendige Bedingung, nicht Beweis.
- Sonst **NICHT BESTANDEN**. Auch ein BESTANDEN führt nur in P3 (Schatten-Journal, Papier), nie direkt zu Echtgeld.

## 7. Vergleiche

1. **Preis gegen Preis + genau ein Filter** (Bewertung 28.10., N4): dieselben Signale ohne Orderflow-Bestätigung
   entstehen im selben Lauf (`confirmed` False), gleiche Zeitpunkte, gleiche Stopps und Ziele.
2. **Zufall** (Protokoll 7.1): je Abschnitt `draws` Zufallsstrategien mit gleicher Trade-Zahl, Richtung, Session,
   Stop-Distanz in %, Zielweite in R, Zeitstopp-Zeitebene; Einstiegsminute gleichverteilt im Abschnitt und in der
   Session; Seed in `Config`. **Abweichung:** 1000 statt 10 000 Strategien je Lauf (Speicher auf dem Mac,
   Streaming-Pass); p-Boden 0,001. P2 kann auf 10 000 erhöhen, wenn der Mac es trägt.
3. Beschreibend: Ergebnis je Stunde neben S17-Kosten, je Regime, je Ausstiegsgrund, MFE/MAE.

## 8. Umsetzung (vor dem Datenzugriff festgelegt)

- `python -m src.research_lab.of2 run --bars <S8-Root> --section training|validierung --out …` (streamt Tage, nie 2025).
- `python -m src.research_lab.of2 random --bars … --section … --trades <run.json> --draws 1000 --out …`.
- Training wird vollständig ausgewertet und berichtet, **bevor** die Validierung läuft. Zwischen beiden keine Änderung an `Config`.
- Look-ahead: Tests `test_engine_signals_do_not_depend_on_future_minutes` (Zukunft ändern → gleiche Signale),
  Tracker nutzt nur die gepushte Minute. Replay: ein zweiter Lauf mit gleichem Code und Daten ergibt identische Signale.

## 9. Offen (vor Freigabe 1.0)

- P0 auf mehr als 40 Tagen wiederholen (Perp-Archive ab 30.10. oder Lesezugriff Postgres); R29/R30 waren auf 18 Tagen
  gerichtet und trennten nicht. Entscheidung, ob M1 ein Mindest-Abstand des Außen-Extrems von der Kante braucht.
- Stop-Puffer 0,05 % und IB 60 min bleiben Entscheidungen ohne Daten.
- Footprint-Schwellen (Abschnitt 5.3) auf dem S8-Footprint des Trainingsabschnitts messen und einfrieren (Mac, nur lesend).
  Prüfen, ob die 0,1-%-Stufen genug Auflösung für Stapel ≥ 3 lassen; sonst Weg B (feinerer Footprint aus neu geladenen Archiven).
- Widersprüche entschieden (Abschnitt 18 der Wissensdatei): IB 60; Imbalance-Schwelle nicht genutzt (kein historischer
  Footprint); nPOC als Ziel und M3-Sweep-Level, nicht als eigener Einstieg; SFP-Einstieg am Schluss der Bestätigungskerze;
  Stop-Runs werden gefadet (M3 an markierten Levels, M6 am laufenden Tagesextrem), nicht gefolgt; Absorption mit
  hohem Angreifer-Delta und haltendem Preis (nicht „Delta nahe null“); Imbalance „ohne Null“, Nullen als eigener Baustein (M6);
  Exhaustion (R08) nicht als Auslöser: P0 fand sie in 32–42 % aller Kerzen, zu häufig.

## 10. Feste Grenzen

Nur Papier, keine Orders. Live-Trader, Plan-Journal und Kraken-Test unverändert. Holdout 2025 nur mit Uzis Wort.
Echtgeld (P4) nur nach bestandenem P3 und Uzis Wort, im Kraken-Test mit seinen Limits.

## Änderungsprotokoll

- 0.1 (07.11.2026): Entwurf nach Bootcamp- und MEGA-Auswertung; P0-Werte eingetragen (Relativvolumen 2,0; IB-Bänder 0,5/1,5).
- 0.2 (08.11.2026): Footprint aus dem S8-Tagesprofil (Stufen auf 0,1 % zusammengefasst); Modelle M4 Absorption, M5
  Stacked-Imbalance-Retest, M6 Stop-Run-Fade/Zeros; Regime-Sperren M5/M6; Zeitstopp je Signal-Zeitebene; Holm m = 6.
