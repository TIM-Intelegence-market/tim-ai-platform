# Herkunft: Claude Crew (Explore auf Haiku)

- Quelle: Notion-Seite "The Claude Crew setup" von @harshithsai.batthini
  (repeated-meat-575.notion.site, abgerufen am 23.10.2026 auf dem Mac, da aus der Cloud gesperrt).
- Übernommen: `explore.md` wörtlich aus Schritt 2 der Seite. Die Datei ersetzt in TIM-Sitzungen
  den eingebauten Such-Helfer `Explore` durch eine Fassung auf Haiku, nur mit Read, Grep, Glob.
- Idee der Seite: Opus plant, Sonnet baut, Haiku sucht. Schritt 1 (`"model": "opusplan"`) gehört in
  die Benutzer-Einstellungen (`~/.claude/settings.json`), nicht ins Repo, damit Cloud-Sitzungen
  ihr eigenes Modell behalten. Auf Uzis Mac am 23.10.2026 eingerichtet (Sicherung der alten
  Datei: `~/.claude/backups/settings.json.vor-claude-crew-20261023`).
- Grenzen: nur lesend, kein Bash, kein Schreiben. Für Prüfungen, die Befehle brauchen, den
  Hauptagenten oder `general-purpose` nehmen.
- Prüfen: nach einer Sitzung `/usage` aufrufen, dort steht der Verbrauch je Modell.
