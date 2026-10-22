# Herkunft

* **Quelle:** `tradermonty/claude-trading-skills` (TraderMonty), Pfad `skills/trade-hypothesis-ideator`,
  Commit `cb0f3aadffed6d1089db4b224162c964368baa46` vom 19.10.2026.
* **Abgerufen:** 22.10.2026 per `git clone` von github.com.
* **Lizenz:** MIT, Copyright (c) 2026 TraderMonty. Lizenztext liegt unverändert als `LICENSE` bei.
* **Übernommen:** alle Dateien des Skill-Ordners unverändert (SKILL.md, references, scripts, Tests).
  Pfade in `SKILL.md` lauten `skills/trade-hypothesis-ideator/...`; in diesem Repo liegt der Skill unter `.claude/skills/trade-hypothesis-ideator/`.
* **Zweck:** Prüfbare Trade-Hypothesen aus Marktdaten, Trade-Logs und Journal, gerankt als Hypothesenkarten.
* **Ein-/Ausgabe:** Lokale JSON-Pipeline ohne Netzwerk. Braucht `PyYAML`.
* **Geprüft (22.10.2026):** Code statisch durchsucht (Netzwerk, Unterprozesse, Löschen, Umgebungsvariablen,
  Order-/Broker-Aufrufe). Keine Order-Ausführung, kein Broker-Zugriff, keine Hooks, keine MCP-Server.
  Die mitgelieferten Tests wurden **nicht** ausgeführt (Ausführen fremden Codes war in der Cloud-Sitzung gesperrt).
  Sie liegen unter `scripts/tests/` und werden von der TIM-Suite (`pytest tests/`) nicht eingesammelt.
* **TIM-Hinweis:** Hypothesen sind Ideen für das Research Lab, keine Signale.
* **Grenzen für TIM:** nur Analyse, Papier und Journal. Kein Echtgeld, keine Anbindung an Order-Pfade,
  keine Zugangsdaten im Repo. Nicht in `~/TIM-live` einspielen, solange die V2-Kampagne läuft (bis 23.11.2026).
