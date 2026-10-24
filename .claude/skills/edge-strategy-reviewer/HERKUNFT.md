# Herkunft

* **Quelle:** `tradermonty/claude-trading-skills` (TraderMonty), Pfad `skills/edge-strategy-reviewer`,
  Commit `cb0f3aadffed6d1089db4b224162c964368baa46` vom 19.10.2026.
* **Abgerufen:** 22.10.2026 per `git clone` von github.com.
* **Lizenz:** MIT, Copyright (c) 2026 TraderMonty. Lizenztext liegt unverändert als `LICENSE` bei.
* **Übernommen:** alle Dateien des Skill-Ordners unverändert (SKILL.md, references, scripts, Tests).
  Pfade in `SKILL.md` lauten `skills/edge-strategy-reviewer/...`; in diesem Repo liegt der Skill unter `.claude/skills/edge-strategy-reviewer/`.
* **Zweck:** Kritische Prüfung von Strategie-Entwürfen auf Plausibilität des Edge, Overfitting, Stichprobe und Ausführbarkeit.
* **Ein-/Ausgabe:** Lokale Rechnung, Eingabe YAML/JSON. Braucht `PyYAML`.
* **Geprüft (22.10.2026):** Code statisch durchsucht (Netzwerk, Unterprozesse, Löschen, Umgebungsvariablen,
  Order-/Broker-Aufrufe). Keine Order-Ausführung, kein Broker-Zugriff, keine Hooks, keine MCP-Server.
  Mitgelieferte Tests am 22.10.2026 auf Uzis Wunsch in der Cloud ausgeführt (eigenes venv, Python 3.13): 56 bestanden, 1 fehlgeschlagen: der Test vergleicht `assets/bias_checklist.yaml` mit der Upstream-Doku `docs/dev/strategy-research-bias-checklist.md`, die nicht mit übernommen wurde. Die Prüflogik selbst ist nicht betroffen.
  Sie liegen unter `scripts/tests/` und werden von der TIM-Suite (`pytest tests/`) nicht eingesammelt.
* **TIM-Hinweis:** Erwartet Entwürfe im Format von `edge-strategy-designer` (nicht übernommen); eigene Entwürfe vorher in dieses Format bringen oder nur den Leitfaden nutzen.
* **Grenzen für TIM:** nur Analyse, Papier und Journal. Kein Echtgeld, keine Anbindung an Order-Pfade,
  keine Zugangsdaten im Repo. Nicht in `~/TIM-live` einspielen, solange die V2-Kampagne läuft (bis 23.11.2026).
