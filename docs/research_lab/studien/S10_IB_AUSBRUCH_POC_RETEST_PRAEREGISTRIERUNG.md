# S10: Initial-Balance-Ausbruch mit Retest der POC-Zone nach New-York-Open (Präregistrierung, Entwurf)

| Feld | Wert |
|---|---|
| Studie | S10 |
| Version | **0.2 – Regeln eingefroren als Code (`src/research_lab/hypotheses/s10.py`), Uzis Entscheidungen vom 28.10.2026 (Abschnitt 8); nichts registriert, keine Marktdaten ausgewertet** |
| Anlass | Uzi 28.10.2026 („go“ auf den Studienvorschlag): Methode des Orderflow-Traders Fabio Valentini (YouTube „Fabervaale ENG“) für TIM prüfen. Auswertung des Kanals: `/mnt/project-files/analysen/fabervaale-2026-10-28/fabervaale-kanal.md` |
| Quelle der Regeln | Zwei Methodenvideos („The Simplest Orderflow Trading Model“, „My Signature Orderflow Model“), gelesen als Untertitel. Grundidee: Opening Range Breakout nach Toby Crabel (1990). Die Videos zeigen ausgewählte Tage ohne Kosten und ohne Gesamtstatistik; der Autor arbeitet für DeepCharts und bewirbt dessen bezahlte Indikatoren. Die Regeln unten sind eine mechanische Übersetzung; wo die Videos Ermessen lassen, steht die gewählte Festlegung in 4 und 8 |
| Protokoll | `../PROTOKOLL.md` Version 1.3, Kriterien K1–K5 unverändert |
| Holdout | ab 2025-01-01, wird nur mit Uzis ausdrücklichem Wort geladen |

## 1. Fragestellung

Hat ein Einstieg nach dem Ausbruch aus der Initial Balance (IB, erste 30 Minuten nach Eröffnung der New Yorker
Aktienbörse) beim ersten Rücksetzer in die Zone zwischen POC und Value-Area-Kante des IB-Volumenprofils, mit Stop
jenseits der gegenüberliegenden Value-Area-Kante und festem Ziel 2 R, für BTC/ETH/SOL-Perpetuals nach allen Kosten
einen positiven Erwartungswert, der sich von zufälligen Einstiegen gleicher Geometrie unterscheidet? Und verbessert
eine Absorptions-Bestätigung an der Zone (Variante O) das Ergebnis?

## 2. Was TIM schon hat und Vorbelastung

