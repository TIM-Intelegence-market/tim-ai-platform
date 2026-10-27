# S9: CHoCH → Retest-Band → Reaktionsschluss auf 15m-Kerzen (Präregistrierung, Entwurf)

| Feld | Wert |
|---|---|
| Studie | S9 |
| Version | **0.2 – Uzis Go „ja lass laufen“ am 27.10.2026 19:38 Ortszeit; Regeln eingefroren mit dem Code `src/research_lab/hypotheses/s9.py`; Registerfrage offen (Abschnitt 9)** |
| Anlass | Uzi 27.10.2026: Wissen aus dem GoatHub-Lernheft „How to identify direction (M15 · M5 · M3)“ mitnehmen, Gold in die Analyse. Auswertung des Hefts: `/mnt/project-files/goathub/education-durchgang-2026-10-27.md`, Abschnitt 8 |
| Quelle der Regeln | Community-Lernheft (XAUUSD, erfundene Beispielpreise, „keine empirisch belegte Trefferquote“). Die Regeln unten sind eine mechanische Übersetzung; wo das Heft Ermessen lässt, steht die gewählte Festlegung in 4.3 |
| Protokoll | `../PROTOKOLL.md` Version 1.3, Kriterien K1–K5 unverändert |
| Holdout | ab 2025-01-01, wird nur mit Uzis ausdrücklichem Wort geladen |

## 1. Fragestellung

Hat der Einstieg nach dem Ablauf des Hefts (CHoCH per Schlusskurs, Rückkehr in ein vorher festgelegtes Retest-Band,
Reaktionskerze schließt jenseits des Bands, Stop am Ursprungsextrem, Einstieg nur bei R:R ≥ 2) für BTCUSDT auf
15m-Kerzen nach allen Kosten einen positiven Erwartungswert, der sich von zufälligen Einstiegen gleicher Geometrie
unterscheidet?

## 2. Was TIM schon hat

- `src/dashboard/chart_live.market_structure`: BOS/MSS per Schlusskurs, Docht zählt nicht, Gleichheit ist kein Bruch,
  „Strong Low/High“ = Ursprung des Impulses. MSS entspricht dem CHoCH des Hefts. Für S9 wird diese Logik **nicht**
  wiederverwendet, sondern im Labor eigenständig und kausal nachgebaut (gleiche Regeln, eigene Tests), damit die
  Anzeige unabhängig bleibt.
- Kosten-Filter der Plan-Journale (> 0,25 R) und Protokoll 4.4 (Taker-Kosten, Funding historisch).

## 3. Daten

- BTCUSDT USD-M Perpetual, Klines 15m (Handel, Struktur) und 1d/1w (HTF-Zone, Variante Z), Funding je 8 h.
  Quelle wie Protokoll 3.1 (`data.binance.vision`, Prüfsummen). Training 2020–2022, Validierung 2023–2024.
- **Gold ist in dieser Version nicht enthalten.** `UNIVERSE` erlaubt nur BTC/ETH/SOL. Für Gold bräuchte es eine
  Protokolländerung (PAXGUSDT Spot ab 2019-09, dünne Liquidität, Handel am Wochenende anders als XAUUSD). Siehe 8.

## 4. Regeln

### 4.1 Struktur (kausal, nur geschlossene Kerzen)

1. Swing-Hoch: Kerze i, deren Hoch **strikt** über den Hochs der 2 Kerzen links und rechts liegt (Heft S. 4);
   bekannt erst beim Schluss der Kerze i + 2. Swing-Tief gespiegelt.
2. Long-Referenz = das neueste bestätigte Swing-Hoch, wenn es ein **Lower High** ist (unter dem Swing-Hoch davor).
   Sie wird **aktiv**, sobald nach ihr ein Docht unter das letzte Swing-Tief vor ihr fällt (das LL; dafür muss das
   LL nicht als Pivot bestätigt sein). Short-Referenz gespiegelt (Higher Low, aktiv nach einem höheren Hoch).
