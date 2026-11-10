# Bauplan: PS5-Dauerforschung Orderflow-Engine (OFX), 10.11.2026

Uzi 10.11.: "die PS5 soll solange an der orderflow engine arbeiten bis wir wirklich ein perfekt bewiesenes OF engine haben" + "go".
Uzi 10.11. 12:16: "ich moechte das sie die heutigen daten von diesem jahr ebenfalls nuzt bis 2020" -> Daten 2020 bis gestern, 2025 eingeschlossen (Uzis ausdrückliches Wort, gilt für OFX).

## Datenaufteilung (neu, 2020-01-01 bis gestern)
| Abschnitt | Zeitraum | Zweck |
|---|---|---|
| Training | 2020-01-01 bis 2023-12-31 (4 Jahre) | Suche und Sieb |
| Validierung | 2024-01-01 bis 2024-12-31 | einmal je Kandidat |
| Schlusstest | 2025-01-01 bis Vortag des Starts (~22 Monate) | einmal je Kandidat, der die Validierung bestand |
| Papierbetrieb | ab Start, laufend | letzter Beweis |
S8-Minutendaten 2025-01-01 bis gestern holt die PS5 neu von data.binance.vision (gleiche Balkenversion 1.2.0).

## Ziel
Die PS5 sucht dauerhaft bessere Varianten der OF2-Engine und schickt nur Kandidaten weiter, die nach festen Regeln
nicht nach Zufall aussehen. Am Ende steht eine Engine, die auf ungesehenen Jahren und danach im Papierbetrieb hält.

## Erfolgskriterium ("belegt")
Eine Variante gilt als belegt, wenn sie alle vier Stufen besteht:
1. **Suche (Training 2020–2023):** gefunden, ohne andere Jahre zu sehen.
2. **Sieb (Training):**
   - ≥ 130 OF-Trades in 4 Jahren (Richtwert Uzi 56–124 ist Orientierung, unter 100 ist nichts prüfbar)
   - netto ≥ +0,10 R je Trade mit Bitunix-Taker-Kosten (0,06 % + Slippage)
   - jedes Jahr 2020–2023 einzeln netto > 0
   - größter Rückgang ≤ 15 R
   - gegen Zufallseinstiege p ≤ 0,01
   - Nachbarn stabil: jeder Parameter ±1 Schritt behält ≥ 50 % des Vorteils (kein Einzelpunkt-Glück)
   - Mehrfachtest: Reality-Check über ALLE bisher probierten Varianten p ≤ 0,05 (jede Variante wird mitgezählt)
3. **Validierung (2024) und Schlusstest (2025 bis gestern), je einmal je Kandidat:** Kandidat wird vorher eingefroren und registriert.
   Validierung ≥ 30 OF-Trades, Schlusstest ≥ 50, jeweils netto ≥ +0,10 R, p ≤ 0,05 nach Holm über alle jemals validierten Kandidaten. Höchstens 2 Kandidaten
   pro Monat. Durchgefallen = endgültig raus, keine Nachbesserung derselben Variante.
4. **Papierbetrieb (Live-Daten, kein Geld):** ≥ 100 Trades, untere 90-%-Grenze des Mittels > 0.
   Bei ~1–2 Trades/Woche dauert das etwa ein Jahr. Erst dann "belegt".

2025 ist auf Uzis Wort Teil des Schlusstests (nicht der Suche).

## Was gesucht wird (Suchraum)
- Modelle M1–M7 einzeln an/aus, Sessions an/aus
- Schwellen: relvol, Imbalance, Absorption, Zeros, Stopp-Puffer, Mindest-RR, Kostengrenze, Zeitstopp, Haltedauer
- Zeitebenen 15/30 min
- "Schlechte Tage auslassen" (Uzi 10.11.): z. B. kein Handel an Trendtagen, nach 2 Verlusten am Tag, bei extremer
  Volatilität, am Wochenende. Kein Mindestzwang an Trades.
- Später (eigene Stufe): Maker-Einstiege mit strenger Füllregel (Kurs muss durch das Limit laufen).

## Nicht-Ziele
- Kein Echtgeld, keine Änderung am Live-Trader oder an ~/TIM-live.
- 2025/2026 nie in der Suche, nur im Schlusstest.
- Keine neuen Datenquellen (nur S8-Minutenbalken mit Footprint-Profil; keine Ticks, kein Orderbuch).
  Grenze: "perfekt" im Sinne echter Orderbuch-Engine ist mit Minutendaten nicht erreichbar.
- Keine 200x-Isolated-Annahme (liquidiert); Hebel nur als Bericht (Cross).

