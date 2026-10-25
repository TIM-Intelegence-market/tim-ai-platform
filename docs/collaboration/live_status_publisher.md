# Live-Status-Publisher für Kollaboratoren (#67)

Code: `src/collaboration/publisher.py` (baut auf Prüfer #258, Snapshot #259 und Veröffentlichungsplan #260 auf).

## Ablauf eines Laufs

1. Sperre (`.git/tim-collab-publisher.lock`); läuft schon ein Lauf, wird übersprungen.
2. Snapshot aus den gelesenen Beobachtungswerten bauen (nur erlaubte Felder, nur Zahlen/Wahrheitswerte).
3. Prüfen (`validate_live_status`); bei Fehler `safe_stop`, nichts wird geschrieben.
4. Abbruch, wenn im Index schon etwas liegt oder der Snapshot-Pfad lokal geändert ist.
5. Plan: nur `artifacts/collaboration/live_status.json`, nur wenn sich mehr als die Zeitstempel geändert hat.
6. Standard ist Probelauf (Stufe A): nichts schreiben. Mit `--commit`: Datei atomar schreiben, nochmals prüfen,
   genau diesen Pfad stagen, kontrollieren, dass der Index exakt diese eine Datei enthält, committen.
7. Mit `--push-branch X` auf diesen Branch pushen. Scheitert der Push, bleibt der Commit lokal, TIM läuft weiter.

Der Publisher liest nur die übergebenen Beobachtungswerte. Er verändert nie Queue, Outbox, Datenbank oder
Trading-Zustand.

```sh
python -m src.collaboration.publisher --repo /pfad/zum/checkout --observed /pfad/observed.json            # Probelauf
python -m src.collaboration.publisher --repo /pfad/zum/checkout --observed /pfad/observed.json --commit   # Stufe B
```

## Gesundheit für Leser

`derive_health(doc, now=…)` liefert `HEALTHY`, `DEGRADED`, `STALE` oder `SAFE_STOP` nach Regeln
`collab-health/1`: ungültiger Snapshot → `SAFE_STOP`; älter als 15 min (drei verpasste 5-Minuten-Läufe) →
`STALE`; veraltete Collector, blockierte Queue-Einträge, kritische Incidents oder fehlgeschlagene
Qualitätsprüfung → `DEGRADED`.

## Offen (nicht per Code lösbar)

- Quelle der Beobachtungswerte auf dem TIM-Host anbinden (nur lesend) und ersten echten Snapshot prüfen.
- Scheduler (launchd/systemd, 5 min) einrichten, Stufe A beobachten, dann Stufe B. Braucht Uzis Freigabe.
- GitHub-Workflow als zweite Prüflinie: `.github/` ist gesperrt, eigener PR nötig.

Tests: `tests/test_collaboration_publisher.py` (echtes Wegwerf-Git-Repo).
