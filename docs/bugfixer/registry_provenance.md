# Remediation-Registry: Versionshistorie und Herkunft (#16)

Das Registry-Schema (`schemas/bugfixer/remediations.v2.json`) bleibt unverändert. Zwei Begleitdateien in
`src/repair_registry/` binden jedes ausgelieferte Rezept (`ID@Version`) an seine Prüfsumme:

- `registry_history.v1.json`: jede je ausgelieferte Version mit Prüfsumme, in Auslieferungsreihenfolge.
  Ein Rezept darf sich ohne Versionssprung nicht ändern, eine neue Version wird angehängt und muss höher sein.
- `provenance.v1.json`: Herkunfts-Commit, Änderungen, Evidenzstatus (`REPRODUCED`, `CANDIDATE_EVIDENCE`,
  `UNVERIFIED_ORIGIN`) und Belege. Wer Evidenz behauptet, muss eine vorhandene Datei nennen.

`tests/test_repair_registry_provenance.py` prüft beides bei jedem CI-Lauf. Damit ist die Upgrade-Prüfung in
einen Pflichtpfad eingebunden und nicht mehr nur ein CLI-Befehl.

Stand 25.10.2026:

| Rezept | Autonomie | Evidenz | Hinweis |
|---|---|---|---|
| `NETWORK_TIMEOUT@2.0.0` | A1 | `CANDIDATE_EVIDENCE` | Ursache stark belegt (Kandidat C1); begrenzter Reconnect unter der Gate-Engine noch nicht bewiesen (#19) |
| `LAUNCHD_LOG_PATH@2.0.0` | A2 | `CANDIDATE_EVIDENCE` | Herkunft geklärt (25.10.): macOS-Problem `launchd → StandardErrorPath → com.apple.macl/Logrotation → EX_CONFIG 78`, im Chat berichtet und in `docs/TIM_LINUX_QUBE_PLAN.md` als ungeprüfter Chat-Befund festgehalten. Gegenmaßnahme seit `58bd3de` (3.9.): `scripts/tim_log_maintenance.py` rotiert die launchd-Logs mit `preserve_inode=True` (`src/operational/logging.py`, Test nur für den Mechanismus). Das Rezept selbst kam mit dem Live-Snapshot `29aafdb`. Kein Log-Auszug eines echten EX_CONFIG-78-Vorfalls, keine Reproduktion, daher nicht `REPRODUCED`. Einzige Aktion bleibt eine Prüfung (`review_log_path_permissions`); für `REPRODUCED` fehlt ein echter launchd-Logauszug mit Exit 78. |
