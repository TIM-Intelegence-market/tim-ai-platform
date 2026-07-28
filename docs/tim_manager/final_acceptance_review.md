# TIM Intelligence Manager — Final Acceptance and Provenance Review

Prüfdatum: 2026-07-28  
Prüfobjekt: `/Users/tim/Documents/TIM/tim`  
Abnahmestatus: **PASS**

Release-Engineering-Nachtrag: Dieser Bericht dokumentiert die technische
Abnahme unmittelbar vor der Repository-Initialisierung. Seit dem
Foundation-Auftrag besitzt TIM ein eigenes autoritatives Repository unter
`/Users/tim/Documents/TIM/tim`. Der historische Akzeptanz-Snapshot bleibt
unverändert; die aktuelle Release-Autorität wird durch
`refs/tags/tim-im-v1.0.0` bestimmt.

## 1. Begründung des Status

Die lokale technische Abnahme ist vollständig erfüllt:

- alle 20 Pflichtszenarien bestanden, ohne XFAIL oder Skip;
- S11 erkennt zwei widersprüchliche, belegte Status-Claims deterministisch,
  erhält beide Claims und Evidenzreferenzen und zeigt den Konflikt in Snapshot,
  Management-Query und Statusbericht;
- die vollständige TIM-IM- und TIM-Regression blieb fehlerfrei;
- Doctor und Validate lieferten Exit-Code `0`;
- zwei unveränderte Folge-Scans behielten dieselbe Snapshot-ID;
- aktueller Snapshot, versionierte Kopie und Export sind bytegleich;
- Protected- und MCP-Prüfung blieben erfolgreich;
- aktive Git-Provenienz bleibt korrekt `unversioned`.

Nachgewiesene, nicht blockierende Grenzen bleiben:

- 145 `pytest-asyncio`-Deprecation-Warnungen;
- Widerspruchserkennung arbeitet bewusst nur mit expliziten
  `tim_manager_claims` und kontrollierten Status-/Boolean-Regeln;
- der veröffentlichte Workspace-Agent ist weiterhin nicht an TIM-IM
  angebunden;
- optionale, nicht konfigurierte Quellgruppen bleiben sichtbar dokumentiert;
- TIM besitzt weiterhin kein eigenes Git-Repository.

Es wurde keine Dependency-Migration und keine neue Produktfunktion
implementiert.

## 2. Prüf- und Änderungsgrenze

Manuell beziehungsweise durch TIM-IM verändert wurden nur TIM-IM-Code,
TIM-IM-Schema, TIM-IM-Tests, TIM-IM-Dokumentation und TIM-IM-Artefakte. Nicht
manuell und nicht durch TIM-IM verändert wurden:

- wissenschaftlicher TIM-Core,
- historische TIM-Daten,
- bestehende Research-Ergebnisse; die unten getrennt ausgewiesenen
  Live-Research-Cache-/Triggerdateien änderten sich während des laufenden
  TIM-Prozesses; die Writer-Zuordnung ist unten mit ihrer Beweisgrenze
  dokumentiert,
- Trading-Komponenten,
- Git-Metadaten, Index, Branch, Commit und außerhalb des untracked TIM-Pfads
  liegende Dateien des übergeordneten Repositories `/Users/tim`.

Vier geschützte Runtime-Dateien wurden während des laufenden TIM-Prozesses im
Implementierungsfenster fortgeschrieben. Diese Änderungen werden unten getrennt
von TIM-IM-Schreibvorgängen ausgewiesen.

## 3. Git-Provenienz

### 3.1 Festgestellter Zustand

| Prüfung | Nachweis |
|---|---|
| Eigenes `.git` unter TIM | nicht vorhanden |
| Übergeordneter Git-Root | `/Users/tim` |
| Übergeordneter Commit | `a418894d33ba2426afe0f31d119332043bddd406` |
| Commit-Betreff | `Add Codex usage fallback protocol` |
| Durch den Parent-Index verfolgte Dateien unter `Documents/TIM/tim` | `0` |
| Parent-Status für TIM | untracked, beispielsweise `?? Documents/TIM/tim/.gitignore` |
| Neues Git-Repository initialisiert | nein |
| Parent-Git-Metadaten, Index, Branch oder Commit verändert | nein |

Der Parent-Commit ist deshalb keine TIM-Codeversion und darf nicht als
autoritative TIM-Provenienz verwendet werden.

### 3.2 Aktive Provenienz

Der aktuelle Snapshot
`artifacts/tim_manager/snapshots/current.json` enthält:

| Feld | Aktueller Wert |
|---|---|
| `schema_version` | `1.1` |
| `repository_status` | `unversioned` |
| `repository_commit` | `null` |
| `authoritative_git_repository` | `false` |
| `repository_dirty` | `null` |
| `content_manifest_hash` | `22b258c5fd8eac5e4d3cff0ef648b96c1ce00665c6b11e58a7f5e2b491a10c1b` |
| `snapshot_id` | `43312fa2-a863-5f56-9765-0d7a224239be` |
| interner `snapshot_hash` | `b9da01d0bec0798f968c6cb0eeea3fce31f3fa49cbbcd19373fd2952e21f0a77` |

