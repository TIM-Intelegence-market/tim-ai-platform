# Architekturentscheidung: Rollen der Geräte (Stand 17.11.2026)

Uzi hat am 17.11.2026 um 01:18 Ortszeit mit "Go" zugestimmt (Thread "16.11. TIM-Bestandsaufnahme und Roadmap"). Die Datei beschreibt die Zielrollen. Sie ändert keinen Dienst. Jeder Umbau braucht weiter sein eigenes Wort von Uzi: "go P…", "Zeitplan an", "PS4 aus".

## Grundsatz

**Jeder Datenstrom hat genau einen Schreiber.** Alle anderen Geräte sind Zeuge (unabhängige zweite Aufzeichnung zum Abgleich), Archiv (Kopie) oder Rechenknoten (Studien). Keiner davon entscheidet mit oder schreibt in Journale des Produktionsknotens. So entstehen keine Doppelzählungen und keine widersprüchlichen Stände.

## Rollen

| Gerät | Rolle | Was dort läuft | Was dort nicht läuft |
|---|---|---|---|
| **Mac mini** (`~/TIM-live`) | einziger Produktionsknoten | Datenaufnahme (Spot-aggTrades → PostgreSQL, Perp/Bybit/Gamma/Liquidationen), Plan-Journale, Schatten, Chart, Control Center, Dashboard-Agent | kein zweiter Schreiber für dieselben Ströme |
| **PS5** (Warpgate `uzi:ps5-research`) | Zeuge und Rechenknoten | geplant: zweiter Spot-Recorder und Orderflow-Papierbetrieb live (Bauplan `of-live-ps5-2026-11-17`, Pakete P1–P5); Trend- und Preisstudien ohne Orderflow | keine Orderflow-Rückschau mehr (OFX am 16.11. gestoppt, Uzi: OF nur vorwärts), kein Holdout ohne Uzis Wort, keine Secrets |
| **Server tim-core-01** (Debian) | Archiv und Sicherung | Backups (Issue #285, Chris), Kopie der nicht wiederholbaren eigenen Daten (Perp-Orderflow-Archiv, OI, Liquidationen), Qwen, Warpgate | kein Live-Dienst (Uzi 22.10.: "TIM soll 100 % auf dem Mac laufen") |
| **PS4** | Backup-Ablage und Restore-Test (Vorschlag 17.11., wartet auf Uzis Zeitplan-Wort) | Kopie der nächtlichen Mac-Sicherung (`scripts/tim_offsite_upload.py`, Dump nur verschlüsselt, solange Zugangsdaten im Dump ungeprüft sind), Prüfsummenkontrolle, Test-Restore in eigenem Postgres | keine Live-Daten, kein Recorder, kein KI-Modell, nichts, das ohne Lücken laufen muss (nach Neustart von Hand hochfahren). Fällt sie aus, geht nichts verloren |

## Begründung

- **Ausfallsicherheit:** Heute gibt es für die Live-Daten nur einen Aufzeichner. Fällt er am Mac aus, sind die Daten verloren. Ein Zeuge auf der PS5 und ein Archiv auf dem Server machen einen Ausfall sichtbar und halten die Daten bereit.
- **Datenprüfung:** Ein Zeuge bringt einen unabhängigen Vergleich (Roadmap R2 der Bestandsaufnahme vom 16.11.: Datenstatus je Quelle). Ein zweiter Schreiber würde dagegen Konflikte erzeugen.
- **Pflegeaufwand:** Die PS4 ist langsam, hat kein git und keinen Cron, und ihr Wächter meldet falsch "läuft". Seit die Orderflow-Rückschau beendet ist, hat sie keine Aufgabe mehr.

## Belege (16.11.2026)

- PS5 hat 16 Kerne, 12 GiB RAM frei und 95 GB Platz. Per WebSocket kamen Spot-aggTrade (70 Nachrichten in 10 s), Perp `@trade` (410 in 15 s) und Bybit (197 in 10 s) an. Perp `@aggTrade` lieferte 0 Nachrichten, die Ursache ist offen.
- OFX gestoppt: PS5 nach 27 597 Konfigurationen, PS4 nach 4 516, beide mit 0 Kandidaten.
- Mac-Live-Dateien waren am 16.11. 0–1 Minute alt.

## Offen

- "PS4 aus" (Uzi).
- Archiv-Kopie der eigenen Daten auf den Server: Umfang und Zeitplan (mit #285).
- PS5-Zeuge: Bauplan P1–P4, jeweils auf "go".
