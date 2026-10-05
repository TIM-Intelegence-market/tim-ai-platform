# Testrepository für die Negativversuche der Rulesets

**Die 13 Negativversuche laufen zuerst hier und nie zuerst auf `platform-main`.** Ein Versuch, der mit einem Fehler im Ruleset gelingt,
landet im Testrepository und nicht im Produktionsrepository. Aufbau (alles Handarbeit des Inhabers, nichts davon hat Claude getan):

1. Ein **privates** Repository anlegen, zum Beispiel `tim-ai-platform-rulesets-test`, mit dem Standard-Branch `platform-main` und
   einem ersten Commit. Dieselbe Organisation (`TIM-Intelegence-market`) und derselbe Plan wie das Produktionsrepository, sonst sind die Rulesets nicht vergleichbar.
2. Beide Apps (Worker und Merger) auf dieses Repository installieren, mit **denselben** Rechten wie im Produktionsrepository.
3. Die drei Dateien aus [`github-workflows/`](github-workflows/) nach `.github/workflows/` des Testrepositories kopieren. Sie erzeugen genau die
   drei Pflicht-Kontexte (`test`, `TIM full suite`, `pr-gate/head`) von `github-actions`; je eine Datei im PR lässt einen davon rot werden:
   `PROBE_RED_TEST`, `PROBE_RED_FULL`, `PROBE_GATE_FAIL`.
4. Beide Rulesets aus [`docs/rulesets/`](..) importieren (`actor_id` der Merger-App eintragen). Name, Regeln, Parameter und Bypass-Akteure
   müssen **identisch** sein; nur das Repository unterscheidet sich.
5. **Gleichheitsbeleg:** Aus beiden Repositories beide Rulesets normalisiert ausgeben und vergleichen; der Unterschied muss leer sein:

   ```bash
   for repo in OWNER/tim-ai-platform OWNER/tim-ai-platform-rulesets-test; do
     for id in $(gh api repos/$repo/rulesets --jq '.[].id'); do
       gh api repos/$repo/rulesets/$id | jq -S 'del(.id,.node_id,.source,.source_type,._links,.created_at,.updated_at,.current_user_can_bypass)'
     done > /tmp/$(basename $repo).json
   done
   diff /tmp/tim-ai-platform.json /tmp/tim-ai-platform-rulesets-test.json && echo identical
   ```
6. Die Versuche 1 bis 13 aus [`AUTO_MERGE_RULESET.md`](../../AUTO_MERGE_RULESET.md) (Abschnitt 4) im Testrepository ausführen und dort
   eintragen. Für den Versuch mit rotem Check: PR mit der Datei `PROBE_RED_FULL` öffnen, warten bis `TIM full suite` rot ist, dann mit dem
   Merger-Token `gh api -X PUT repos/OWNER/tim-ai-platform-rulesets-test/pulls/<N>/merge -f sha=<head> -f merge_method=squash`; erwartet
   ist eine Ablehnung (HTTP 405 oder 403). Für „Status fehlt“: PR öffnen, solange der Workflow `PR gate` im Testrepository deaktiviert ist.
7. Erst wenn alle Versuche im Testrepository wie erwartet scheitern **und** der Gleichheitsbeleg leer ist, folgen im Produktionsrepository nur noch
   die **lesenden** Prüfungen (Versuche 9 und 10); dort wird kein roter, fehlender oder veralteter PR gemergt.

Die Gate-Fixture liest Commit und Root-Tree als Metadaten. Nur ein erfolgreich gelesener, gültiger Tree ohne
`PROBE_GATE_FAIL` erzeugt `success`; API-Fehler oder ungültige Antworten erzeugen `failure`. PR-Code wird nicht ausgeführt.