## Pakete und Prüfbefehle
| Paket | Inhalt | Prüfung |
|---|---|---|
| P0 Daten | PS5 lädt 2025-01-01 bis gestern nach (S8 1.2.0), Store-Sperre für 2025 nur für OFX geöffnet, Rest bleibt gesperrt | Manifest vollständig, 0 Ladefehler; Test: andere Studien lesen 2025 weiter nicht |
| P1 Suchmotor | `src/research_lab/ofx/`: Variante = Config + Filter; Zufalls-/Gitter-Ziehung mit festem Seed; Tages-Cache (Tage einmal laden, viele Varianten); jede Variante mit Digest in `varianten.jsonl` | `pytest tests/test_research_lab_ofx.py`; Lauf mit Standard-Config ergibt exakt OF2-1.0-Zahlen (56 Trades, +15,05 R) |
| P2 Sieb | Jahresprüfung, Rückgang, Zufallsvergleich, Nachbarn, Reality-Check über alle Varianten | Tests mit künstlichen Daten: reines Rauschen besteht nie, eingebauter Vorteil besteht |
| P3 Dauerlauf PS5 | Cron/nohup-Schleife in Blöcken, STOP-Datei, Logs mit Rotation, Budget je Block, Absturz setzt fort | Probeblock 1 h auf PS5, Log + Ergebnisdatei vorhanden |
| P4 Wochenbericht | Kurzbericht je Woche: Varianten probiert, im Sieb, bester Kandidat, keine Validierungszahlen vor Freigabe | Bericht aus Probeblock |
| P5 Validierungs-Schleuse | Einfrieren + Registereintrag + einmaliger Lauf 2024, dann 2025+, Holm-Zähler | Test: zweiter Lauf desselben Kandidaten wird abgewiesen |
| P6 Papierbetrieb | Bestandener Kandidat läuft als Schatten-Journal auf Live-Minutendaten am Mac | erst wenn ein Kandidat P5 besteht |

Code kommt per PR ins Repo (merge nur auf Uzis "merge"), die PS5 holt ihn nachts. Keine Secrets auf der PS5.

## Risiken
- **Überanpassung** (Hauptrisiko): Gegenmittel sind Reality-Check über alle Varianten, Nachbar-Stabilität, Jahrestest, einmalige Validierung.
- Mit 2025 im Schlusstest ist der alte Holdout für andere Studien nicht mehr ganz blind, wenn Ergebnisse geteilt werden. Validierung 2024 nutzt sich ab: jede Prüfung zählt in Holm, daher höchstens 2 pro Monat.
- Register hat nur noch 2 freie Plätze: OFX bekommt einen Familienplatz, Kandidaten laufen darunter.
- PS5 14 GB RAM: Tages-Cache muss passen (3 Jahre Minuten + Profile, vorher messen).
- Ergebnis kann "nichts gefunden" sein; das ist ein gültiges Ergebnis.

## Offene Entscheidung (Uzi)
Validierung je Kandidat: automatisch (max. 2/Monat, alle gezählt) oder jedes Mal erst nach deinem Wort?
Empfehlung: automatisch, Bericht danach.

## Nachtrag 10.11.: Zeitrahmen im Suchraum

Uzi: Die Suche soll die Zeitrahmen 1m bis 1M mitrechnen. Eingebaut sind die, die die Engine heute rechnen kann:
`tf_value` (Wertbereich-Modelle) 5, 15, 30, 60 Minuten und `tf_sfp` (Sweep- und Footprint-Modelle) 1, 5, 15, 30, 60 Minuten.
Die Engine baut ihre Kerzen an jedem UTC-Tag neu auf. 4h, 1d, 1w und 1M brauchen Kerzen über Tagesgrenzen, längere
Haltezeiten und Marken aus Vorwoche/Vormonat; das ist ein eigener Umbau und nicht Teil dieses Nachtrags.
Die Zählung der Konfigurationen (Mehrfachtest) läuft im selben Lauf weiter.

## Nachtrag 10.11.: Richtungsfilter Tag, Woche, Monat (Z5)

Uzi "go" zum Zeitrahmen-Plan. Erstes Paket: Für jeden Trade wird beim Signal die Richtung von Tag, Woche und Monat
bestimmt (`ofx/trend.py`), nur aus abgeschlossenen Kerzen: letzter Schluss gegen den Mittelwert der letzten
20 Tage, 10 Wochen oder 3 Monate. Der Filter darf je Zeitrahmen "MIT", "GEGEN" oder nichts wählen. Ohne genug
Vorgeschichte (Anfang 2020) gilt die Richtung als unbekannt und der Trade fällt bei aktivem Filter weg.
Die Regel wurde festgelegt, bevor die Suche ein Ergebnis damit gesehen hat.

