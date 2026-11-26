# INFRA-11: Parallele Entwicklung und Bereitschaft

Stand: 26.11.2026, Version 0.1 (Entwurf). Auftrag: Mission INFRA-11 des Owners vom 26.11.2026.
Status: **nur Vorbereitung.** Nichts eingerichtet, nichts aktiviert, kein Merge, keine Löschung.
INFRA-09 Einrichtung: **HOLD.** INFRA-10 Owner-only: **INCONCLUSIVE.** `TRADING_AUTHORIZED=NO`.

Öffentliches Repo: keine Hostnamen, Adressen, Konten, Schlüssel oder UUIDs in diesem Dokument.

## P0 Projektstand (gelesen 26.11. ca. 13:50 Ortszeit)

Quellen: #285 (15 Kommentare), #372 (58 Kommentare), Liste der offenen PRs. Bestandene Prüfungen
wurden nicht wiederholt.

### Was bereits bestanden ist (nicht erneut prüfen)

| Prüfung | Ergebnis | Beleg |
|---|---|---|
| INFRA-10.1 Gates 1–3 (Repo-Integrität, Regression, Laufzeit) für #397 und Private #464 | PASS (Codex, Cloud-Umgebung) | #372 Kommentar 7172531879 |
| INFRA-10.1 Netzwerk-Durchsetzung (Gate 4 Teil) | PASS | ebd. |
| PG18 Dump/Restore synthetisch | PASS | ebd. |
| Cold Store #394 intern (81 Tests, Mac PG18 215 Tests, CI grün) | grün, aber **kein** Codex-Urteil | #285 Kommentar 7149028693 |

### Offene PRs und ihre Abnahme

| Gruppe | PRs | Wartet auf | Art |
|---|---|---|---|
| Archiv INFRA-09 | #389, #390, #392, #393, #394 | Codex-Abnahme an den SHAs aus #285 7149028693 | **technisch**: Review fehlt |
| Codex-Cloud INFRA-10.1 | #397 (Public), Private #464 | Owner-only-Nachweis mit Nicht-Owner-Rolle | **organisatorisch** |
| Codex-Dauerprüfung INFRA-10 | #396 | Owner-Entscheidungen §7, Codex-Prüfung | organisatorisch + Review |
| TIM 2.0 Pakete | #376 B, #377 A, #378 C, #379 D, #380 E, #381, #382, #383 | Codex-PASS + Uzis Freigabe; B-Korrektur (Versuch 4) vorbereitet, nicht gepusht | technisch (Review) + Freigabe |
| Prüfstand | #384 | nie mergen | – |
| Volatilität | #385 | GO je Paket V0–V5 | organisatorisch |
| Server | #388 Watchdog | Review, Server-Freigabe | technisch + Freigabe |
| Chris | #398 (S42–S44), #369 (XMR) | Chris | fremd, nur lesen |
| Sonstiges | #371 zurückgestellt, #363, #362 Dependabot | Owner | – |

### Technische Blocker und organisatorische Nachweise getrennt

Technisch (lösbar ohne Owner-Handgriff, sobald Codex prüft):

1. Archivkette #389–#394 hat kein Codex-Urteil. Die Codex-Cloud-Umgebung läuft seit 25.11. (Gates 1–3
   PASS). Die Abnahme kann jetzt dort laufen; Übergabe siehe Abschnitt "Übergabe an Codex".
2. TIM-2.0-Pakete A–E brauchen ein Codex-Review auf ihren aktuellen HEADs.
3. Selbstfreigabe ist heute technisch möglich: alle Agenten schreiben unter demselben GitHub-Konto, der
   Kopf `[AGENT: CODEX]` ist nur Text. Gegenmaßnahme als Code in #396 (`src/review_pipeline/`).

Organisatorisch (nur der Owner oder Chris):

1. Owner-only der Codex-Cloud-Umgebung unabhängig nachweisen (Nicht-Owner-Testrolle). Blockiert nur das
   Gesamturteil INFRA-10, **nicht** die Archiv-Abnahme selbst.
