# Herkunft

* **Quelle:** `tradermonty/claude-trading-skills` (TraderMonty), Pfad `skills/signal-postmortem`,
  Commit `cb0f3aadffed6d1089db4b224162c964368baa46` vom 19.10.2026.
* **Abgerufen:** 22.10.2026 per `git clone` von github.com.
* **Lizenz:** MIT, Copyright (c) 2026 TraderMonty. Lizenztext liegt unverändert als `LICENSE` bei.
* **Übernommen:** alle Dateien des Skill-Ordners unverändert (SKILL.md, references, scripts, Tests).
  Pfade in `SKILL.md` lauten `skills/signal-postmortem/...`; in diesem Repo liegt der Skill unter `.claude/skills/signal-postmortem/`.
* **Zweck:** Ergebnisse von Signalen nach dem Trade festhalten und auswerten (Treffer, Fehlsignal, verpasste Chance, Regime-Fehlgriff) gegen 5- und 20-Tage-Renditen.
* **Ein-/Ausgabe:** Manuelle Preiseingabe geht offline. Optional FMP mit `FMP_API_KEY` (US-Aktien, für TIM nicht nötig). Braucht `requests`.
* **Geprüft (22.10.2026):** Code statisch durchsucht (Netzwerk, Unterprozesse, Löschen, Umgebungsvariablen,
  Order-/Broker-Aufrufe). Keine Order-Ausführung, kein Broker-Zugriff, keine Hooks, keine MCP-Server.
  Die mitgelieferten Tests wurden **nicht** ausgeführt (Ausführen fremden Codes war in der Cloud-Sitzung gesperrt).
  Sie liegen unter `scripts/tests/` und werden von der TIM-Suite (`pytest tests/`) nicht eingesammelt.
* **TIM-Hinweis:** Passt zu Arena- und Research-Lab-Auswertungen.
* **Grenzen für TIM:** nur Analyse, Papier und Journal. Kein Echtgeld, keine Anbindung an Order-Pfade,
  keine Zugangsdaten im Repo. Nicht in `~/TIM-live` einspielen, solange die V2-Kampagne läuft (bis 23.11.2026).
