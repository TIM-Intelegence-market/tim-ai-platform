# Herkunft

* **Quelle:** `tradermonty/claude-trading-skills` (TraderMonty), Pfad `skills/backtest-expert`,
  Commit `cb0f3aadffed6d1089db4b224162c964368baa46` vom 19.10.2026.
* **Abgerufen:** 22.10.2026 per `git clone` von github.com.
* **Lizenz:** MIT, Copyright (c) 2026 TraderMonty. Lizenztext liegt unverändert als `LICENSE` bei.
* **Übernommen:** alle Dateien des Skill-Ordners unverändert (SKILL.md, references, scripts, Tests).
  Pfade in `SKILL.md` lauten `skills/backtest-expert/...`; in diesem Repo liegt der Skill unter `.claude/skills/backtest-expert/`.
* **Zweck:** Leitfaden und Bewertungsskript für systematische Backtests (Stichprobe, Overfitting, Kosten, Robustheit).
* **Ein-/Ausgabe:** Reine Rechnung auf Nutzereingaben.
* **Geprüft (22.10.2026):** Code statisch durchsucht (Netzwerk, Unterprozesse, Löschen, Umgebungsvariablen,
  Order-/Broker-Aufrufe). Keine Order-Ausführung, kein Broker-Zugriff, keine Hooks, keine MCP-Server.
  Die mitgelieferten Tests wurden **nicht** ausgeführt (Ausführen fremden Codes war in der Cloud-Sitzung gesperrt).
  Sie liegen unter `scripts/tests/` und werden von der TIM-Suite (`pytest tests/`) nicht eingesammelt.
* **TIM-Hinweis:** Ergänzt das Research Lab; ersetzt nicht dessen Guards (Holdout 2025 nur mit Uzis Wort).
* **Grenzen für TIM:** nur Analyse, Papier und Journal. Kein Echtgeld, keine Anbindung an Order-Pfade,
  keine Zugangsdaten im Repo. Nicht in `~/TIM-live` einspielen, solange die V2-Kampagne läuft (bis 23.11.2026).
