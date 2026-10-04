# Auto-Merge: GitHub-Schutzregeln als harte Voraussetzung

**Solange diese Regeln nicht angelegt und per Negativversuch geprüft sind, bleibt Auto-Merge aus.** Ein Code-Gate allein ist
keine technische Sperre für andere Schreibberechtigte: Wer Schreibrecht hat und keine Regel im Weg findet, kann selbst nach
`platform-main` pushen oder mergen. Der Controller liest deshalb vor jedem echten Merge **beide Rulesets unten samt ihrer
Bypass-Konfiguration** (`GET /repos/{repo}/rulesets`, `.../rulesets/{id}`, `.../rules/branches/platform-main`), prüft sie gegen die
Policy und bricht bei jeder Abweichung oder jedem Lesefehler ab. Dasselbe lesende Prüfen ohne Merge:
`python -m scripts.auto_merge_controller --repo OWNER/REPO --policy .github/auto-merge-policy.json --gate-policy .github/pr-gate-policy.json --verify-rulesets`.

## 1. Der HTTP-403-Block (am 2026-10-04 lesend verifiziert)

Drei reine `GET`-Abfragen mit dem Integrations-Token der Entwicklungssitzung. Es wurde kein Admin-Token verwendet und nichts
umgangen oder geändert.

| Abfrage | Antwort |
|---|---|
| `GET /repos/uezeyiraydin-cell/tim-ai-platform/rulesets` | HTTP 403: *„Upgrade to GitHub Pro or make this repository public to enable this feature.“* |
| `GET /repos/uezeyiraydin-cell/tim-ai-platform/rules/branches/platform-main` | HTTP 403, derselbe Text |
| `GET /repos/uezeyiraydin-cell/tim-ai-platform/branches/platform-main/protection` | HTTP 403: *„Resource not accessible by integration“* (fehlende Token-Rechte; **kein** Planhinweis, sagt über den Plan nichts) |

Gelesene Repository-Daten: `private: true`, `owner.type: User` (persönliches Konto), `default_branch: platform-main`,
`allow_auto_merge: false`. **Folgerung:** Rulesets sind für dieses private Repository auf dem aktuellen Plan nicht verfügbar. GitHub
nennt als Ausweg ausdrücklich *GitHub Pro* oder ein *öffentliches* Repository. Dass das Konto derzeit GitHub Free hat, folgt aus
diesem Text, ist aber nicht direkt gelesen (der Plan des Kontos ist über dieses Token nicht lesbar). Preis und Umfang von GitHub
Pro habe ich nicht verifiziert.

**Entscheidung des Inhabers (offen):**

| Weg | Bewertung |
|---|---|
| Privat mit GitHub Pro | empfohlen: schaltet Rulesets, Pflicht-Checks und Bypass-Listen frei |
| Öffentlich | nicht empfohlen: Betriebs- und Governance-Dokumente eines Trading-Systems würden öffentlich |
| Weiter bei Draft-PRs, Merge von Hand | sicherer Zustand bis zur Entscheidung; so sind #146, #147, #149 und #150 heute |

## 2. Exakte Konfiguration: zwei getrennte Rulesets

**Ein Bypass gilt für jede Regel des Rulesets, in dem der Akteur eingetragen ist.** Stünde die Merger-App mit `bypass_mode: "always"` im
selben Ruleset wie die Pflicht-Checks, könnte sie auch einen roten oder fehlenden Check umgehen. Ein früherer Entwurf dieses Dokuments hatte
genau diesen Fehler (ein einziges Ruleset mit Bypass); er wurde im Review gefunden und ist hier korrigiert. Deshalb gibt es zwei Rulesets:

| | **A: `platform-main merge conditions`** | **B: `platform-main restrict updates`** |
|---|---|---|
| Datei | [`rulesets/platform-main-merge-conditions.json`](rulesets/platform-main-merge-conditions.json) | [`rulesets/platform-main-restrict-updates.json`](rulesets/platform-main-restrict-updates.json) |
| Regeln | `pull_request` (0 Freigaben), `required_status_checks` (strikt: `test`, `TIM full suite`, `pr-gate/head`, jeweils an die GitHub-Actions-App gebunden, `integration_id: 15368`, Wert vor dem Import prüfen), `non_fast_forward`, `deletion` | nur `update` |
| Bypass-Akteure | **keine** (leere Liste) | **genau einer**: die Merger-App (`actor_type: Integration`, `bypass_mode: always`, `actor_id` vor dem Import ersetzen) |
| Wirkung | gilt für **alle**, auch für die Merger-App: PR erforderlich, alle drei Kontexte grün, Branch aktuell, kein Force-Push, kein Löschen | niemand außer der Merger-App darf `platform-main` aktualisieren, also auch nicht per PR mergen |

In GitHub unter „Settings → Rules → Rulesets → New ruleset → Import a ruleset“ (beide Dateien einzeln importieren).

**Wie ausschließlich die Merger-Identität mergt, ohne Checks umgehen zu können:** Ruleset B sperrt jede Aktualisierung von `platform-main` für alle
außer der Merger-App. Ruleset A bleibt für die Merger-App voll wirksam, weil es keinen Bypass hat: Sie darf nur über einen PR mergen,
dessen drei Pflicht-Kontexte grün sind und dessen Branch aktuell ist. Ein direkter Push der Merger-App scheitert an der PR-Pflicht, ein roter
oder fehlender Check am Pflicht-Check. Das ist **GitHubs Ruleset-Semantik nach meinem Kenntnisstand und nicht selbst getestet**; es zählt erst,
wenn die Negativversuche 6 bis 8 und 11 bis 13 unten belegt sind. Der Controller prüft vor jedem echten Merge, dass A keinen und B genau den einen
erwarteten Bypass-Akteur hat, dass keine Pflichtregel in B steht und dass jede Regel auf `platform-main` wirksam ist (Abgleich mit
`rules/branches/platform-main`).