Der Parent-Kontext ist separat und ausdrücklich nicht autoritativ:

```json
{
  "git_root": "/Users/tim",
  "branch": "main",
  "commit": "a418894d33ba2426afe0f31d119332043bddd406",
  "project_path_tracked": false,
  "context_only": true
}
```

`change_manifest.json` und `implementation_state.json` verwenden
`repository_status=unversioned`, `repository_commit=null`,
`authoritative_git_repository=false`, denselben separaten
`parent_git_context` und den aktuellen `content_manifest_hash`. Das Feld
`repository_dirty` ist in diesen beiden Verwaltungsartefakten nicht enthalten.

Der aktive SQLite-Index enthält 228 Artefakt-Datensätze. Eine
`sqlite3 -readonly`-Prüfung der JSON-Felder ergab:

- nicht-null `provenance.repository_commit`: `0`,
- `provenance.authoritative_git_repository=true`: `0`,
- Parent-Commit unter `provenance.parent_git_context.commit`: `228`.

Damit wird der Commit im aktiven Index ausschließlich als separater
Parent-Kontext geführt.

Der `content_manifest_hash` ist reproduzierbar definiert als SHA-256 über
kanonisches JSON (`sort_keys=true`, UTF-8, Separatoren `,` und `:`) einer nach
`(source_id, normalized_path)` sortierten Liste mit genau den Feldern
`source_id`, `normalized_path`, `content_hash`, `size_bytes` und `status`.
Der persistierte Probe-Lauf reproduzierte aus dem finalen Scan exakt:

```text
22b258c5fd8eac5e4d3cff0ef648b96c1ce00665c6b11e58a7f5e2b491a10c1b
```