- Volumenprofil, POC und Value Area (Chart, Merkmale 1.1 der S8-Familie), Absorption/Exhaustion R1–R4
  (`docs/knowledge/ORDERFLOW_REGELN.md`, PR #439), NYSE-Kalender `src/research_lab/hypotheses/calendars.py`.
- S10 baut die Regeln im Labor eigenständig und kausal nach (eigene Tests), die Anzeige bleibt unabhängig.
- **Vorbelastung:** S7 (Trendfolge-Ausbruch, BTC/ETH/SOL) scheiterte in der Validierung an K4 (Drawdown);
  T1-Ausbruchsregeln in R4 ohne Vorteil; S2 (Session-Regeln) bekannt. Ausbruchsideen auf diesen Daten sind also
  schon mehrfach geprüft worden. S10 unterscheidet sich durch den festen Tageszeitpunkt (NY-Open), das IB-Profil als
  Ort und den Retest statt Einstieg am Ausbruch.

## 3. Daten

- USD-M-Perpetuals BTCUSDT, ETHUSDT, SOLUSDT (`protocol.UNIVERSE`), Klines 1m (IB-Profil) und 5m (Ausbruch,
  Retest, Ausstieg), Funding je 8 h. Quelle wie Protokoll 3.1 (`data.binance.vision`, Prüfsummen).
- Training 2020–2022, Validierung 2023–2024 (SOL ab erstem vollständigem Perpetual-Monat).
- Absorption (Variante O) aus der Kline-Spalte `taker_buy_base_volume`: Delta = 2 · taker_buy − volume.
  Keine aggTrades, kein Footprint je Preisstufe (Laufzeit und gleicher Datenstand wie die anderen Studien).

## 4. Regeln

### 4.1 Handelstag und Initial Balance

1. Handelstag = NYSE-Handelstag nach `calendars.nyse_holidays` (Mo–Fr ohne Feiertage); verkürzte Tage zählen voll.
2. IB = 09:30–10:00 America/New_York (Sommer-/Winterzeit nach Zeitzonen-Datenbank), also die 30 1m-Kerzen ab 09:30.
   IBH/IBL = höchstes Hoch / tiefstes Tief dieser Kerzen.
3. IB-Volumenprofil aus den 30 1m-Kerzen: Volumen jeder Kerze gleichmäßig über ihre Spanne verteilt, 40 gleich breite
   Preisstufen zwischen IBL und IBH, POC = Stufe mit dem meisten Volumen (bei Gleichstand die IB-Mitte nächste),
   Value Area 70 % nach der üblichen Ausdehnung vom POC aus (wie S9 Variante Z). VAH/VAL = Ober-/Unterkante der VA.
4. Fehlt im IB eine 1m-Kerze oder zwischen 08:15 und 16:00 New York eine 5m-Kerze (15 Kerzen Vorlauf vor 09:30 für
   ATR und Absorptions-Maßstab), gibt es an diesem Tag kein Signal.
5. Kein Signal, wenn die IB-Spanne kleiner als 0,25 · ATR(14, 1d) ist (zu enge Range, Kosten > Nutzen). ATR(14, 1d) =
   einfacher Mittelwert der True Range der 14 vollständigen UTC-Tage vor dem Handelstag (aus 5m-Kerzen, ein Tag mehr für
   den ersten Vortagesschluss); fehlt einer, kein Signal. Der Wert ist vorab gesetzt und wird nicht optimiert.

### 4.2 Ausbruch

1. Bullischer Ausbruch: erste 5m-Kerze ab 10:00, die **strikt über** IBH schließt (Docht zählt nicht).
   Bärisch gespiegelt unter IBL. Nur der erste Ausbruch des Tages zählt, gleich welcher Richtung.
2. Spätester Ausbruch: Kerze, die um 12:00 New York schließt. Danach kein Signal an diesem Tag.

### 4.3 Retest und Einstieg (Long; Short gespiegelt)

1. Zone = [POC, VAH]. Retest: eine 5m-Kerze nach der Ausbruchskerze, deren Tief ≤ VAH ist. Signalzeit = Schluss der
   Reaktionskerze; die Einstiegskerze muss vor 16:00 beginnen.
2. **Variante P (Profil):** Reaktionsschluss = die Retest-Kerze oder eine spätere schließt **strikt über** VAH,
   ohne dass vorher eine Kerze unter VAL geschlossen hat. Einstieg zum Eröffnungskurs der nächsten 5m-Kerze (Taker,
   Slippage nach Protokoll 4.4).
3. **Variante O (Profil + Orderflow):** wie P, zusätzlich zeigt mindestens eine Kerze zwischen Retest und
   Reaktionsschluss (beide eingeschlossen), deren Tief in der Zone oder darunter liegt, Absorption der Verkäufer:
   Delta < 0, `volume_ratio` ≥ 1,2 und `range_ratio` < 0,8 gegen den Mittelwert der fünf 5m-Kerzen davor
   (Schwellen aus `ORDERFLOW_REGELN.md`, nicht optimiert). Kommt ein Reaktionsschluss ohne vorherige Absorption, wartet
   Variante O auf einen späteren Reaktionsschluss mit Absorption (bis zum Verfall in 5).
4. Ungültig: Schließt eine 5m-Kerze nach dem Ausbruch unter VAL (Long), ist der Tag ohne Signal erledigt.
5. Verfall: kein Reaktionsschluss bis zur Kerze, die um 13:00 New York schließt → kein Signal.
6. Höchstens ein Trade je Instrument und Tag.

### 4.4 Ausstieg

1. Stop = VAL − 0,1 · ATR(14, 5m) zum Signalzeitpunkt (Long). Liegt der Eröffnungskurs der Einstiegskerze schon
   jenseits des Stops, zählt das Signal als ungültig (Bericht nennt die Zahl).
2. Ziel = 2 R ab dem tatsächlichen Einstieg (Autor: „1:2 bis 1:3 konsequent statt Maximalziel“; 2 R als untere
   Festlegung, kein Raster).
3. Zeitstop: Schluss der 5m-Kerze, die um 16:00 New York schließt (Ende der Kassasitzung), Taker.
4. Stop wird nie verschoben; kein Teilverkauf, kein Runner (der Runner der Videos ist Ermessen).
5. Berühren Stop und Ziel dieselbe Kerze, gilt der Stop (Engine-Regel).

### 4.5 Varianten (vorab, nicht nachträglich erweiterbar)

| Variante | Einstieg | Ziel | Bemerkung |
|---|---|---|---|
| S10-P | Reaktionsschluss über/unter der VA-Kante | 2 R | Modell 1 der Videos (Profil ohne Orderflow) |
| S10-O | wie P plus Absorption an der Zone | 2 R | Modell 2 der Videos (Orderflow-Bestätigung) |

Nicht getestet: 15-Minuten-IB, „protection level“ (DeepCharts-Algorithmus, nicht öffentlich), Mean Reversion
innerhalb der IB, Runner. Die Ausdehnung nach dem Ausbruch (in IB-Spannen) wird nur beschreibend berichtet.

## 5. Erfolgskriterien

K1–K5 aus dem Protokoll, Horizont „Short“, ausgewertet mit dem allgemeinen Runner (`src/research_lab/runner.py`,
Protokoll Abschnitt 8): Training ≥ 500 Trades, E[R] > 0, p < 0,10 gegen Zufall; Validierung ≥ 250 Trades, E[R] > 0,
p < 0,05, Profitfaktor > 1,1, Drawdown ≤ 20 %, Jahresstabilität, Walk-Forward > 0. Zusätzlich berichtet: Ergebnis mit
doppelten Kosten, BTC allein, Zählung je Ausschlussgrund, Anteil Zeitstop.

Ein Trade je Instrument und Tag über drei stark korrelierte Coins ist kein unabhängiger Fall. **Kriterium (Uzi
28.10.2026):** wie S6 (Protokoll 1.3, A3) zusätzlich mindestens 160 effektive Trades im Training, 183 in der
Validierung (n_eff = ⌊n / D⌋, Designeffekt D aus dem Tagescluster über alle Instrumente).

### 5.1 Machbarkeits-Gate (vor jedem Ergebnis)

Ergebnisblinder Zähllauf (`scripts/research_lab_s10.py count`): nur Signale, keine Ausstiege, kein R. Eine Variante
wird nur ausgewertet, wenn sie gepoolt im Training ≥ 500 und in der Validierung ≥ 250 Signale hat, an mindestens 160
(Training) bzw. 183 (Validierung) verschiedenen Tagen (ergebnisblinde Untergrenze für n_eff: D kann höchstens die Zahl
der Instrumente je Tag sein), und das schwächste Kalenderjahr, auf 21 Holdout-Monate hochgerechnet, ≥ 200 ergibt. Grobe Schätzung vorab: rund 250 NYSE-Tage je Jahr
und Instrument, Training also höchstens etwa 1 900 Instrument-Tage; Variante O dürfte das Gate knapp oder gar nicht
erreichen. Besteht keine Variante, endet S10 mit dem Befund „zu selten für einen Test“; die Regeln werden danach
nicht gelockert.

## 6. Zufallsvergleich

Protokoll 7.1 (`stats/random_entry`) mit Pool-Methode nach R4(a): zufällige Einstiegs-5m-Kerzen im selben Instrument
und Abschnitt **zwischen 10:00 und 13:00 New York an NYSE-Handelstagen** (gleiches Zeitfenster wie die echten
Einstiege), Richtung, Stopabstand in ATR und Haltedauer gemeinsam aus den echten Trades gezogen, gleiches Ziel 2 R,
gleicher Zeitstop und gleiche Kosten, 10 000 Läufe, Seed 20261029.

## 7. Bis zur Erstellung gesehene Daten

Keine Kurse für S10 ausgewertet. Gesehen: die zwei Videos (NQ-Future, Herbst 2026, ausgewählte Tage, Werbung) und die
öffentliche Videoliste des Kanals. Vorbelastung durch frühere Ausbruchsstudien siehe 2.

## 8. Entscheidungen (Uzi, 28.10.2026, „go“ auf die Empfehlung) und offene Punkte

1. **Register:** erst der Zähllauf 5.1, der keinen Platz belegt. Besteht eine Variante, läuft S10 als **eigene Familie
   wie S8** (kein Archiv-Holdout, Bestätigung nur prospektiv auf neuen Daten), nicht auf den letzten zwei Plätzen des
   Registers (58/60). Dafür ist vor jedem Ergebnis eine Protokoll-Einordnung wie bei S8 nötig.
2. **Universum:** gepoolt über BTC/ETH/SOL (wie S7), BTC allein wird beschreibend berichtet.
3. **Effektive Fallzahl:** Kriterium (Abschnitt 5).
4. **New-York-Open bei Krypto:** BTC hat keine Kassasitzung. Die Studie nimmt an, dass die Eröffnung der US-Aktien
   (09:30 New York) auch bei BTC Volumen und Richtung bündelt. Die beschreibende Statistik (Volumen je Halbstunde)
   kommt in den Zählbericht.

## 9. Ergebnis

Noch keins.

## Änderungsprotokoll

- 0.1 (28.10.2026): Entwurf aus den zwei Methodenvideos, nichts registriert, keine Marktdaten ausgewertet.
- 0.2 (28.10.2026): Uzis Entscheidungen (8), Regeln als Code eingefroren vor jedem Kontakt mit Marktdaten; präzisiert:
  5m-Vorlauf ab 08:15, Tages-ATR aus UTC-Tagen, Variante O wartet auf späteren Reaktionsschluss mit Absorption,
  Gate zusätzlich mit Signaltagen. Zähllauf: `scripts/research_lab_s10.py fetch` und `count` auf dem Mac.
