# Herkunft

* **Quelle:** `tradermonty/claude-trading-skills` (TraderMonty), Pfad `skills/crypto-regime-analyzer`,
  Commit `cb0f3aadffed6d1089db4b224162c964368baa46` vom 19.10.2026.
* **Abgerufen:** 22.10.2026 per `git clone` von github.com.
* **Lizenz:** MIT, Copyright (c) 2026 TraderMonty. Lizenztext liegt unverändert als `LICENSE` bei.
* **Übernommen:** alle Dateien des Skill-Ordners unverändert (SKILL.md, references, scripts, Tests).
  Pfade in `SKILL.md` lauten `skills/crypto-regime-analyzer/...`; in diesem Repo liegt der Skill unter `.claude/skills/crypto-regime-analyzer/`.
* **Zweck:** Krypto-Regime 0-100 aus sechs Komponenten (BTC-Trend, Dominanz, Alt-Breite, Funding, Drawdown/Vol, Momentum).
* **Ein-/Ausgabe:** Liest öffentlich und ohne Schlüssel `api.coingecko.com` und `fapi.binance.com` (nur Funding-Raten, lesend). In der Cloud ist Binance gesperrt, auf dem Mac erreichbar. Alternativ Offline-Modus mit eigener Snapshot-JSON (nur Standardbibliothek). Live-Modus braucht `requests`.
* **Geprüft (22.10.2026):** Code statisch durchsucht (Netzwerk, Unterprozesse, Löschen, Umgebungsvariablen,
  Order-/Broker-Aufrufe). Keine Order-Ausführung, kein Broker-Zugriff, keine Hooks, keine MCP-Server.
  Mitgelieferte Tests am 22.10.2026 auf Uzis Wunsch in der Cloud ausgeführt (eigenes venv, Python 3.13): 84 bestanden.
  Sie liegen unter `scripts/tests/` und werden von der TIM-Suite (`pytest tests/`) nicht eingesammelt.
* **TIM-Hinweis:** Ergebnis ist ein Lagebild, kein Richtungssignal. Nicht als Handelssignal für TIM verdrahten.
* **Grenzen für TIM:** nur Analyse, Papier und Journal. Kein Echtgeld, keine Anbindung an Order-Pfade,
  keine Zugangsdaten im Repo. Nicht in `~/TIM-live` einspielen, solange die V2-Kampagne läuft (bis 23.11.2026).
