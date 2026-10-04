# Auto-Merge: GitHub-Schutzregeln als harte Voraussetzung

**Solange diese Regeln nicht angelegt und per Negativversuch geprüft sind, bleibt Auto-Merge aus.** Ein Code-Gate allein ist
keine technische Sperre für andere Schreibberechtigte: Wer Schreibrecht hat und keine Regel im Weg findet, kann selbst nach
`platform-main` pushen oder mergen. Der Controller liest deshalb **unmittelbar vor jedem einzelnen Merge** (nicht nur einmal zu Beginn des Laufs; ein echter Lauf mergt genau einen PR) **beide Rulesets unten samt ihrer
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
wenn die Negativversuche 6 bis 8 und 11 bis 13 unten in Stufe 1 (Testrepository) belegt sind. Der Controller prüft vor jedem echten Merge, dass A keinen und B genau den einen
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

## 4. Negativversuche: erst im Testrepository, dann nur lesend im Produktionsrepository

**Stufe 1, Testrepository.** Alle 13 Versuche laufen in einem **privaten Testrepository mit identischen Regeln** (Aufbau, Fixture-Workflows und
Gleichheitsbeleg: [`rulesets/test-repo/README.md`](rulesets/test-repo/README.md)). Gelingt dort ein Merge, den die Regeln verhindern sollten, ist
das Ruleset falsch konfiguriert, und der Schaden bleibt im Testrepository. **Stufe 2, Produktionsrepository.** Dort gibt es danach nur die
**lesenden** Prüfungen (Versuche 9 und 10); kein roter, fehlender oder veralteter PR wird nach `platform-main` gemergt. Bis alle Zeilen in Stufe 1
belegt sind und der Gleichheitsbeleg leer ist, bleibt `enabled: false`.

| Nr. | Versuch (in Stufe 1) | Erwartung | Beleg Stufe 1 | Beleg Stufe 2 |
|---|---|---|---|---|
| 1 | Worker-Token: `git push origin HEAD:platform-main` | abgelehnt (B und PR-Pflicht) | offen | nicht ausführen |
| 2 | Worker-Token: Force-Push auf `platform-main` | abgelehnt (`non_fast_forward`) | offen | nicht ausführen |
| 3 | Inhaber (Admin): direkter Push auf `platform-main` | abgelehnt (kein Bypass) | offen | nicht ausführen |
| 4 | Worker-Token: Datei unter `.github/workflows/` auf einen Branch pushen | abgelehnt (App ohne Recht „Workflows“) | offen | nicht ausführen |
| 5 | Worker-Token: einen grünen PR mergen | abgelehnt (B, kein Bypass) | offen | nicht ausführen |
| 6 | Merger-Token: einen PR mergen, dessen Branch hinter `platform-main` liegt | abgelehnt (strikte Aktualität, A) | offen | nicht ausführen |
| 7 | Merger-Token: PR ohne den Commit-Status `pr-gate/head` mergen | abgelehnt (Pflicht-Kontext, A) | offen | nicht ausführen |
| 8 | Merger-Token: PR mit rotem `TIM full suite` mergen (Datei `PROBE_RED_FULL`) | abgelehnt (Pflicht-Kontext, A) | offen | nicht ausführen |
| 9 | `GET /repos/{repo}/rules/branches/platform-main` | `deletion`, `non_fast_forward`, `pull_request`, `required_status_checks` aus Ruleset A und `update` aus Ruleset B | offen | offen (lesend) |
| 10 | `--verify-rulesets` | `ok: true`, keine Probleme | offen | offen (lesend) |
| 11 | Merger-Token: PR mit fehlendem oder rotem `test` mergen (Datei `PROBE_RED_TEST`) | abgelehnt (Pflicht-Kontext, A) | offen | nicht ausführen |
| 12 | Merger-Token: direkter Push auf `platform-main` ohne PR | abgelehnt (PR-Pflicht in A, kein Bypass) | offen | nicht ausführen |
| 13 | Merger-Token: Force-Push und Löschen von `platform-main` | abgelehnt (`non_fast_forward`, `deletion` in A) | offen | nicht ausführen |
| 14 | Gleichheitsbeleg: beide Rulesets normalisiert in beiden Repositories | Unterschied leer | offen | offen |

Den Merge-Aufruf nie mit deaktiviertem Ruleset wiederholen und im Testrepository nach jedem Versuch den PR schließen und den Branch löschen.

## 5. GitHub-eigenes Auto-Merge

`allow_auto_merge` ist `false` und wird **nicht** gebraucht: Der Controller merged über die API. GitHubs eigenes Auto-Merge könnte
die Merge-Steuerung ersetzen, kennt aber weder die Autor-Identität noch das erneute Gate noch die Bindung der Checks an
Workflows; deshalb ist es hier nicht vorgesehen.
