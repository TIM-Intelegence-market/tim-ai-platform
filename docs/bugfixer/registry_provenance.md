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
| `LAUNCHD_LOG_PATH@2.0.0` | A2 | `UNVERIFIED_ORIGIN` | kam mit dem Live-Snapshot `29aafdb`; kein passender Kandidat im P8-Register. Einzige Aktion ist eine Prüfung (`review_log_path_permissions`). Vor einer echten A2-Freigabe Herkunft klären oder auf A0 setzen. |
