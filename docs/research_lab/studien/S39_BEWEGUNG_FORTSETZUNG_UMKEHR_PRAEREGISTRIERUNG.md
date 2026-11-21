# S39 – Nach großen Bewegungen: Fortsetzung oder Umkehr? (Präregistrierung 1.0, 16.11.2026)

Auftrag Uzi 16.11. ("Go" für P4 und P5 aus dem Bauplan "Preisbewegungen erklären"). Anlass: der Abverkauf in Woche 46, den TIM nicht einordnen konnte. Die Frage aus dem Bauplan lautet: Gibt es nach Ereignissen vom Typ X systematisch andere Ergebnisse, also Fortsetzung oder Umkehr? Die Regeln wurden vor jedem Ergebnis eingefroren. Nach dem ersten Ergebnis ändert sich nichts mehr. Die Studie beschreibt nur. Tage mit Fehlern im S8-Bericht fallen ganz weg; fallen Stresstage häufiger aus, gehen gerade große Bewegungen verloren (die Zahl der weggefallenen Tage steht im Bericht des Datenspeichers). Sie ist kein Trade und keine Regel, es gibt keine Kosten und sie ändert keinen Score. Code: `src/research_lab/studies/s39.py`, Tests in `tests/test_s39.py`.

## Ereignisse (fest)
- Gesucht wird mit dem Live-Detektor `move-context/0.2` aus `src/dashboard/move_context.py` mit unveränderten Schwellen. Eine 1h-Kerze zählt bei mindestens dem 15-fachen Median der letzten bis zu 480 Kerzen und mindestens 1,5 %. Eine 4h-Kerze zählt bei mindestens 5 σ der letzten bis zu 540 Kerzen. Treffer mit höchstens 4 h Abstand gelten als eine Bewegung. Mindesthistorie: 168 Stunden für 1h, 90 Kerzen (15 Tage) für 4h; Anfang Januar 2020 findet daher keine Bewegung. Die Schwellen stammen aus der Kalibrierung (`docs/research_lab/MOVE_CONTEXT_KALIBRIERUNG.md`). Diese hat nur die Häufigkeit gewählt und kein Ergebnis danach angesehen.
- Daten: BTCUSDT-Stundenkerzen aus den S8-Minutenbars. Geladen wird über `s17.load_candles`, das jeden Tag gegen das Manifest prüft und den Holdout verweigert. Stunden ohne Handel und Tage mit Fehlern im Bericht fallen weg. Die 4h-Kerzen setzen sich aus vier lückenlosen Stunden zusammen.
- Richtung: Schluss der letzten gegen Eröffnung der ersten Stunde des Fensters.
- Fluss: Spot-Taker-Delta (Kauf minus Verkauf geteilt durch Volumen) über das Fenster, mit dem Vorzeichen der Bewegung. Ein Wert von mindestens 0,08 (`DELTA_SHARE` wie im Live-Text) heißt "mit Fluss".

## Typen (genau 4, Holm über 4)
`UP_FLOW`, `UP_OHNE`, `DOWN_FLOW`, `DOWN_OHNE`, also Richtung mal Fluss. Andere Merkmale wie Liquidationen, Open Interest, Schlagzeilen oder Makro-Termine gibt es für 2020–23 nicht lückenlos. Sie sind deshalb nicht Teil dieser Studie. Dafür gibt es das Live-Etikett aus P4, das prospektiv gesammelt wird.

## Messung
- Messbeginn: Eine Bewegung ist erst vorbei, wenn 4 h lang kein weiterer Treffer kam. Gemessen wird deshalb ab dem Ende des letzten Treffers (auch eines 4h-Treffers) plus 4 h. So steckt keine Kerze, die für die Auswahl zählte, im gemessenen Zeitraum, und der Zeitpunkt war damals bekannt (kein Look-ahead).
- Hauptmaß, einzig getestet: die Rendite vom Schluss der Messbeginn-Stunde bis zum Schluss 24 h später, mit dem Vorzeichen der Bewegung. Positiv bedeutet Fortsetzung, negativ Umkehr. Fehlt eine der beiden Stunden, entfällt das Ereignis (gezählt).
- Überlappung: Liegt der Messbeginn weniger als 24 h nach dem der vorigen Bewegung, entfällt die spätere (gezählt). Die 24h-Fenster überlappen sich damit nicht.
- Zufallskontrolle: Zu jeder Bewegung wird eine zufällige Stunde aus demselben Abschnitt innerhalb von ±15 Tagen um ihren Messbeginn gezogen (gleiche Volatilitätsphase), mit demselben Vorzeichen und vorhandenem 24h-Schluss. Das ergibt 1000 Ziehungen, Seed 39. Überschuss = Mittel echt − Mittel der Ziehungen, damit ist der Trend herausgerechnet. Der p-Wert ist zweiseitig: (1 + Anzahl |Ziehung − Mittel| ≥ |echt − Mittel|) / 1001.
- Nur zum Ausweis, ohne Bedingung: die gleiche Rendite nach 4 h und der Anteil der Fortsetzungen.

## Abschnitte
Training 2020–2023, Lauf nur mit Daten bis 31.12.2023. Validierung 2024 wird genau einmal gelesen, und zwar nach dem Trainingslauf (`--phase valid`). Der Validierungslauf liest das eingefrorene Trainingsergebnis `s39_train.json` und rechnet das Training nicht neu; 2023 dient dort nur als Detektor-Historie. Der Code verweigert einen zweiten Lauf je Phase und eine Validierung ohne Training. Der Holdout 2025 ist gesperrt und wird nicht gelesen.

## Kriterium (je Typ, alle zugleich)
- Training: n ≥ 20, Holm-p ≤ 0,05, |Überschuss| ≥ 0,5 Prozentpunkte, Ereignisse aus mindestens 2 Jahren, und Leave-one-year-out (Überschuss ohne je ein Jahr) zeigt in jedem Fall dasselbe Vorzeichen.
- Validierung: n ≥ 5 und Überschuss mit demselben Vorzeichen.
- Ergebnisse: "belegt: Fortsetzung", "belegt: Umkehr", "nicht belegt", "nicht prüfbar" (Training unter der Mindestzahl) und "nicht prüfbar (Validierung zu klein)".

## Ablauf
1. Einfrieren per PR (diese Datei, `s39.py`, Tests).
2. Trainingslauf auf der PS5: `PYTHONPATH=. ../.venv/bin/python -m src.research_lab.studies.s39 --root DATA --out DIR --phase train`.
3. Validierung einmal mit `--phase valid`, unabhängig vom Trainingsergebnis, damit die Beschreibung vollständig ist. Ein Typ, der das Training nicht besteht, bleibt "nicht belegt".
4. Bericht aller Läufe.

## Erwartung
Der Detektor findet etwa 20 Bewegungen je Jahr, im Training also rund 80, verteilt auf vier Typen. Die Teststärke ist klein, in der Validierung (etwa 13 Bewegungen 2024, also rund 3 je Typ) noch kleiner: "nicht prüfbar (Validierung zu klein)" ist dort wahrscheinlich. "Nicht prüfbar" oder "nicht belegt" ist das wahrscheinliche Ergebnis und wird ehrlich berichtet. Auch ein belegter Befund wäre nur eine Beschreibung und keine Handelsregel.
