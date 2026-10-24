# Herkunft

* **Quelle:** Anthropic, `anthropics/claude-plugins-official`, Plugin `claude-code-setup` v1.0.0
  (Autorin laut README: Isabella He). Pfad: `plugins/claude-code-setup/skills/claude-automation-recommender`.
* **Abgerufen:** 17.10.2026 über raw.githubusercontent.com, Branch `main` (Commit nicht festgehalten).
* **Übernommen:** `SKILL.md` und `references/*.md` unverändert. Als Repo-Skill kopiert, nicht als Plugin installiert.
* **Geprüft (17.10.2026):** alle sechs Dateien gelesen bzw. per grep auf Netzwerk-, Lösch- und Geheimnis-Muster
  durchsucht. Keine ausführbaren Skripte, keine Hooks, keine eigenen MCP-Server. Treffer nur in Beispieltext.
* **Rechte:** `tools: Read, Glob, Grep, Bash`. Der Skill ist laut Text read-only und ändert keine Dateien.
* **Lizenz:** nicht geprüft.
* **Grenze:** Empfehlungen sind Vorschläge. Nichts davon (MCP-Server, Hooks, Berechtigungen) wird ohne
  ausdrückliche Freigabe umgesetzt (siehe `CLAUDE.md`).
