# Neues Control Center (Cockpit) unter /neu

Stand: 24.10.2026, Paket P1 des Bauplans "Neues TIM-Dashboard".

Das neue Control Center läuft im selben Prozess wie das bisherige (Port 8765) und
ist unter `http://127.0.0.1:8765/neu` erreichbar. Die bisherigen Seiten bleiben
unverändert, bis Uzi das neue Dashboard abnimmt und umgeschaltet wird (Paket P4).

## Bereiche

| Bereich | Adresse | Stand |
| --- | --- | --- |
| Lage (Startseite) | `/neu` | gebaut (P1) |
| Markt & Pläne | `/neu/markt` | verweist auf die bisherigen Seiten, Neubau in P2 |
| Forschung | `/neu/forschung` | verweist auf die bisherigen Seiten, Neubau in P3 |
| Betrieb | `/neu/betrieb` | verweist auf die bisherigen Seiten, Neubau in P3 |
| System & Freigabe | `/neu/system` | verweist auf die bisherigen Seiten, Neubau in P3 |

Maschinenlesbar: `GET /api/cockpit` (Modell der Startseite), `GET /neu?fragment=1`
(neu gerenderter Seiteninhalt für die Aktualisierung alle 30 Sekunden).

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
