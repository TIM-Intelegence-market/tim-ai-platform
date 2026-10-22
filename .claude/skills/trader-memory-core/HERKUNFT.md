# Herkunft

* **Quelle:** `tradermonty/claude-trading-skills` (TraderMonty), Pfad `skills/trader-memory-core`,
  Commit `cb0f3aadffed6d1089db4b224162c964368baa46` vom 19.10.2026.
* **Abgerufen:** 22.10.2026 per `git clone` von github.com.
* **Lizenz:** MIT, Copyright (c) 2026 TraderMonty. Lizenztext liegt unverändert als `LICENSE` bei.
* **Übernommen:** alle Dateien des Skill-Ordners unverändert (SKILL.md, references, scripts, Tests).
  Pfade in `SKILL.md` lauten `skills/trader-memory-core/...`; in diesem Repo liegt der Skill unter `.claude/skills/trader-memory-core/`.
* **Zweck:** Thesen-Journal über den ganzen Lebenszyklus (Idee, aktiv, geschlossen, Postmortem) als lokale YAML-Dateien.
* **Ein-/Ausgabe:** Kern läuft offline (`jsonschema`). Optional `fmp_price_adapter.py` mit `FMP_API_KEY` (US-Aktiendaten, für TIM nicht nötig, nicht einrichten). `trader_memory_cli.py` erwartet das Upstream-Layout `skills/...` und ruft `uv` auf; in TIM stattdessen `thesis_store.py`/`thesis_review.py` direkt aufrufen.
* **Geprüft (22.10.2026):** Code statisch durchsucht (Netzwerk, Unterprozesse, Löschen, Umgebungsvariablen,
  Order-/Broker-Aufrufe). Keine Order-Ausführung, kein Broker-Zugriff, keine Hooks, keine MCP-Server.
  Mitgelieferte Tests am 22.10.2026 auf Uzis Wunsch in der Cloud ausgeführt (eigenes venv, Python 3.13): 411 bestanden.
  Sie liegen unter `scripts/tests/` und werden von der TIM-Suite (`pytest tests/`) nicht eingesammelt.
* **TIM-Hinweis:** Zustand liegt standardmäßig unter `state/theses/` relativ zum Arbeitsordner; im Repo per `.gitignore` ausgeschlossen.
* **Grenzen für TIM:** nur Analyse, Papier und Journal. Kein Echtgeld, keine Anbindung an Order-Pfade,
  keine Zugangsdaten im Repo. Nicht in `~/TIM-live` einspielen, solange die V2-Kampagne läuft (bis 23.11.2026).
