# Wissen für Agenten: ein Markdown-Bestand für Codex und Claude

Beide Werkzeuge lesen dieselben Markdown-Dateien im Repo. Es gibt keine zweite Kopie.

| Werkzeug | Einstiegsdatei | Was sie tut |
|---|---|---|
| Codex | `AGENTS.md` | Liest die Datei selbst und folgt den Verweisen. |
| Claude Code | `CLAUDE.md` | Bindet `AGENTS.md` per `@AGENTS.md` ein und ergänzt Claude-spezifische Regeln. |

Regel: Gemeinsames Wissen steht in `AGENTS.md` oder unter `docs/`. In `CLAUDE.md`
steht nur, was nur für Claude gilt (Skills, Subagenten, Modellwahl). So laufen die
beiden Einstiege nicht auseinander.

## Lesereihenfolge vor größerer Arbeit

1. `AGENTS.md` und `CLAUDE.md` (Arbeitsregeln, GitHub-Arbeit).
2. `CI.md` (Worker-PRs, gesperrte Pfade, Merge-Kriterien).
3. `docs/SYSTEMSTAND.md` (aktueller Stand, mit Datum lesen, kein Betriebsnachweis).
4. `docs/TIM_GESAMTPLAN.md` und `docs/TIM_LINUX_QUBE_PLAN.md` (Ziele, Missionen, Gates).
5. Zum Thema: unten im Themenindex.

## Themenindex

| Thema | Datei |
|---|---|
| Issues und Pipeline | `docs/ISSUE_WORKFLOW.md`, `docs/GITHUB_ISSUE_PIPELINE.md` |
| Subagenten und Master-Auftrag | `docs/SUBAGENTEN_PLAN.md`, `docs/SUBAGENTEN_MASTER_AUFTRAG.md`, `.claude/agents/` |
| Multi-Agenten-System | `docs/MULTI_AGENTEN_SYSTEM.md` |
| Kontext vor dem Coden (Graph, Serena) | `docs/tooling/agent-context-preflight.md`, `docs/tooling/tool-router.md`, `docs/tooling/serena.md` |
| Forschung und Studien | `docs/research_lab/` (Register, Logbuch, Protokolle) |
| Datenqualität | `docs/DATA_QUALITY.md` |
| Projektchat-Wissen | `docs/TIM_CHAT_KNOWLEDGE_INDEX.md` |
| Gemeinsame KI-Ressourcen, Playbooks | `ai-resources/KI-Ressourcen.md` |

## Obsidian-Vault

Der Vault liegt nur auf dem Mac (`~/Documents/TIM/TIM OBSIDIAN`) und ist nicht im Repo.
Schema und Ordner: `docs/obsidian/VAULT_SCHEMA.md`. Der Vault ist die menschenlesbare,
geprüfte Wissensschicht; das Repo bleibt die Quelle für versionierten Text und Code.

- Lesen: Notizen sind normales Markdown mit Frontmatter (`type`, `status`, `updated`).
  Für Agenten reicht der Graph-Zugriff (`docs/tooling/agent-context-preflight.md`);
  keinen Vault-Komplettauszug in den Kontext laden.
- Schreiben: nur Entwürfe nach `00 Inbox` mit `review: pending`. Übernahme in die
  Ordner macht der Mensch.
- Verschieben, Löschen und Umbenennen im Vault nur nach ausdrücklicher Freigabe.

## Grenzen

- Datierte Aussagen bleiben datiert. Alte Stände sind keine aktuellen Betriebsnachweise.
- Keine Zugangsdaten, Tokens oder Schlüsselpfade in Markdown, auch nicht in Beispielen.
- Neue Wissensdatei: unter `docs/` ablegen und hier im Themenindex eintragen,
  sonst findet sie keiner der beiden Agenten.
