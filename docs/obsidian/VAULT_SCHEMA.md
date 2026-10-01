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

## Werkzeuge

Ein Pfad für alle Werkzeuge: `TIM_OBSIDIAN_VAULT` (Altname `TIM_GRAPH_MCP_VAULT`
wird weiter gelesen). Health-Check nutzt sonst `~/Documents/TIM/TIM OBSIDIAN`.

```bash
python -m src.obsidian_vault.lint                    # Schema, Links, Alter prüfen (Exit 1 bei Fehlern)
python -m src.obsidian_vault.migrate plan  --source OLD --markdown
python -m src.obsidian_vault.migrate apply --source OLD --target NEU   # Ziel leer, Quelle bleibt unberührt
python -m src.obsidian_vault.draft_writer decision --title "…" --source https://…   # nur nach 00 Inbox
```

Regel: Agenten schreiben nur über `draft_writer` in `00 Inbox`, nie überschreibend.
In den geprüften Bereich verschiebt Uzi die Notiz in Obsidian.
