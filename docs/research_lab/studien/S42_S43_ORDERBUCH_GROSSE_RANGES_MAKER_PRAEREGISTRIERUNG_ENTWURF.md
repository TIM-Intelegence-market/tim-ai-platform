# S42 und S43: Orderbuch-Setup an größeren Ranges und mit Limit-Einstieg (Präregistrierung, Entwurf 0.1)

| Feld | Wert |
|---|---|
| Studien | S42 (größere Ranges) und S43 (Limit-Einstieg), Folgestudien zu S32 (nächste freie Nummern, 25.11.2026; im Konzept vom 23.11. noch S40 und S41, die inzwischen an andere Studien vergeben sind) |
| Version | **0.1, Entwurf.** Regeln als Code: `src/research_lab/studies/s42.py`, `src/research_lab/studies/s43.py` (Config-SHA-256 in jeder Ergebnisdatei), Tests `tests/test_research_lab_s42_s43.py`. `evaluate` gesperrt bis 1.x |
| Anlass | S32 1.0 (23.11.2026) nicht bestanden: Nach Kosten verlor jede Gruppe 1,6–2,2 R je Trade, weil 13–18 bp Kosten bei engen Ranges größer als der ganze Stop sind. Barti 23.11.: Folgestudien „1, 2 und 3 machen“ (Konzept `/mnt/project-files/s32-orderbuch/Folgestudien-Konzept-2026-11-23.md`) |
| Protokoll | `../PROTOKOLL.md` Version 1.3, Kosten aus `src/research_lab/protocol.py` (Maker 2 bp nur mit Durchhandel-Regel und Latenzprüfung, Abschnitt 4.4) |
| Daten | wie S32: Binance USDⓈ-M BTCUSDT, Tardis `incremental_book_L2`, für S43 zusätzlich Tardis `trades`, nur die kostenlosen Tage (1. jedes Monats). Training 2020-06 bis 2022-12 (31 Tage), Validierung 2023–2024 (24 Tage), Holdout ab 2025 gesperrt |
| Einordnung | Beobachtungsstudien mit gedachten Trades, ohne Registerplatz. Auch bei Bestehen kein Filter für S7b oder Engine. Eine bestandene Gruppe wird nur an neuen Daten bestätigt (Recorder, #253) |

## Warum das neue Fragen sind und kein Nachbessern

S32 hat nur 15-Minuten-Ranges mit Market-Einstieg geprüft. Beide Änderungen kommen aus der Idee selbst und nicht aus dem
Ergebnis von S32: Im Video ging es um einen Markt, in dem die Kosten im Verhältnis zum Stop winzig sind. Wer so handelt,
nimmt dafür größere Ranges oder Limit-Orders. Weil S32 schon ausgewertet ist, wird die Zahl aller Versuche
mitgezählt (Abschnitt 5). Die Studien laufen auf denselben 55 Tagen.

## 1. Gemeinsame Regeln (wie S32 1.0)

Buch ±5 bp, Schiefe als Minimum der letzten 3 s, verteidigte Range (beide Ränder berührt und wieder verlassen,
mindestens 3 Berührungen, 95 % gültige Sekunden), Auslöser im unteren / oberen Viertel, Einstieg 1 s später, Stop 5 bp
jenseits des Rands, beide Ziele (Mitte und anderer Rand, jedes eine eigene Frage), alle Schiefen, keine Schwelle.

Jede Gruppe ist eine eigene Frage mit α = 0,05: die Hälfte für H1 (Trendtest „Ziel zuerst“ über die log-Schiefe),
die Hälfte für H2 (Netto-R je Schiefe-Stufe, 7 Stufen, Bonferroni). Untere Grenze per Block-Bootstrap über Tage
(9 999 Ziehungen). Bestanden heißt: untere Grenze über 0 in Training **und** Validierung. Unter 30 Fällen wird die
Gruppe gezeigt, bekommt aber kein Urteil. Alle Gruppen werden immer berichtet.

## 2. S42: größere Ranges

| Regel | Wert |
|---|---|
| Range-Fenster | 1 h, 2 h, 4 h, jedes Fenster eine eigene Familie |
| Breiten | 60–100, 100–150, 150–250, 250–400 bp, jede Breite über den ganzen Tag und je Sitzung (Asien 0 Uhr, London 7 Uhr, New York 13:30, spät 20 Uhr UTC), also 20 Gruppen je Fenster |
| Haltedauer und Pause | ein Drittel des Fensters (S32: 300 s bei 900 s): 20 / 40 / 80 min |
| Verteidigungsprüfung | höchstens alle 10 s je Breite (sonst sind 4-h-Fenster zu langsam). Gilt für alle Fenster gleich |
| Kosten | Protokoll 1.3 Taker: 13 bp, mit Stop 18 bp; Stress doppelt |

Tagesgrenzen: Jeder Tag ist eine eigene Datei. Die ersten Fensterlängen eines Tages dienen zum Aufwärmen, und Fälle,
deren Haltedauer über das Tagesende reicht, fallen weg („missing“). Das betrifft lange Fenster stärker und wird im
Zähllauf mitgezählt.

## 3. S43: Limit-Einstieg

| Regel | Wert |
|---|---|
| Ereignisse | wie S32 1.0 (15 min, S32-Breiten und Sitzungen) und wie S42 (1/2/4 h) |
| Order | Limit zum Mittelkurs 1 s nach dem Auslöser |
| Füllung | erst, wenn in einer **späteren** Sekunde ein Trade **durch** den Limit geht (Kauf: Trade strikt darunter), Protokoll 1.3, 4.4 |
| Löschen | nicht gefüllt nach 30 s, 60 s oder 5 min, jeder Wert eine eigene Familie. Ungefüllt heißt kein Trade, nicht Verlust |
| Ausgang | Ziel als ruhende Limit-Order, gefüllt erst bei Trade strikt durch das Ziel. Stop per Mittelkurs wie S32, innerhalb einer Sekunde zuerst geprüft. Am Ende der Haltedauer Market-Ausstieg |
| Kosten | Maker 2 bp je Limit-Füllung. Ziel: 4 bp. Zeitausstieg: 2 + 5 + 3 bp. Stop: 2 + 5 + 5 bp. Stress doppelt |
| Zusätzlich berichtet | Füllquote und ob gerade die guten Fälle nicht gefüllt werden (Market-Ergebnis von gefüllten gegen ungefüllte Fälle, beschreibend) |

Familien: 4 Fenster × 3 Löschzeiten × 2 Ziele = 24, je mit 20 Gruppen.

## 4. Ablauf

1. Barti und Uzi lesen den Entwurf. Änderungen nur jetzt.
2. `pytest tests/test_research_lab_s42_s43.py` grün.
3. Zähllauf (ergebnisblind, nur Anzahl der Fälle je Gruppe, ohne Ausgänge und ohne Füllungen):
   `python -m src.research_lab.studies.s42 count --dir ~/TIM-research/tardis --out DIR --fetch` und
   `python -m src.research_lab.studies.s43 count ...`.
4. Einfrieren als 1.0 nur mit Uzis Wort **und** Bartis Go.
5. Genau ein Auswertungslauf (`evaluate`). Kein Nachbessern.

## 5. Mehrfachtests

Jede Gruppe hat ihr eigenes α (Barti 16.11.: Ein Trader wählt seine Range und Sitzung). Damit niemand eine zufällige
Gewinnergruppe überschätzt, wird die Gesamtzahl der H2-Felder aus S32, S42 und S43 im Bericht genannt, und für jedes
bestandene Feld wird der Deflated Sharpe mit dieser Zahl ausgewiesen.

## 6. Nicht Teil von S42 / S43

Andere Bänder, Stops oder Haltedauern als oben, Spot-Buch, andere Börsen, Echtgeld, Live-Orders. Dem Ausbruch folgen
ist S44 (eigene Präregistrierung, andere Daten).
