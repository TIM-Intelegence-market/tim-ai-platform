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
