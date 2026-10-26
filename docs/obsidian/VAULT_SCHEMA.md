# TIM Obsidian-Vault: Schema und Werkzeuge

Der Vault (`~/Documents/TIM/TIM OBSIDIAN`) ist die menschenlesbare, geprüfte
Wissensschicht von TIM. Obsidian bleibt kostenlos: kein Sync-Abo, keine
Community-Plugins; gesichert wird mit Git im Vault.

Maschinenlesbares Schema: `schemas/obsidian/vault_schema.json` (Version 1.0.0).

## Ordner unter `TIM/`

| Ordner | erlaubte `type` |
|---|---|
| 00 Inbox | alle; nur Entwürfe mit `review: pending` |
| 01 Home | home, moc |
| 10 Architektur | architecture, moc |
| 20 Incidents | incident, moc |
| 30 Missionen | mission, gate, moc |
| 40 Systeme | system, moc |
| 50 Daten & QA | data-qa, gate, moc |
| 60 Agenten & Tools | tool, moc |
| 70 Entscheidungen | decision, moc |
| 75 Research | research, moc |
| 80 Runbooks | runbook, moc |
| 90 Berichte | report, daily, moc (Tagesnotizen in `90 Berichte/Daily`) |
| 95 Archiv | alle, nur `status: archived` |
| 99 Vorlagen | Vorlagen; werden nicht indexiert und nur auf `type` geprüft |

## Pflichtfelder und Status

Pflicht: `type`, `status`, `updated` (JJJJ-MM-TT).
`status` ist genau einer von: `planned`, `active`, `blocked`, `done`, `archived`.
Entscheidungen, Research und Incidents tragen `source:` mit Link auf PR oder Beleg.

Optional `code:` (Liste) verbindet eine Notiz mit dem Repository, z. B. in System-Notizen:

```yaml
code:
  - src/data_ingestion/aggregator.py   # Datei
  - src/data_ingestion                 # Paket = Service
  - service:research_lab               # Service direkt
```

Der Graph legt nur Verbindungen zu Pfaden an, die im Repository existieren
(`<Datei/Service> DOCUMENTED_BY <Notiz>`); unbekannte Einträge zählt er als
`CODE_LINKS_UNRESOLVED`. Wikilinks zwischen typisierten Notizen werden zu
Beziehungen: Mission ↔ Gate als `REQUIRES` (Mission braucht Gate), sonst
`REFERENCES`. Dadurch liefern `graph_mission_context` und `graph_gate_context`
Gates, Incidents und Missionen.

## Werkzeuge

Ein Pfad für alle Werkzeuge: `TIM_OBSIDIAN_VAULT` (Altname `TIM_GRAPH_MCP_VAULT`
wird weiter gelesen). Health-Check nutzt sonst `~/Documents/TIM/TIM OBSIDIAN`.

```bash
python -m src.obsidian_vault.lint                    # Schema, Links, Alter prüfen (Exit 1 bei Fehlern)
python -m src.obsidian_vault.migrate plan  --source OLD --markdown
python -m src.obsidian_vault.migrate apply --source OLD --target NEU   # Ziel leer, Quelle bleibt unberührt
python -m src.obsidian_vault.draft_writer decision --title "…" --source https://…   # nur nach 00 Inbox
gh pr list --state merged --limit 50 --json number,title,url,mergedAt \
  | python -m src.obsidian_vault.pr_drafts --prs-json - --since 2026-10-01   # gemergte PRs als Entwürfe
```

Regel: Agenten schreiben nur über `draft_writer` in `00 Inbox`, nie überschreibend.
In den geprüften Bereich verschiebt Uzi die Notiz in Obsidian.
`pr_drafts` überspringt jeden PR, dessen URL schon irgendwo im Vault steht (auch im
Master-Entwurf), und schreibt keinen Entwurf doppelt.

## Automatisch aktuell (Mac)