3. **Bullischer CHoCH:** Schlusskurs strikt über der aktiven Long-Referenz (Gleichheit ist kein Bruch, Docht zählt nicht).
4. Ein Impuls bekommt ein Label (Heft S. 10): Eine Referenz wird beim ersten Schluss jenseits verbraucht. Schließt der
   Kurs jenseits, bevor sie aktiv ist, ist sie ebenfalls verbraucht (kein LH → LL, kein CHoCH). Eine neue Referenz
   entsteht erst mit dem nächsten bestätigten Swing; hatte der Kurs bei ihrer Bestätigung schon jenseits geschlossen,
   zählt sie nicht.
5. Ursprungsextrem = tiefstes Tief (Long) von der Referenzkerze bis zur CHoCH-Kerze.
6. Fehlt eine 15m-Kerze, beginnt die Struktur danach von vorn (kein Swing, keine Referenz, kein Setup über eine Lücke).

### 4.2 Einstieg (Basismodell A des Hefts, M15)

1. Retest-Band, festgelegt beim CHoCH: Referenz ± b · ATR(14, 15m) der CHoCH-Kerze (ATR = einfacher Mittelwert der
   True Range der letzten 14 Kerzen).
2. Berührung: eine spätere Kerze, deren Tief (Long) die Oberkante des Bands erreicht. Berührung allein ist kein Signal.
3. Reaktionsschluss: dieselbe oder eine spätere Kerze schließt **strikt über** der Oberkante (Short: unter der Unterkante).
4. Einstieg zum Eröffnungskurs der nächsten Kerze (Taker, Slippage nach Protokoll 4.4).
5. Stop: Ursprungsextrem minus 0,1 · ATR (Long). Berührt eine Kerze nach dem CHoCH das Ursprungsextrem, auch nur mit dem
   Docht, ist die Sequenz ungültig. Liegt der Eröffnungskurs der Einstiegskerze schon jenseits des Stops, wird der Trade
   als voller Verlust gebucht (Engine-Regel `gap_entry_as_loss` ist im allgemeinen Runner aus; dann zählt das Signal
   als ungültig, Bericht nennt die Zahl).
6. Ziel: Impulsextrem = höchstes Hoch (Long) von der CHoCH-Kerze bis zur Kerze vor dem Reaktionsschluss. R:R am
   Reaktionsschluss = (Ziel − Schluss) / (Schluss − Stop). **R:R < 2 → kein Trade** (Heft S. 18). Das Ziel wird als
   dieses R-Vielfache ab dem tatsächlichen Einstieg gesetzt (Engine rechnet Ziele in R); Stop wird nie verschoben.
7. Verfall: kommt kein Reaktionsschluss innerhalb von 48 Kerzen (12 h) nach dem CHoCH, verfällt das Setup.
   Ein neuer CHoCH (gleich welcher Richtung) ersetzt ein offenes Setup.
8. Zeitstop: 96 Kerzen (24 h) nach Einstieg, Ausstieg zum Schluss. Während eine Position offen ist, werden neue Signale
   gezählt, aber nicht gehandelt (Engine).

### 4.3 Varianten (vorab, nicht nachträglich erweiterbar)

| Variante | Bandbreite b | Ziel | HTF-Zone nötig |
|---|---|---|---|
| S9-B25-I | 0,25 | Impulsextrem nach dem CHoCH (Heft: „Ziel unter dem Impulshoch“) | nein |
| S9-B50-I | 0,50 | Impulsextrem | nein |
| S9-B25-Z | 0,25 | Impulsextrem | ja: Ursprungsextrem liegt innerhalb 0,5 · ATR(14, 1d) eines Levels des letzten abgeschlossenen UTC-Tags oder der letzten abgeschlossenen ISO-Woche (Hoch, Tief, POC, VAH, VAL; Volumenprofil aus den 15m-Kerzen, Volumen gleichmäßig über die Kerzenspanne, 60 Stufen, Value Area 70 %) |
| S9-B50-Z | 0,50 | Impulsextrem | ja |

M5/M3-Varianten des Hefts werden nicht getestet (Heft: Timing-Alternativen, keine unabhängigen Belege).

## 5. Erfolgskriterien