Zufallsvergleich: Die Zufallseinstiege müssen dieselbe Richtungsregel einhalten. Sonst würde "nur Long im
Aufwärtstrend" den Zufall allein durch die Drift des Marktes schlagen.

Tagesschlüsse kommen aus dem Speicher ohne Freigabe (nur bis Trainingsende) und liegen als `tagesschluss.json`
im Ergebnisordner.

## Nachtrag 10.11.: Swing-Spur 4h und 1d, Funding (Z1 bis Z4, Z6)

- **Kerzen über Tagesgrenzen (Z1):** Mit `swing_tf` (240 oder 1440 Minuten, 0 = aus) führt die Engine eine zweite,
  fortlaufende Kerzenreihe (höchstens `swing_history` = 40 Kerzen Rückblick).
- **Marken aus Vorwoche und Vormonat (Z2):** `swing_level` "W" (Montag bis Sonntag UTC) oder "M" (Kalendermonat).
  Wertbereich, POC, Hoch, Tief und Schluss aus den Tagesprofilen der abgeschlossenen Periode
  (`levels.period_summary`; die Tage haben eigene Bin-Breiten und werden auf die breiteste umgelegt).
  Ist die Periode nicht vollständig im Speicher, gibt es keine Marken und kein Signal.
- **Swing-Spur (Z3):** M1, M2 und M3 laufen ein zweites Mal auf den Swing-Kerzen gegen diese Marken und heißen
  dort S1, S2, S3. Ein Signal je Modell, Richtung und Woche. Haltezeit bis `swing_hold_days` (3, 7 oder 14 Tage).
  Die Tagesregime-Sperren (Trend-/Range-Tag) gelten für S1 bis S3 nicht. Bei S1 zählt nur der letzte Ausflug aus
  dem Wertbereich, nicht die ganze Kerzenreihe. Die Footprint-Modelle M4 bis M7 bleiben im Intraday.
- **Funding (Z4):** `funding_per_8h`; die OFX-Basis rechnet 0,01 % je 8-Stunden-Marke (00, 08, 16 UTC), die der
  Trade offen überquert, in beiden Richtungen als Kosten (ein Short bekommt nichts gutgeschrieben). Gilt ab jetzt
  auch für die Intraday-Trades der Suche. OF2 1.0 und das Papier-Journal bleiben ohne Funding und bitgleich.
- **Suche (Z6):** `swing_tf` (0, 240, 1440), `swing_level` (W, M), `swing_hold_days` (3, 7, 14) im Suchraum,
  S1 bis S3 in der Modellauswahl der Filter. Der Vorlauf der Rechenstücke wächst mit der Swing-Spur
  (`parallel.warmup_days`).

Ebenfalls in diesem Nachtrag: M1 und M2 tragen ihren Zeitrahmen im Signal (vorher fest 30). Mit `tf_value`
ungleich 30 zählte der Zeitstopp falsch und die Storno-Regel von M2 griff nicht; betroffen waren die
Konfigurationen 1400 bis etwa 1450 von lauf2 (kein Kandidat darunter).

1w und 1M sind kein Einstiegs-Zeitrahmen (208 Wochen- und 48 Monatskerzen in vier Jahren, das Sieb verlangt
130 Trades); sie wirken über den Richtungsfilter und über die Marken.

## Nachtrag 10.11. abends: Suche nur bis 1h

Uzi nach den ersten Zahlen der Swing-Spur (4h: 43 Trades, -0,10 R; 1d: 2 bis 8 Trades in vier Jahren):
"nimm nur die low timeframes bis 1h". `swing_tf`, `swing_level` und `swing_hold_days` sind wieder aus dem
Suchraum, S1 bis S3 aus der Modellauswahl. Der Code der Swing-Spur bleibt in der Engine, ausgeschaltet.
Richtungsfilter (Tag, Woche, Monat) und Funding bleiben in der Suche.

## PS4 als zweiter Sucher (Uzi 10.11. "go")

Die PS4 (8 Kerne, 6,7 GB RAM, kein sudo, kein cron) sucht im selben Raum mit eigenem Seed (`--seed 20261111`,
Ordner `results/ofx/lauf2-ps4`), gleicher Code wie lauf2 der PS5. Auf der PS4 liegen nur die Trainingstage
2020–2023 (Validierung 2024 und Schlusstest 2025 nie). Jede Maschine zählt im Sieb nur ihre eigenen Konfigurationen;
`python -m src.research_lab.ofx gesamt <lauf2> <lauf2-ps4>` summiert beide und prüft jeden Kandidaten gegen die
gemeinsame Bonferroni-Schwelle. Nur Kandidaten, die dort bestehen, gehen in Validierung/Schlusstest.