launchd `com.tim.obsidian-refresh` (`ops/launchd/com.tim.obsidian-refresh.plist`)
läuft stündlich `python -m src.obsidian_vault.auto_refresh --repo ~/Documents/TIM/tim-graph`:

1. Klon `tim-graph` per fast-forward auf `origin/platform-main`. Lokale Änderungen an
   versionierten Dateien bleiben stehen, der Lauf meldet dann `pull: local_changes`.
2. Vault: je Kalenderwoche eine Notiz `PRs JJJJ-Www` (gemergte PRs mit Link und
   Wikilinks zu den berührten System-Notizen) und die Übersicht `TIM Stand automatisch`,
   alle in `TIM/90 Berichte/Automatisch/` mit Tag `automatisch`. Eine Datei dort ohne
   diesen Tag wird nie überschrieben. Ausnahme von der Inbox-Regel, weil die Notizen
   nur Fakten aus Git wiedergeben und keine Freigabe brauchen.
3. Graph-MCP-Datenbank: `refresh-all`, wenn platform-main sich bewegt hat, sonst nur
   `refresh-docs`.
4. Graphify-Ansicht: `graphify update`, Kopie von `graph.html` nach
   `~/Documents/TIM/TIM Graph Ansicht/` (nur bei neuem Stand).
5. Graph-Knoten: `graph_hubs sync` hängt neue Notizen an ihren Bereichs-Knoten (siehe unten).
6. Vault-Git: committet nur den Ordner `Automatisch` und die dabei geänderten
   Knoten-Notizen, andere Änderungen bleiben offen.

Status: `~/Library/Application Support/TIM/obsidian-refresh/status.json`.
Löst den alten Job `com.tim.graph-refresh` (täglich nur `refresh-docs`) ab.

## Ein TIM-Graph (Knoten-Struktur)

Der Obsidian-Graph ist ein zusammenhängender Baum mit Querverbindungen:
`TIM Home` → ein Knoten (MOC) je Bereich → alle Notizen des Bereichs.

| Ordner | Knoten | Farbe |
|---|---|---|
| 01 Home | TIM Home | weiß |
| 10 Architektur | Architecture MOC | hellblau |
| 20 Incidents | Incidents MOC | rot |
| 30 Missionen | Missions MOC | orange |
| 40 Systeme | Systems MOC | blau |
| 50 Daten & QA | Data QA MOC | grün |
| 60 Agenten & Tools | Agents & Tools MOC | lila |
| 70 Entscheidungen | Decisions MOC | pink |
| 75 Research | Research MOC | gelb |
| 80 Runbooks | Runbooks MOC | türkis |
| 90 Berichte | Reports MOC | grau |
| 00 Inbox | (in TIM Home unter „Eingang“) | hellgrün |

`python -m src.obsidian_vault.graph_hubs sync` schreibt in jeden Knoten einen Block
zwischen `<!-- tim-graph:start -->` und `<!-- tim-graph:end -->` mit Links auf alle
Notizen des Ordners (Unterordner eingeschlossen; Wochen-PR-Notizen hängen an
`TIM Stand automatisch`). Fehlende Knoten legt er an. Text außerhalb der Markierungen
bleibt unberührt. `check` meldet unverbundene Notizen und veraltete Blöcke (Exit 1),
`settings` schreibt die Graph-Ansicht aus `docs/obsidian/graph.json`
(Filter ohne 95 Archiv/99 Vorlagen, ungelöste Links aus, Farbe je Bereich) nach
`.obsidian/graph.json` und behält den Zoom. Der stündliche Job ruft `sync` selbst auf.

## Dashboards

`docs/obsidian/dashboards/TIM Cockpit.base` gehört nach `TIM/01 Home/` im Vault
(Obsidian-Core-Plugin Bases, keine Community-Plugins). Ansichten: Missionen,
Gates, Blockiert, Incidents offen, Entscheidungen, Research, Eingang (prüfen),
Zuletzt geändert.