K1–K5 aus dem Protokoll, Horizont „Short“, ausgewertet mit dem allgemeinen Runner (`src/research_lab/runner.py`,
Protokoll Abschnitt 8): Training ≥ 500 Trades, E[R] > 0, p < 0,10 gegen Zufall; Validierung ≥ 250 Trades, E[R] > 0,
p < 0,05, Profitfaktor > 1,1, Drawdown ≤ 20 %, Jahresstabilität, Walk-Forward > 0, Nachbar im Raster (b) positiv.
Zusätzlich berichtet: Ergebnis mit doppelten Kosten, Zählung je Ausschlussgrund.

### 5.1 Machbarkeits-Gate (vor jedem Ergebnis)

Ergebnisblinder Zähllauf (`scripts/research_lab_s9.py count`): nur Signale, keine Ausstiege, kein R. Eine Variante
wird nur ausgewertet, wenn sie im Training ≥ 500 und in der Validierung ≥ 250 Signale hat (untere Zahl: jeder Trade
läuft bis zum Zeitstop) und das schwächste Kalenderjahr, auf 21 Holdout-Monate hochgerechnet, ≥ 200 ergibt. Besteht
keine Variante, endet S9 hier mit dem Befund „zu selten für einen Test“; die Regeln werden danach nicht gelockert
(das wäre eine neue Studie).

## 6. Zufallsvergleich

Protokoll 7.1 (`stats/random_entry`): zufällige Einstiegskerzen im selben Abschnitt, Richtung, Stopabstand in ATR,
Ziel in R und Haltedauer gemeinsam aus den echten Trades gezogen, gleiche Ausstiege und Kosten, 10 000 Läufe,
Seed 20261028.

## 7. Bis zur Erstellung gesehene Daten

Keine Kurse für S9 ausgewertet. Gesehen: das Lernheft (erfundene Preise), die TIM-Chart-Anzeige von BOS/MSS auf
aktuellen BTC-Kerzen (Okt. 2026, liegt im Holdout-Zeitraum und wird nicht benutzt). Vorbelastung: T1-bos-15m (BOS mit
Stop 1 ATR, Ziel 2 R) ist in R4 auf denselben Daten gescheitert. Ein Probelauf der Regeln auf einer **synthetischen**
Zufallsreihe (keine Marktdaten) zeigte, dass fast alle CHoCH an R:R < 2 scheitern; das ist der Grund für das
Machbarkeits-Gate 5.1, nicht für eine Regeländerung.

## 8. Offene Punkte vor Version 1.0

1. Freigabe: Uzi „ja lass laufen“ (27.10.2026). Registerfrage siehe Abschnitt 9.
2. Gold: eigene Protokolländerung für PAXGUSDT (oder XAUUSD aus anderer Quelle) oder Gold nur als Anzeige lassen.
3. Bandbreite in ATR statt fester Preisspanne: das Heft gibt keine Breite vor („teaching example“).
4. Das deutsche Heft „GoatHub XAUUSD – Higher Timeframe Analysis“ (Heft S. 26) liegt nicht vor; die HTF-Zone in
   Variante Z ist eine eigene Festlegung.

## 9. Register

Das Protokoll-Register ist mit 58 von 60 Einträgen fast voll. Uzi entscheidet per Karte zwischen (a) eigener Familie
außerhalb des Registers wie S8 (alle vier Varianten, kein Holdout-Anspruch, Bestätigung nur prospektiv im
Papier-Journal) und (b) den letzten zwei Plätzen (S9-B50-I, S9-B50-Z). Bis dahin wird nichts registriert und nur
das ergebnisblinde Gate gerechnet.

## Änderungsprotokoll

- 0.1 (27.10.2026): Entwurf aus dem Lernheft, nichts registriert.
- 0.2 (27.10.2026): Uzis Go; Regeln präzisiert und als Code eingefroren (Referenz aktiv nach LL-Docht statt nach
  bestätigtem LL-Pivot, Ziel als R-Vielfaches, Zufallsvergleich nach Protokoll 7.1 mit 10 000 Läufen, Gate 5.1),
  vor jedem Kontakt mit Marktdaten.
