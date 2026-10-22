# Herkunft

* **Quelle:** `tradermonty/claude-trading-skills` (TraderMonty), Pfad `skills/position-sizer`,
  Commit `cb0f3aadffed6d1089db4b224162c964368baa46` vom 19.10.2026.
* **Abgerufen:** 22.10.2026 per `git clone` von github.com.
* **Lizenz:** MIT, Copyright (c) 2026 TraderMonty. Lizenztext liegt unverändert als `LICENSE` bei.
* **Übernommen:** alle Dateien des Skill-Ordners unverändert (SKILL.md, references, scripts, Tests).
  Pfade in `SKILL.md` lauten `skills/position-sizer/...`; in diesem Repo liegt der Skill unter `.claude/skills/position-sizer/`.
* **Zweck:** Risikobasierte Positionsgröße (Fixed-Fractional, ATR, Kelly) aus Einstieg, Stop und Kontogröße.
* **Ein-/Ausgabe:** Reine Rechnung ohne Netzwerk und ohne Schlüssel.
* **Geprüft (22.10.2026):** Code statisch durchsucht (Netzwerk, Unterprozesse, Löschen, Umgebungsvariablen,
  Order-/Broker-Aufrufe). Keine Order-Ausführung, kein Broker-Zugriff, keine Hooks, keine MCP-Server.
  Mitgelieferte Tests am 22.10.2026 auf Uzis Wunsch in der Cloud ausgeführt (eigenes venv, Python 3.13): 42 bestanden.
  Sie liegen unter `scripts/tests/` und werden von der TIM-Suite (`pytest tests/`) nicht eingesammelt.
* **TIM-Hinweis:** Ursprünglich für Long-Aktien geschrieben; die Prozent-Risiko-Rechnung gilt auch für BTC-Spot. Standard sind ganze Stück; für BTC-Bruchteile `--fractional` nutzen.
* **Grenzen für TIM:** nur Analyse, Papier und Journal. Kein Echtgeld, keine Anbindung an Order-Pfade,
  keine Zugangsdaten im Repo. Nicht in `~/TIM-live` einspielen, solange die V2-Kampagne läuft (bis 23.11.2026).