Ausgeführter Befehl, Exit-Code `0`:

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python artifacts/tim_manager/reports/final_verification_probes.py provenance
```

### 3.3 Historische TIM-IM-Ausgaben

Sieben historische Scan-Dateien und vier historische Snapshot-Dateien enthalten
noch das frühere Feld `repository_commit` mit dem Parent-Commit. Sie werden
nicht mehr als autoritative TIM-Provenienz verwendet und wurden wegen des
Verbots, historische Daten umzuschreiben, nicht nachträglich verändert:

- Scans:
  `03379258-f82d-5e7d-be94-b156bdb47968`,
  `4d12c501-fc72-5d2c-9e8d-a1afcc3d73e8`,
  `6502351f-8c74-5fbc-bcef-a5e7f2e9d2df`,
  `678bbfeb-afab-524c-8dca-4999cbd564e8`,
  `911b06e5-d028-54c8-a638-0094e745e87d`,
  `c2a7fd0a-e513-55cf-8667-d796ef0c6db6`,
  `df6d8563-6722-5821-8c47-fe924c88d3a9`.
- Snapshots:
  `1012c72f-e6c8-531a-af98-d38baa0a9495`,
  `24e75ee4-38a2-5cf5-8cd2-2b8f629a2411`,
  `4f260059-e2a0-59c5-a629-bb16f234f39c`,
  `710e9a04-6af2-5f86-8808-716760816d04`.

Die aktive Statusdatei, der aktive Export und alle neuen Scans verwenden den
Parent-Commit nicht als `repository_commit` und nicht autoritativ. Sie führen
ihn ausschließlich als `parent_git_context.commit` mit `context_only=true`.

## 4. Geschützte Dateien

### 4.1 Baseline und Nachweisgrenze

Die Pre-Implementation-Baseline enthält 48 geschützte Dateien. Das
Backup-Manifest deklariert `created_at_utc=2026-07-28T07:21:33Z`; die
Hashliste `protected_data_hashes.txt` wurde um `07:22:10Z` geschrieben. Weil
TIM während der Inventarisierung lief, war diese Baseline nicht atomar. Die
vier unten genannten Baseline-Hashes entsprechen dem hashverifizierten
Inhaltsstand bis ungefähr `07:22:04Z`. Der reproduzierbare finale
Protected-Probe-Lauf ergab:

- unverändert gegen Baseline: `44`,
- verändert gegen Baseline: `4`,
- fehlend: `0`.

Es wird ausdrücklich **keine vollständige TIM-V1-Unverändertheit** behauptet.

### 4.2 Vier während der Implementierung veränderte Dateien

Die folgende Nachher-Spalte ist ein fester **Implementierungs-Zwischenmesspunkt
um 07:39:04Z**, nicht der spätere Endstand der Schlussverifikation.

| Vollständiger Pfad | Vorher: SHA-256, rekonstruierte Größe, Inhaltszeit | Zwischenmesspunkt 07:39Z: SHA-256, Größe, Zeit | Dateityp | Fachliche Funktion |
|---|---|---|---|---|
| `/Users/tim/Documents/TIM/tim/data/operational/runtime_launchd.err.log` | `94dd9b19c191daf65586a1469400b815f2b5e2bbe6820b6cbb1a360f4f574050`; 7.070.925 Byte; letzter enthaltener Trigger `2026-07-28T07:22:03.988042Z` | `8b62fd1def1dd37825ccef89291c4f44981dfb0fdc6c649156fb9cee19b72a07`; 7.086.849 Byte; letzte enthaltene Logzeile `2026-07-28 09:39:04,256` lokal (`+0200`) | Textlog, `text/plain` | StandardError-/Logging-Ziel (FD 2) des LaunchAgents; enthält Runtime- und Research-Trigger-Protokollierung |
| `/Users/tim/Documents/TIM/tim/data/research/module_a_cache.jsonl` | `e3ca84f1b4b414acf222ce70d01ddfc79d953ed3d3a77d707097d96f17783b28`; 3.995.642 Byte; letzter `created_at` `2026-07-28T07:22:03.957789Z` | `994935df167f88496009d35f45147854cae1310ffaee6b194b74ece8711ee346`; 4.004.388 Byte; mtime `2026-07-28T07:39:04.247038Z`, letzter `created_at` `2026-07-28T07:39:04.202614Z` | JSON Lines; MIME-Erkennung `application/json` | idempotenter Cache deterministischer Ergebnisse von Research Module A |
| `/Users/tim/Documents/TIM/tim/data/research/trigger_events.jsonl` | `1ecfb8e9847d75092d59495fbba6c934835f5ca9c0530060e4b74ea499690031`; 1.721.941 Byte; letzter `triggered_at` `2026-07-28T07:22:03.988042Z` | `a534bcee975c68f965cd8c16d1edf811924f7d6e4b058dbedbed8754bbf741d9`; 1.725.723 Byte; mtime `2026-07-28T07:39:04.251281Z`, letzter `triggered_at` `2026-07-28T07:39:04.247629Z` | JSON Lines; MIME-Erkennung `application/json` | append-only Journal erfolgreich verarbeiteter Research-Trigger |
| `/Users/tim/Documents/TIM/tim/data/research/trigger_state.json` | `fe4e5c8cd21fa69a6af1bf6bb9d7870c76a6bafb2329a31e7eb6564bc4c6020e`; 458.500 Byte; `updated_at` `2026-07-28T07:22:03.989551Z` | `05d6875840ed3bcd411bbe11054900a905a574631a89336a075289460281272b`; 459.508 Byte; mtime `2026-07-28T07:39:04.250353Z`, `updated_at` `2026-07-28T07:39:04.248856Z` | JSON; `application/json` | atomar ersetzter Deduplizierungszustand bereits verarbeiteter Research-Trigger |

Alle vier Dateien sind als **volatile protected runtime** klassifiziert, nicht
als immutable.

`protected_data_hashes.txt` speichert nur Hash und Pfad. Die
Vorher-Größen/logischen Zeitstempel wurden aus den weiterhin exakt erhaltenen,
hashgleichen Append-Präfixen beziehungsweise JSON-Inhalten rekonstruiert. Der
Runtime-Zwischenhash
`8b62fd1def1dd37825ccef89291c4f44981dfb0fdc6c649156fb9cee19b72a07`
ist reproduzierbar der SHA-256 des ersten
7.086.849-Byte-Präfixes, wurde aber nicht zeitgleich durch einen TIM-IM-Scan
persistiert. Die drei strukturierten 07:39-Werte sind zusätzlich in den
historischen TIM-IM-Scans erhalten.

### 4.3 Schreibberechtigung, Ereignisse und Prozesszuordnung

| Datei | TIM-IM-Anwendungsberechtigung | Betriebssystem-Modus bei Schlussprüfung | Tatsächliche TIM-IM-Schreibereignisse | Bekannter oder wahrscheinlicher Writer |
|---|---|---|---|---|
| `runtime_launchd.err.log` | verweigert durch `protected_paths: data/**` | `-rw-r--r--`, Eigentümer schreibbar | keine TIM-IM-Schreibung nachgewiesen; Datei wird nicht als strukturierter TIM-IM-Quelltyp ingestiert | sicherer Prozessbezug: PID `4494`, `/Users/tim/Documents/TIM/tim/main.py --init-schema`, hat Dateideskriptor 2 auf dieser Datei geöffnet |
| `module_a_cache.jsonl` | verweigert | `-rw-r--r--`, Eigentümer schreibbar | keine TIM-IM-Schreibung nachgewiesen; letztes persistiertes Change-Event vor den unveränderten Folge-Scans: `f1b02166-344b-5e08-ac9c-c4960772138d` im Stabilisierungsscan | `LocalResearchAgent._cache`, `src/research/module_a/agent.py:42-48`; stark mit PID 4494 korreliert; Dashboard-Research-POSTs können denselben Cachepfad ebenfalls verwenden |
| `trigger_events.jsonl` | verweigert | `-rw-r--r--`, Eigentümer schreibbar | keine TIM-IM-Schreibung nachgewiesen; letztes persistiertes Change-Event vor den unveränderten Folge-Scans: `38c7749d-ea64-55db-8ccc-c12d15ee43d1` im Stabilisierungsscan | `ResearchTrigger._log`, `src/research/trigger.py:63-65`; stark mit PID 4494 korreliert |
| `trigger_state.json` | verweigert | `-rw-r--r--`, Eigentümer schreibbar | keine TIM-IM-Schreibung nachgewiesen; letztes persistiertes Change-Event vor den unveränderten Folge-Scans: `56e35fbd-7730-58a6-acb3-42c2006b7bf4` im Stabilisierungsscan | `ResearchTrigger._persist`, `src/research/trigger.py:60-61`; stark mit PID 4494 korreliert |

Die Dateisystemrechte allein verhindern einen Schreibzugriff durch andere
Prozesse desselben Benutzerkontos nicht. Die TIM-IM-Anwendungsschicht hat alle
fünf manuell geprüften geschützten Pfade abgewiesen. Eine
Betriebssystem-Auditspur mit per-write PID war nicht vorhanden; außer dem
offenen Log-Dateideskriptor ist die Prozesszuordnung deshalb eine durch
Prozesspfad, Quellcode, Reihenfolge und Zeitstempel gestützte Zuordnung.
Nur die Zuordnung von PID 4494 zu `runtime_launchd.err.log` ist über den offenen
Dateideskriptor direkt nachgewiesen; für die drei Research-Dateien fehlt ein
per-write Betriebssystem-Audit.

### 4.4 Spätere feste Verifikations-Cutoffs

Der letzte persistierte Quellscan beobachtete die drei ingestierten
Research-Runtime-Dateien am `2026-07-28T08:30:44.919450Z`:

| Datei | SHA-256 | Größe | mtime UTC |
|---|---|---:|---|
| `module_a_cache.jsonl` | `47c9cae9160a1e6ef7ff98ce8d0affd261abd03d6e03ad13b9c5c28ed1a5155c` | 4.028.768 | `2026-07-28T08:30:03.439702Z` |
| `trigger_events.jsonl` | `3fd09574819d3bad9f9b6c5fb40594edfb9941ca78d3c8c3ad99fd80ae254d2c` | 1.736.262 | `2026-07-28T08:30:03.451775Z` |
| `trigger_state.json` | `e9c67c6cf7818ae11632b4146a45db8eb314a112955cab6b0437f39c26c76b0a` | 462.316 | `2026-07-28T08:30:03.447253Z` |

Der finale Protected-Probe-Lauf nach der S11-Korrektur erfasste folgenden
festen Dateistand um `2026-07-28T09:41:02Z`:

| Datei | SHA-256 | Größe | mtime UTC |
|---|---|---:|---|
| `runtime_launchd.err.log` | `364a938fcc3832e7dc74ef8e10253242866f68eb089548e9f9cd77c7234af8a8` | 7.187.798 | `2026-07-28T09:41:02.822974Z` |
| `module_a_cache.jsonl` | `cdec7b8f68fd26b6bb6b18ea212ceffb1b41e8257e80c7aee76571b8c964a7db` | 4.061.891 | `2026-07-28T09:41:02.813359Z` |
| `trigger_events.jsonl` | `85809cf63b0abbd1a93dcb6f091f8494c4e6de73ec0e23d0102983e7191bcd4a` | 1.750.589 | `2026-07-28T09:41:02.817146Z` |
| `trigger_state.json` | `ad8ca1aa2ec7ebea6a25b2646631d970891f5aa08b2841f64b27c1063e5ed41d` | 466.132 | `2026-07-28T09:41:02.816287Z` |

PID 4494 läuft weiter; diese Werte sind deshalb ausdrücklich
zeitpunktbezogene Cutoffs und keine Behauptung eines später unveränderten
Dateistands. Der ausgeführte Befehl und sein stdout sind in
`artifacts/tim_manager/reports/final_verification_probe_results.md`
persistiert; SHA-256:
`ec58de43f15372d8fdf9f9273b1144caffb3d4d133f4a96cbe18186d991acd0c`.

### 4.5 Getrennte Schutzklassen

Für die 48 Baseline-Dateien wird ab dieser Prüfung folgende fachliche Trennung
verwendet. Sie ist eine Dokumentationsklassifikation; die bestehende
TIM-IM-Policy verweigert weiterhin beide Klassen.

**Immutable protected files — 19 Baseline-Einträge**

- vier abgeschlossene Audit-/Provenienzartefakte:
  `tim_v1_change_manifest.json`, `tim_v1_data_flow_graph.json`,
  `tim_v1_validation_results.json`,
  `TIM-V1-UNFREEZE-20260727T170852Z.json`;
- fünf Dateien unter
  `data/operational_archive/pre_acceptance_20260720T151302Z/`;
- `data/research/insights/README.md`;
- sieben bestehende Einträge unter `data/research/module_b_reports/`
  einschließlich `.gitkeep`;
- `data/research/snapshots/README.md`;
- `data/research/validation/tim_v1_scientific_validation.json`.

**Volatile protected runtime files — 29 Baseline-Einträge**

- `artifacts/audits/tim_v1_pipeline_runs.jsonl`;
- `data/benchmarks/latest.json`;
- 17 Live-Dateien unter `data/operational/`;
- `data/quality/latest.json`;
- `data/research/audit/latest.json`;
- `data/research/module_a_cache.jsonl`;
- `data/research/quality/latest.json`;
- zwei `2026-07.in_progress`-Snapshots;
- `data/research/snapshots/scientific_maturity_history.jsonl`;
- `data/research/status/tim_v1_readiness.json`;
- `data/research/trigger_events.jsonl`;
- `data/research/trigger_state.json`.

Von den 29 volatilen Dateien änderten sich im geprüften
Implementierungsfenster genau die vier detailliert beschriebenen Dateien. Die
übrigen 25 volatilen Dateien waren hashgleich; ihre Volatilität wird dadurch
nicht zu Immutabilität umgedeutet.

## 5. Pflicht-Akzeptanzmatrix

Die vollständige Einzelzuordnung steht in
`docs/tim_manager/acceptance_test_matrix.md`.

| Kennzahl | Ergebnis |
|---|---:|
| Pflichtszenarien mit konkreter Testfunktion | 20/20 |
| Pytest-Testfunktionen bestanden | 20 |
| XFAIL/Skips | 0 |
| Nicht zugeordnet | 0 |

S11 ist durch eine echte deterministische Implementierung erfüllt. Die
bekannten Grenzen einzelner Szenarien sind in der Matrix weiterhin
ausgewiesen; der jeweils definierte Pflichtfall ist bestanden.

Der persistierte JUnit-Nachweis ist
`artifacts/tim_manager/reports/mandatory_acceptance.junit.xml`.

## 6. Source Coverage

### 6.1 Bedeutung von „keine erforderliche Quelle fehlt“

Die produktive Konfiguration besitzt sieben Top-Level-Quellen. Nur
`source_code`, `tests`, `documentation` und `configuration` sind als
`required=true` gesetzt. Alle vier sind erreichbar. Daher ist
`missing_required_sources=0` formal korrekt, beweist aber **nicht**, dass alle
21 erwarteten Quellgruppen konfiguriert oder vorhanden sind.

Der aktuelle Snapshot umfasst 228 eindeutige Artefakte:

| Konfigurierte Top-Level-Quelle | Required | Status | Freshness | Artefakte |
|---|---:|---|---|---:|
| `source_code` | ja | reachable | current | 85 |
| `tests` | ja | reachable | current | 45 |
| `documentation` | ja | reachable | current | 69 |
| `configuration` | ja | reachable | current | 6 |
| `structured_reports` | nein | reachable | current | 23 |
| `git_history` | nein | not_found | unknown | 0 |
| `github_metadata` | nein | disabled | not_applicable | 0 |

### 6.2 Vollständige erwartete Quellgruppen

`artifact_count` ist eine pfadbasierte Zuordnung. Indirekte Gruppen können sich
überschneiden und dürfen nicht zu einer Gesamtsumme addiert werden.

| Quellgruppe | expected | configured | required | reachable | artifact_count | freshness | limitation |
|---|---|---|---|---|---:|---|---|
| `repository_metadata` | yes | yes, Git-Adapter | no | partial | 0 | unknown | Nur nicht autoritativer Parent-Kontext; TIM selbst ist unversioned. |
| `source_code` | yes | yes, direkt | yes | yes | 84 | current | Enthält `main.py` und `src/**/*.py`; erzeugte und externe Pakete sind ausgeschlossen. |
| `tests` | yes | yes, direkt | yes | yes | 44 | current | Artefaktzahl zählt Testdateien, nicht Testfälle. |
| `schemas` | yes | yes, indirekt über `configuration` | not independently; parent `configuration` is required | yes | 4 | current, Aggregat | Keine eigene Source-Health-Zeile; eine leere Schema-Untergruppe würde nicht separat als fehlende Pflichtquelle gemeldet. |
| `configs` | yes | yes, indirekt über `configuration` | not independently; parent `configuration` is required | yes | 2 | current, Aggregat | Der Adapter scannt JSON/YAML/YML/TOML/SQL unter `config`/`schemas`; Python-Konfiguration wie `config/settings.py` fehlt. Eine leere Config-Untergruppe würde nicht separat gemeldet. |
| `prompts` | yes | indirekt über `source_code` | no | yes | 2 | current, Aggregat | Keine eigene Prompt-Quelle oder Prompt-Versionierung. |
| `documentation` | yes | yes, direkt | yes | yes | 69 | current | `docs/tim_manager/**` ist zur Vermeidung von Self-Ingest ausgeschlossen. |
| `architecture_decisions` | yes | **NOT CONFIGURED** | no | **NOT FOUND als eigene Gruppe** | 0 | not_applicable | Zwei allgemeine Architektur-Dokumente ersetzen kein ADR-Register. |
| `reports` | yes | indirekt über das heterogene Aggregat `structured_reports` | no | partial | 23 | current, Aggregat | Keine eigene Report-Klassifikation. Die 23 umfassen vier `artifacts/audits/*`, ein Provenienzartefakt und 18 Research-Artefakte; dies ist keine vollständige eigenständige Reports-Inventur und überschneidet `research`/`provenance`. |
| `research` | yes | indirekt über `structured_reports` | no | yes | 18 | current, Aggregat | Nur Dateien unter `data/research`; keine externe Research-Datenbank. |
| `experiments` | yes | **NOT CONFIGURED** | no | **NOT FOUND** | 0 | not_applicable | Snapshot-Feld existiert, aber kein Experiment-Adapter oder Inventar. |
| `evaluations` | yes | **NOT CONFIGURED** | no | **NOT FOUND als eigene Gruppe** | 0 | not_applicable | Evaluation-ähnliche Dokumente werden nicht als eigene Quelle geführt. |
| `backtests` | yes | **NOT CONFIGURED** | no | **NOT FOUND** | 0 | not_applicable | `backtests/results/**` ist geschützt, aber nicht als Read-Quelle konfiguriert. |
| `data_catalogs` | yes | **NOT CONFIGURED** | no | **NOT FOUND** | 0 | not_applicable | Kein Datenkatalog-Adapter oder Katalogartefakt. |
| `provenance` | yes | indirekt über `structured_reports` | no | yes | 1 | current, Aggregat | Ein TIM-V1-Provenienzartefakt; TIM-IM-Provenienzartefakte sind vom Self-Ingest ausgeschlossen. |
| `agent_outputs` | yes | indirekt, nicht typisiert | no | partial | 7 | current, Aggregat | Pfadbasierte Zählung von einem Module-A-Cache und sechs Module-B-Reportdateien; keine eigene Trust-/Health-Zeile. Überschneidet `research`. |
| `model_outputs` | yes | **NOT CONFIGURED** | no | **NOT FOUND** | 0 | not_applicable | Kein dedizierter Model-Output-Ingest; externe Modelle sind optional deaktiviert. |
| `git_history` | yes | yes | no | **NOT FOUND** | 0 | unknown | Parent-Git-Historie ist keine TIM-Historie und wird nicht als TIM-Evidenz ausgegeben. |
| `github_metadata` | yes | configured but disabled | no | disabled / not evaluated | 0 | not_applicable | Kein GitHub-Connector und keine Cloud-Metadaten aktiviert. |
| `rag_indexes` | yes | **NOT CONFIGURED** | no | **NOT FOUND als Eingabe** | 0 | not_applicable | Der eigene abgeleitete TIM-IM-SQLite-Index ist keine RAG-Quellgruppe. |
| `local_databases` | yes | **NOT CONFIGURED** | no | **NOT CONFIGURED / not tested** | 0 | not_applicable | Der abgeleitete TIM-IM-SQLite-Store ist ausgeschlossen; die externe TIM-Postgres-Datenbank wurde nicht als Quelle auditiert. |

## 7. MCP- und Manager-Integration

| Integrationsstufe | Nachgewiesener Zustand |
|---|---|
| Lokaler MCP-Server | validiert; stdio-Prozess Exit `0`, Initialisierung, Tool-Liste, alle sechs Tools, Ressourcenliste und Ressourcenlesen getestet |
| Lokale MCP-Tools | `tim_get_status`, `tim_get_module_status`, `tim_get_risks`, `tim_get_source_health`, `tim_search`, `tim_query` |
| Exponierte MCP-Mutationen | keine; `0` Mutationswerkzeuge, unbekannte Schreibmethode ergibt JSON-RPC `-32601` |
| MCP-Protected-Hash | vor/nach lokalem Protokolltest identisch: `413fef8c8794c618a805abb44a2d22ffa20834c88b5a983b3f03f54638da0d99` |
| Bestehender TIM-IM-SQLite-Index bei `tim_search` | Hash vor/nach identisch: `bee655df0f3bb89342c74436a4992653e659e13daeaa45c50bef1de0633392f2`; Größe und mtime ebenfalls identisch |
| Interne Dateisystemgrenze | `tim_search` verwendet eine normale SQLite-Verbindung und ist nicht explizit mit SQLite-Read-only-URI geöffnet; bei fehlendem Index ist eine Initialisierung innerhalb der TIM-IM-Allowlist möglich |
| Claude-/OpenCode-Konfiguration | Beispiel in `docs/tim_manager/mcp_integration.md` vorhanden |
| Tatsächliche Claude-/OpenCode-Clientverbindung | nicht konfiguriert und nicht getestet |
| ChatGPT-Workspace-Agent | Agent „TIM Manager“ existiert und ist veröffentlicht; Agent-ID `agt_6a6852df446c81919556552d9ade11d8`, veröffentlichte Version `agtv_6a68536271b08191a246dcb8c7402e3c` |
| ChatGPT-Agent-Datenanbindung | **nicht angebunden**: `connectors=[]`, `linked_connectors=[]`, `widget_tools=[]`, `skills=[]`, API-Kanäle `[]`, Slack `[]`; Draft- und Published-Dateibaum jeweils Revision `0` mit leerem Root |

Der reproduzierbare lokale Probe-Aufruf ist:

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python artifacts/tim_manager/reports/final_verification_probes.py mcp
```

Prüfskript-SHA-256:
`89f87e626d34565066c63f523cadea817ecc8b89c2f6f0cc1d754ceffc0f4815`.

Die Veröffentlichung eines Agenten und seine Chat-UI beweisen keine Verbindung
zu TIM-IM. Eine solche Verbindung wurde nicht behauptet.

## 8. Deprecation-Warnungen

Der vollständige Lauf erfolgte mit:

- Python `3.14.6`,
- pytest `8.4.2`,
- pytest-asyncio `0.26.0`.

Ergebnis: `145 warnings`. Die Warnungen stammen aus
`pytest_asyncio/plugin.py` und betreffen die veralteten APIs
`asyncio.get_event_loop_policy` und `asyncio.set_event_loop_policy`, deren
Entfernung für Python 3.16 angekündigt ist.

Risikobewertung:

- aktuell kein Testfehler,
- zukünftiges Kompatibilitätsrisiko bei Python 3.16,
- keine großflächige Dependency-Migration in dieser Abnahme durchgeführt.

## 9. Finale Verifikation

### 9.1 Befehle und Exit-Codes

| Prüfung | Ausgeführter Befehl | Exit-Code | Ergebnis |
|---|---|---:|---|
| gezielter S11- und Contradiction-Lauf | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q tests/tim_manager/test_mandatory_acceptance.py::test_s11_conflicting_sources_are_visible tests/tim_manager/test_contradictions.py` | 0 | 14 passed, 1 warning |
| 20er-Pflichtmatrix | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q tests/tim_manager/test_mandatory_acceptance.py --junitxml=artifacts/tim_manager/reports/mandatory_acceptance.junit.xml` | 0 | 20 passed, 0 XFAIL/Skips, 1 warning |
| vollständige TIM-IM-Tests | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q tests/tim_manager` | 0 | 58 passed, 1 warning |
| vollständige TIM-Tests | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q` | 0 | 237 passed, 145 warnings |
| Doctor, erster falscher Modulpfad | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m tim_manager.cli doctor` | 1 | `ModuleNotFoundError`; nicht als erfolgreiche Verifikation gewertet |
| Validate, erster falscher Modulpfad | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m tim_manager.cli validate` | 1 | `ModuleNotFoundError`; nicht als erfolgreiche Verifikation gewertet |
| Doctor, dokumentierter Modulpfad | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.tim_manager.cli doctor` | 0 | Status `PASS`; config, project root, storage parent, protected write check, snapshot und MCP wahr; externe Modelle optional deaktiviert |
| Validate, dokumentierter Modulpfad | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.tim_manager.cli validate` | 0 | identische Checkliste und identisches Ergebnis wie Doctor |
| Stabilisierungsscan | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.tim_manager.cli scan` | 0 | Scan `90e98a54-b75e-5d6c-9dbc-9eecc7e53692`; 234 unchanged, sonst 0 |
| unveränderter Folge-Scan 1 | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.tim_manager.cli scan` | 0 | Scan `c681f93f-ff81-5df9-a426-ec785b58f7d0`; 234 unchanged, sonst 0, Parserfehler 0 |
| unveränderter Folge-Scan 2 | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.tim_manager.cli scan` | 0 | Scan `148146d3-4ed2-5897-b1f7-f5b562adf70e`; 234 unchanged, sonst 0, Parserfehler 0 |
| Snapshot-Export | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.tim_manager.cli export --output artifacts/tim_manager/reports/final_acceptance_snapshot_export.json` | 0 | Export erzeugt |
| Formale Schema-Prüfung, Standard-venv | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -c 'import jsonschema'` | 1 | `ModuleNotFoundError: jsonschema`; dokumentierter Fehlversuch |
| Formale Schema-Prüfung, Research-venv | `PYTHONDONTWRITEBYTECODE=1 .venv-research/bin/python artifacts/tim_manager/reports/final_verification_probes.py schema` | 0 | 3 aktuelle Dateien formal gültig und bytegleich; historischer Schema-1.0-Snapshot weiterhin gültig; jsonschema 4.26.0 |
| Snapshot-Dateihash | `shasum -a 256 artifacts/tim_manager/snapshots/current.json artifacts/tim_manager/snapshots/43312fa2-a863-5f56-9765-0d7a224239be.json` | 0 | beide `73c6481e3f33ed0ccdc8514fa81bdaf481d104f1bf0b2002da211592b82ebb7d` |
| Export-Dateihash | `shasum -a 256 artifacts/tim_manager/snapshots/current.json artifacts/tim_manager/reports/final_acceptance_snapshot_export.json` | 0 | beide `73c6481e3f33ed0ccdc8514fa81bdaf481d104f1bf0b2002da211592b82ebb7d` |
| Git-/SQLite-Provenienz und Manifest-Reproduktion | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python artifacts/tim_manager/reports/final_verification_probes.py provenance` | 0 | 228 Artefakte; 0 autoritative/non-null TIM-Commits; 228 Parent-Kontexte; `content_manifest_hash` exakt reproduziert |
| Protected-Baseline und Policy | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python artifacts/tim_manager/reports/final_verification_probes.py protected` | 0 | 44 identisch, 4 verändert, 0 fehlend; 5/5 Schreibpfade verweigert |
| Verbotener CLI-Export | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.tim_manager.cli export --output data/tim_manager_forbidden_probe.json` | 2 | Schutzfehler; Datei nicht angelegt |
| Ungültiger CLI-Befehl | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.tim_manager.cli does-not-exist` | 2 | aussagekräftiger argparse-Fehler |
| MCP API-/Protected-Grenze und eigener Index | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python artifacts/tim_manager/reports/final_verification_probes.py mcp` | 0 | 11 Antworten, sechs Read-only-Tools, 0 exponierte Mutationswerkzeuge; Protected-Hash sowie Hash/Größe/mtime des bestehenden Index vor/nach identisch |
| Probe-Skript-Hash | `shasum -a 256 artifacts/tim_manager/reports/final_verification_probes.py` | 0 | `89f87e626d34565066c63f523cadea817ecc8b89c2f6f0cc1d754ceffc0f4815` |
| Persistierter Probe-stdout | `shasum -a 256 artifacts/tim_manager/reports/final_verification_probe_results.md` | 0 | `ec58de43f15372d8fdf9f9273b1144caffb3d4d133f4a96cbe18186d991acd0c` |

### 9.2 Zwei unveränderte Folge-Scans

Beide Folge-Scans erzeugten dieselbe Snapshot-ID:
`43312fa2-a863-5f56-9765-0d7a224239be`.

| Scan-ID | new | changed | deleted | moved | unchanged | parser_errors |
|---|---:|---:|---:|---:|---:|---:|
| `c681f93f-ff81-5df9-a426-ec785b58f7d0` | 0 | 0 | 0 | 0 | 234 | 0 |
| `148146d3-4ed2-5897-b1f7-f5b562adf70e` | 0 | 0 | 0 | 0 | 234 | 0 |

Die Snapshot-Datei, ihre versionierte Kopie und der Export sind bytegleich.

`234 unchanged` sind Quellenbeobachtungen, nicht 234 eindeutige
Artefakt-Datensätze. Sechs Markdown-Pfade werden sowohl von
`documentation` als auch von `structured_reports` besucht; der Snapshot
dedupliziert pfadbasiert auf 228 eindeutige Artefakte.

## 10. Verbleibende nicht blockierende Grenzen

Nicht im Rahmen der lokalen TIM-IM-Abnahme umgesetzt:

1. Vollständige Alt-/Neu-Pfad-Provenienz der Move-Erkennung ohne zusätzlichen
   missverständlichen Delete-Tombstone.
2. Expliziter SQLite-Read-only-Modus für MCP-Suchzugriffe, wenn vollständige
   Dateisystem-Read-only-Semantik gefordert ist.
3. Separate, explizite Quellenadapter oder Registrierungen für die als
   `NOT CONFIGURED` ausgewiesenen Quellgruppen.
4. Technische Anbindung des veröffentlichten Workspace-Agenten an den lokalen
   TIM-IM-MCP-Server oder an TIM-IM-Dateien.
5. Geplante Aktualisierung der asyncio-Testabhängigkeiten vor Python 3.16.
6. Initialisierung eines eigenständigen TIM-Git-Repositories.

Diese Punkte wurden dokumentiert, aber in diesem Auftrag weder als neue
Funktion noch als Dependency- oder Repository-Migration umgesetzt.