2. INFRA-09: Uzis bedingtes GO vom 24.11. gilt weiter; Bedingung "Codex-PASS" fehlt.
3. Fragen an Chris (Archiv-Doku §15): Redundanz der Warpgate-Platte, Fernwartungskonsole.

## P1 Archiv-Einrichtung vorbereiten (nichts eingerichtet)

### Plan geprüft

Einrichtungsplan `docs/ARCHIV_WARPGATE_UEBERGANG.md` §11 (auf #394) gelesen. Er ist fail-closed
(`set -euo pipefail`, jeder Schritt bricht ab, wenn das Ziel existiert), formatiert nur eine neue
Image-Datei, schützt vor Trim (`X-fstrim.notrim`, `-E nodiscard`), setzt einen unbeschreibbaren
Einhängepunkt und einen root-Wächter. Rückweg (Aushängen, fstab-Zeile auskommentieren, nichts löschen)
und Wiederherstellung (§12) sind beschrieben.

Ergänzungen, die dieses Paket liefert:

- **Lesender Vorab-Prüfer** `python -m src.archive_readiness.preflight` (neu, 11 Tests). Misst nur
  (`statvfs`, Existenz der Ziele, Einhängung) und rechnet alle Bedingungen nach: 32 GiB Image,
  26-GiB-Grenze, 15 % frei nach dem Image **und** während des Restore-Tests, mit 5 % Puffer auf den
  zuletzt belegten Restore-Bedarf. Fehlt ein Messwert, lautet das Urteil INCONCLUSIVE, nie PASS. Ein
  PASS ist keine Einrichtungsfreigabe.
- Hinweis zum Plan: Schritt 0 verlangt fest 300 GB frei. Der Vorab-Prüfer ersetzt diese Zahl nicht,
  sondern prüft zusätzlich die Restore-Reserve; beide müssen bestehen.

### Speicherstand heute (nur lesend, 26.11. 13:50 Ortszeit)

| Messung | Wert |
|---|---|
| Warpgate-Platte, Größe | 391.999.193.088 B |
| frei für Nicht-root | **324.995.493.888 B** (am 25.11.: 325.019.078.656 B, also −23,6 MB) |
| Image-Ordner, Einhängepunkt, Dienstkonto, fstab-Eintrag | alle **nicht vorhanden** (nichts eingerichtet) |
| Warpgate | aktiv, läuft unverändert seit 01.11. |
| Trim-Zeitgeber | aktiv (wie bekannt, Gegenmittel im Plan) |
| Nächster Restore-Test | So 29.11. 05:30, letzter Lauf 22.11. |

Rechnung mit 32 GiB: frei danach 290,64 GB; während des Restore-Tests 81,97 GB = **20,9 %** (Vorgabe
15 %). Mit 5 % Wachstumspuffer auf den Restore-Bedarf: 71,5 GB = 18,2 %. **Bedingung erfüllt.**
100 GiB würden weiter scheitern (Test im Vorab-Prüfer).

Neuer Befund außerhalb des Archivs (nur gemeldet, nichts geändert): Die Systempartition `/var` des
Servers ist zu **91 %** belegt (5,2 GB frei; am 25.11. 88 %). `/srv` 87 %. Das betrifft den Archivplan
nicht (er nutzt die Warpgate-Platte), kann aber Dienste mit Logs unter `/var` stören. Frage an Chris.

### Ablauf, sobald Codex PASS meldet (Reihenfolge, je Schritt Stopp bei Fehler)

1. Vorab-Prüfer am Server ausführen (lesend). Nur bei PASS weiter.
2. Einrichtung nach §11 (deckt Uzis bedingtes GO vom 24.11. ab, ohne weitere Rückfrage).
3. Nachprüfung lesend (§11 Ende): Einhängung, volle Belegung, `cold-verify` OK, Warpgate-Startzeit
   unverändert, Anmeldung klappt, rund 290 GB frei.
4. **Stopp.** Erster Archivlauf und Zeitplan brauchen je ein eigenes GO.

### Erster manueller Archivlauf (vorbereitet, eigenes GO nötig)

- Umfang klein: ein Symbol, ein Tag (Binance Spot, ca. 20 MB). Export am Mac (`export`), Übertragung
  (`transfer`, sha256 vor und nach), dann `cold-ingest` in den Store.
- Abbruch bei BUDGET_STOP, DISK_STOP, CONFLICT, FILE_INVALID, `cold-verify` FAIL oder wenn Warpgate
  langsamer reagiert.
- Abnahme: `cold-verify` OK, Ledger-Eintrag mit `batch_id` und `content_sha256`, Vorab-Prüfer danach
  weiter PASS, Warpgate unbeeinträchtigt.
- Rückweg: Lauf anhalten, aushängen (§11). Nichts wird gelöscht.
- Wiederherstellungsprobe direkt danach: `cold-migrate --to <leerer Ordner>` auf dem Mac, bitgleicher
  Vergleich, Importer-Trockenlauf gegen eine Wegwerf-Datenbank (§12 Stufe 2 und 3).

## P2 Codex-Prüfstrecke (#396)

Weiterentwicklung im Entwurfs-PR #396, ohne eine Regel oder einen Workflow zu aktivieren. Details dort.

## P3 Forschung

Bestandsaufnahme und acht priorisierte Offline-Aufgaben: `docs/infra11/P3_FORSCHUNGSSTAND.md`.
Kurz: Alle vier bekannten Point-in-Time-Lücken (Handelsseite, Live-Lage, Gamma-Frische, `dvol_change`
als Vermutung) bestehen auf `platform-main` weiter, weil die Pakete A–C ungemergt sind. Property-Tests
und inverse Optionskontrakte fehlen. Kein Studienbefund rechtfertigt eine Handelsnutzung.

## P4 Werkzeuge (gelesen am Mac, 26.11.)

| Werkzeug | Stand | Einsatz in INFRA-11 |
|---|---|---|
| OpenCode | 1.18.33 vorhanden | nicht nötig gewesen |
| GLM | kein eigenes Programm; nur über OpenCode | nicht genutzt |
| Graphify | 0.9.29 vorhanden, `graphify-out/` im Repo | nicht genutzt (gezielte Suche reichte) |
| Serena | Konfiguration vorhanden, Server nicht im Pfad | nicht genutzt |
| RTK | 0.49.0 vorhanden | nicht genutzt |
| Context Mode | vorhanden | nicht genutzt |
| Ponytail | **nicht gefunden** | – |
| Codex-CLI | vorhanden | Prüfung bleibt bei Codex, Claude startet keine Codex-Läufe |
| TIM-Skills/Subagenten | vorhanden | zwei Hilfsagenten (günstiges Modell) für P2-Code und P3-Bestand; ihr Ergebnis ist keine unabhängige Prüfung |

## Übergabe an Codex (READY_FOR_REVIEW)

1. Archivkette #389, #390, #392, #393, #394 an den SHAs aus #285 7149028693, Abnahmeliste 1–12 dort.
2. Dieses Paket (Vorab-Prüfer, Doku).
3. #396 mit `src/review_pipeline/`.

Jeweils PASS / FAIL / INCONCLUSIVE je Punkt, mit Befehl und Ausgabe. Ein Urteil gilt nur für den
genannten HEAD-SHA.

## Nächste Schritte (priorisiert)

1. Codex prüft die Archivkette (technischer Blocker, kein Owner-Handgriff nötig).
2. Owner: Owner-only-Nachweis für die Codex-Cloud (organisatorisch).
3. Bei Archiv-PASS: Vorab-Prüfer, dann Einrichtung nach §11, dann Stopp.
4. Codex prüft TIM-2.0-Pakete B → A → C; danach Forschungsaufgaben A2–A4 aus P3.
5. Chris: `/var` auf dem Server zu 91 % belegt.
