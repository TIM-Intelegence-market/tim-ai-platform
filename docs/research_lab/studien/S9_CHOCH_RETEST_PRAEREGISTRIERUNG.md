# S9: CHoCH → Retest-Band → Reaktionsschluss auf 15m-Kerzen (Präregistrierung, Entwurf)

| Feld | Wert |
|---|---|
| Studie | S9 |
| Version | **0.1 ENTWURF – nicht freigegeben, nichts registriert, kein Datenlauf** |
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

1. Swing-Hoch/-Tief: Pivot mit k = 2 Kerzen links und rechts (Heft S. 4), bekannt erst bei Schluss der 2. Kerze rechts.
2. Abwärtsstruktur: letzte relevante Folge LH → LL. CHoCH-Referenz = Docht-Hoch des LH, von dem der Lauf zum
   letzten LL startete. Ursprungstief = dieses LL.
3. **Bullischer CHoCH:** Schlusskurs > CHoCH-Referenz (Gleichheit zählt nicht). Bärisch gespiegelt.
4. Ein Impuls bekommt nur ein Label (Heft S. 10): nach dem CHoCH zählt der nächste Bruch erst nach neuem HL/LH.

### 4.2 Einstieg (Basismodell A des Hefts, M15)

1. Retest-Band direkt nach dem CHoCH festlegen: Referenz ± b · ATR(14, 15m) zum Zeitpunkt des CHoCH.
2. Warten, bis eine spätere Kerze das Band berührt (Docht im Band). Berührung allein ist kein Signal.
3. Reaktionsschluss: eine Kerze schließt **strikt über** der Oberkante (Long) bzw. unter der Unterkante (Short).
4. Einstieg zum Eröffnungskurs der nächsten Kerze (Taker).
5. Stop: Ursprungsextrem minus Puffer 0,1 · ATR (Long). Wird das Ursprungsextrem vor dem Einstieg verletzt, auch
   intrabar, ist die Sequenz ungültig, kein Trade.
6. Ziel: Variante T (siehe 4.3). R:R = (Ziel − Einstieg) / (Einstieg − Stop) vor Kosten. **R:R < 2 → kein Trade**
   (Heft S. 18). Stop wird nie nachträglich verschoben.
7. Verfall: kommt kein Reaktionsschluss innerhalb von 48 Kerzen (12 h) nach dem CHoCH, verfällt das Setup.
8. Zeitstop: 96 Kerzen (24 h) nach Einstieg, Ausstieg zum Schluss.

### 4.3 Varianten (vorab, nicht nachträglich erweiterbar)

| Variante | Bandbreite b | Ziel | HTF-Zone nötig |
|---|---|---|---|
| S9-B25-I | 0,25 | Impulsextrem nach dem CHoCH (Heft: „Ziel unter dem Impulshoch“) | nein |
| S9-B50-I | 0,50 | Impulsextrem | nein |
| S9-B25-Z | 0,25 | Impulsextrem | ja: Ursprungsextrem liegt innerhalb 0,5 · ATR(14, 1d) eines Vortags- oder Vorwochen-Levels (VAH, POC, VAL, Hoch, Tief), wie in `session_map` |
| S9-B50-Z | 0,50 | Impulsextrem | ja |

M5/M3-Varianten des Hefts werden nicht getestet (Heft: Timing-Alternativen, keine unabhängigen Belege).

## 5. Erfolgskriterien

K1–K5 aus dem Protokoll, Horizont „Short“ (K3: ≥ 200 Trades im Holdout). Zusätzlich berichtet: Trefferquote,
mittleres R:R der genommenen Trades, Anteil verworfener Setups wegen R:R < 2, Ergebnis mit doppelten Kosten.

## 6. Zufallsvergleich

Je echtem Einstieg ein zufälliger Einstiegszeitpunkt im selben Monat mit gleicher Richtung, gleichem Stopabstand in ATR
und gleichem R:R-Ziel, 1000 Wiederholungen; K2 mit Holm-Bonferroni über alle Registereinträge.

## 7. Bis zur Erstellung gesehene Daten

Keine Kurse für S9 ausgewertet. Gesehen: das Lernheft (erfundene Preise), die TIM-Chart-Anzeige von BOS/MSS auf
aktuellen BTC-Kerzen (Okt. 2026, liegt im Holdout-Zeitraum und wird nicht benutzt).

## 8. Offene Punkte vor Version 1.0

1. Freigabe durch Uzi (Entscheidungskarte), danach Registrierung der vier Varianten.
2. Gold: eigene Protokolländerung für PAXGUSDT (oder XAUUSD aus anderer Quelle) oder Gold nur als Anzeige lassen.
3. Bandbreite in ATR statt fester Preisspanne: das Heft gibt keine Breite vor („teaching example“).
4. Das deutsche Heft „GoatHub XAUUSD – Higher Timeframe Analysis“ (Heft S. 26) liegt nicht vor; die HTF-Zone in
   Variante Z ist eine eigene Festlegung.

## Änderungsprotokoll

- 0.1 (27.10.2026): Entwurf aus dem Lernheft, nichts registriert.
