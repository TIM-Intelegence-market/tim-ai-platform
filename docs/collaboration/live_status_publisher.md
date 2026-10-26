# Live-Status-Publisher für Kollaboratoren (#67)

> **Archiviert am 26.10.2026** (Grün-Plan Paket I1, `docs/PAKETINVENTAR.md`): Der Code `src/collaboration/` und seine Tests sind aus `platform-main` entfernt und stehen im Zweig `archiv/unerreichte-pakete-2026-10-26` (Stand 06c8bc2). Diese Seite beschreibt den archivierten Stand.

Code: `src/collaboration/publisher.py` (baut auf Prüfer #258, Snapshot #259 und Veröffentlichungsplan #260 auf).

## Ablauf eines Laufs

1. Sperre (`.git/tim-collab-publisher.lock`); läuft schon ein Lauf, wird übersprungen.
2. Snapshot aus den gelesenen Beobachtungswerten bauen (nur erlaubte Felder, nur Zahlen/Wahrheitswerte).
3. Prüfen (`validate_live_status`); bei Fehler `safe_stop`, nichts wird geschrieben.
4. Abbruch, wenn im Index schon etwas liegt oder der Snapshot-Pfad lokal geändert ist.
5. Plan: nur `artifacts/collaboration/live_status.json`, nur wenn sich mehr als die Zeitstempel geändert hat.
6. Standard ist Probelauf (Stufe A): nichts schreiben. Mit `--commit`: Datei atomar schreiben, nochmals prüfen,
   genau diesen Pfad stagen, kontrollieren, dass der Index exakt diese eine Datei enthält, committen.
7. Mit `--push-branch X` auf diesen Branch pushen. Der Branch muss auf dem Remote schon existieren (einmal von
   einem sauberen Stand anlegen). Gepusht wird nur, wenn sich HEAD vom Remote-Branch ausschließlich in der
   Snapshot-Datei unterscheidet; andere lokale Commits des Host-Checkouts gehen so nie mit. Scheitert der Push,
   bleibt der Commit lokal und der nächste Lauf versucht es erneut. TIM läuft davon unberührt weiter.

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