**Preis der Strenge:** Wegen B kann auch der Inhaber `platform-main` nicht mehr direkt oder per PR ändern. Wollen Sie als Inhaber weiter normal per PR
mergen, brauchen Sie eine bewusste Entscheidung: B weglassen (dann kann aber auch der Worker mit Schreibrecht mergen, sobald A erfüllt ist, und die
Zusatzprüfungen des Controllers sind umgehbar) oder B für eine Änderung kurzzeitig und protokolliert anpassen. Ein allgemeiner Admin-Bypass ist nicht
vorgesehen.

**Rechte für die Prüfung:** Den Bypass kann nur lesen, wer das Ruleset im Detail lesen darf. Die Merger-App braucht dafür das Repository-Recht
*Administration: Read-only* (nur lesen, kein Schreiben). Das ist ein bewusster Kompromiss; ohne dieses Recht kann der Controller die Bypass-Konfiguration
nicht prüfen und merged deshalb nie.

## 3. Der Base-Race: welche Regel verhindert den Merge?

`sha=` im Merge-Aufruf schützt nur vor einem geänderten **Head**. Läuft `platform-main` nach der Prüfung weiter, schützt ausschließlich
`strict_required_status_checks_policy: true` in Ruleset A („Branch muss vor dem Merge aktuell sein“): GitHub lehnt den Merge dann ab (nach meinem
Kenntnisstand mit HTTP 405 „Base branch was modified“; nicht selbst getestet, siehe Negativversuch 6). Der Controller prüft zusätzlich unmittelbar vor
dem Merge erneut `behind_by == 0` und die Merge-Basis; ein Restfenster von Millisekunden schließt nur die Regel.

## 4. Negativversuche (nach dem Anlegen der Rulesets, vor jeder Aktivierung)

Jeder Versuch muss scheitern. Ergebnis und Zeitpunkt eintragen; **bis alle Zeilen belegt sind, bleibt `enabled: false`.** Das sind echte Versuche
gegen GitHub und nicht automatisiert: Gelingt ein Merge, den die Regeln verhindern sollten, ist das Ruleset unwirksam und ein roter Test läge auf
`platform-main` (sofort zurücknehmen, `enabled: false` lassen).

| Nr. | Versuch | Erwartung | Beleg |
|---|---|---|---|
| 1 | Worker-Token: `git push origin HEAD:platform-main` | abgelehnt (B und PR-Pflicht) | offen |
| 2 | Worker-Token: Force-Push auf `platform-main` | abgelehnt (`non_fast_forward`) | offen |
| 3 | Inhaber (Admin): direkter Push auf `platform-main` | abgelehnt (kein Bypass) | offen |
| 4 | Worker-Token: Datei unter `.github/workflows/` auf einen Branch pushen | abgelehnt (App ohne Recht „Workflows“) | offen |
| 5 | Worker-Token: einen grünen PR mergen | abgelehnt (B, kein Bypass) | offen |
| 6 | Merger-Token: einen PR mergen, dessen Branch hinter `platform-main` liegt | abgelehnt (strikte Aktualität, A) | offen |
| 7 | Merger-Token: PR ohne den Commit-Status `pr-gate/head` mergen | abgelehnt (Pflicht-Kontext, A) | offen |
| 8 | Merger-Token: PR mit rotem `TIM full suite` mergen | abgelehnt (Pflicht-Kontext, A) | offen |
| 9 | `GET /repos/{repo}/rules/branches/platform-main` | `deletion`, `non_fast_forward`, `pull_request`, `required_status_checks` aus Ruleset A und `update` aus Ruleset B | offen |
| 10 | `--verify-rulesets` | `ok: true`, keine Probleme | offen |
| 11 | Merger-Token: PR mit fehlendem `test` mergen | abgelehnt (Pflicht-Kontext, A) | offen |
| 12 | Merger-Token: direkter Push auf `platform-main` ohne PR | abgelehnt (PR-Pflicht in A, kein Bypass) | offen |
| 13 | Merger-Token: Force-Push und Löschen von `platform-main` | abgelehnt (`non_fast_forward`, `deletion` in A) | offen |

**So geht ein Versuch mit rotem Check (Nr. 8) gefahrlos:** Auf einem Wegwerf-Branch `claude/issue-<N>-probe-red` eine Datei
`tests/test_zz_probe_must_stay_red.py` mit einem Test anlegen, der `assert False` enthält, PR öffnen, warten bis `TIM full suite` rot ist, dann mit
dem Merger-Token `gh api -X PUT repos/OWNER/REPO/pulls/<N>/merge -f sha=<head> -f merge_method=squash` ausführen. Erwartet ist eine Ablehnung
(HTTP 405 oder 403), danach PR schließen und Branch löschen. Entsprechend für 7 (Status nicht gesetzt) und 11. Den Merge-Aufruf nie mit
deaktiviertem Ruleset wiederholen.

## 5. GitHub-eigenes Auto-Merge

`allow_auto_merge` ist `false` und wird **nicht** gebraucht: Der Controller merged über die API. GitHubs eigenes Auto-Merge könnte
die Merge-Steuerung ersetzen, kennt aber weder die Autor-Identität noch das erneute Gate noch die Bindung der Checks an
Workflows; deshalb ist es hier nicht vorgesehen.
