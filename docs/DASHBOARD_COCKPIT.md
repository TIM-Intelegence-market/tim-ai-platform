# Neues Control Center (Cockpit) unter /neu

Stand: 24.10.2026, Pakete P1 bis P3 des Bauplans "Neues TIM-Dashboard", dazu der Bereich "Mac jetzt" auf Uzis Wunsch.

Das neue Control Center läuft im selben Prozess wie das bisherige (Port 8765) und
ist unter `http://127.0.0.1:8765/neu` erreichbar. Die bisherigen Seiten bleiben
unverändert, bis Uzi das neue Dashboard abnimmt und umgeschaltet wird (Paket P4).

## Bereiche

| Bereich | Adresse | Stand |
| --- | --- | --- |
| Lage (Startseite) | `/neu` | gebaut (P1) |
| Markt & Pläne | `/neu/markt?tf=15m` | gebaut (P2): Chart mit Plänen, Vorbereitung, Plan- und Trader-Journal |
| Mac jetzt | `/neu/mac` | gebaut: CI-Lauf, Issue-Worker, Hintergrunddienste |
| Forschung | `/neu/forschung` | gebaut (P3): Validator, Research Cases, Beobachtungen, Qualifizierung |
| Betrieb | `/neu/betrieb` | gebaut (P3): Gesundheit, Datenpipeline, Datenqualität und Lücken, Zeitleiste |
| System & Freigabe | `/neu/system` | gebaut (P3): Betriebsart und Handelssperre, V2-Gates, Sicherheit, Nachweise |

Maschinenlesbar: `GET /api/cockpit?area=lage|markt|mac|forschung|betrieb|system` (Modell eines
Bereichs, ohne `area` die Startseite), `GET /neu?fragment=1`, `/neu/markt?tf=1h&fragment=1`,
`/neu/<bereich>?fragment=1` (neu gerenderter Seiteninhalt für die Aktualisierung alle 30 Sekunden).

## Forschung, Betrieb, System: Aufbau

Alle drei lesen den TIM-Zustand (`/api/state`, Block `operations`); Betrieb zusätzlich
Backup- und Server-Bericht wie die Startseite (`src/dashboard/cockpit/areas.py`).
Jeder Bereich besteht aus Abschnitten mit Kacheln und höchstens einer kleinen Tabelle;
die vollen Detailseiten des bisherigen Dashboards bleiben unten verlinkt.

- Bewusst grau: Ein menschlicher Schritt (Freigabe, Integrity-Prüfung), die abgebrochene
  Kampagne, ein Gate nur mit Archivwert und der externe MCP-Weg tragen ein eigenes Wort
  ("Wartet auf euch", "Abgebrochen", "Nur Archiv", "Extern"). Sie bleiben sichtbar, färben
  aber die Überschrift des Bereichs nicht, weil nichts kaputt ist.
- Reine Messwerte (Empfangsrate, Neustarts gesamt) sind Information ohne Urteil. Bewertet
  werden nur Werte mit eigener Grenze (Nachrichtenalter, Datenträger, Logs).
- Messwerte ohne Wert in der Quelle stehen gesammelt in einer Zeile unter dem Abschnitt.
- V2-Gates: Grüne Gates stehen nur in der Tabelle, Kacheln zeigen den Rest.
- Handel gilt nur als gesperrt, wenn `trading_locked` und `execution_disabled` beide
  wirklich `true` sind; sonst rot.
- Ein unerwartetes Datenformat macht einen Abschnitt grau, nie die ganze Seite.

## Mac jetzt: Quellen

| Kachel | Quelle | Frischegrenze |
| --- | --- | --- |
| Issue-Worker, CI-Runner, Warteschlange, Zuletzt erledigt, Lokales Modell | `GET 127.0.0.1:8767/api/status` (Worker-Dashboard, `TIM_WORKER_STATUS_URL`) | 3 min |
| TIM-Laufzeit, Watchdog, Backup | wie auf der Startseite | wie dort |
| Validator | `data/operational/research_cycle_latest.json` | 5 min |
| Server-Health | `data/operational/server_health.json` | 5 min |
| Lückenreparatur | `data/operational/history_recovery.json` | 3 min |
| Readiness-Eingaben | `data/operational/readiness_inputs.json` | 5 min |
| Dashboard-Agent | `data/operational/dashboard_refresh.json` | 30 min |
| Trading-Team | `~/TIM-trading-team/state/trading-team/` (`TIM_TRADING_TEAM_STATE`) | 15 min |

Der CI-Runner wird nur über den Issue-Worker gesehen: Er meldet einen laufenden
CI-Job, solange er selbst läuft und kein Issue bearbeitet. Arbeitet er an einem
Issue, ist die CI-Kachel grau ("unbekannt"), nicht grün. Das Cockpit startet keine
Prozesse und ruft weder `ps` noch `launchctl` auf.

## Aussehen

Gestaltet nach den Anthropic-Plugins `frontend-design` (Plan, Prüfung gegen Standard-Look,
Bau, Kritik mit Screenshots) und `Design` (Design-Kritik, WCAG-2.1-AA-Prüfung).

- Startseite beginnt mit einem Lage-Satz ("Ein Punkt braucht einen Blick") und dem BTC-Kurs.
- Kacheln sind Zeilen einer Liste (Zustand, Name, Wert mit Grund, Stand und Quelle), nicht
  einzelne Karten. Zeilen mit "Prüfen" oder "Fehler" sind farbig hinterlegt.
- Zustand nie nur über Farbe: Wort plus Form (● OK, ▲ Prüfen, ■ Fehler, ○ Keine Daten).
- Farben: Seekarten-Blau und Tinte, helles und dunkles Schema; alle Text-Hintergrund-Paare
  mindestens 4,5:1 Kontrast. Schrift: Avenir Next (Mac), sonst Systemschrift; keine Webfonts
  (CSP `font-src 'none'`), Ziffern in fester Breite.
- Schmale Spalten und Handys stapeln die Zeile (CSS Container Query); Tipp-Ziele mindestens 44 px.

## Kachel-Vertrag und Statusregel

Jede Kachel hat Wert, Zustand, Grund, Quelle und Stand (`src/dashboard/cockpit/tiles.py`).
Eine einzige Regel entscheidet die Farbe:

- grün (`ok`): geprüft gesund und frisch.
- gelb (`warn`): ansehen (eingeschränkt, wartend, veraltet).
- rot (`fail`): gemessener Fehler.
- grau (`unknown`): keine Daten oder bewusst aus.

Nicht grün heißt immer: Grund im Klartext auf der Kachel. Liegt der Stand einer
Kachel über ihrer Frischegrenze, ist sie mindestens gelb und nennt das Alter.
Fehlt ein Zeitstempel, wo Frische gefordert ist, ist sie grau, nie grün.

## Zeitbudget je Quelle

`src/dashboard/cockpit/sources.py` liest jede Quelle (Snapshot, Chart, Vorbereitung,
Plan- und Trader-Journal, Backup- und Server-Bericht) in einem eigenen Thread und
wartet höchstens 1,5 Sekunden. Eine langsame Quelle macht ihre Kacheln grau
("antwortet nicht"), statt den Server zu blockieren. Läuft eine Abfrage noch,
startet die nächste Anfrage keine zweite.

## Grenzen

- Nur Anzeige: Das Cockpit liest, was TIM schon schreibt, und schreibt nichts.
- Keine neuen Signale oder Berechnungen, kein Order-Knopf.
- Zeiten in deutscher Ortszeit (Europe/Berlin).
