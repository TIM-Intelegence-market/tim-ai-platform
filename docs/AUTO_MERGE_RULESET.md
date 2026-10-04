# Auto-Merge: GitHub-Schutzregeln als harte Voraussetzung

**Solange diese Regeln nicht angelegt und per Negativversuch geprüft sind, bleibt Auto-Merge aus.** Ein Code-Gate allein ist
keine technische Sperre für andere Schreibberechtigte: Wer Schreibrecht hat und keine Regel im Weg findet, kann selbst nach
`platform-main` pushen oder mergen. Der Controller verlangt deshalb vor jedem echten Merge, dass GitHub die Regeln unten für
`platform-main` meldet (`GET /repos/{repo}/rules/branches/platform-main`), und bricht sonst ab.

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

## 2. Exakte Ruleset-Konfiguration für `platform-main`

Datei: [`docs/rulesets/platform-main-auto-merge.json`](rulesets/platform-main-auto-merge.json) (in GitHub unter
„Settings → Rules → Rulesets → New ruleset → Import a ruleset“). Vor dem Import `actor_id` durch die App-ID der Merger-App ersetzen.

| Regel | Wirkung |
|---|---|
| `pull_request` mit `required_approving_review_count: 0` | Änderungen nur per PR, **kein menschliches Review** |
| `required_status_checks`, `strict_required_status_checks_policy: true` | `test`, `TIM full suite` und der Commit-Status `pr-gate/head`, jeweils von `github-actions` (`integration_id: 15368`, Wert vor dem Import prüfen); der Branch muss **aktuell** sein |
| `non_fast_forward` | kein Force-Push |
| `deletion` | `platform-main` kann nicht gelöscht werden |
| `update` | niemand darf `platform-main` aktualisieren, außer den Akteuren der Bypass-Liste |
| Bypass-Liste | **genau ein** Eintrag: die Merger-App. Kein Repository-Admin, kein Inhaber, keine Rolle |

**Wie ausschließlich die Merger-Identität mergt:** Wegen der Regel `update` kann weder der Worker (Schreibrecht, kein Bypass)
noch der Inhaber `platform-main` verändern; nur die Merger-App umgeht die Regel und führt über die Merge-API aus, was der Controller
freigegeben hat. Das ist der Preis der Strenge: Auch menschliche Änderungen an `platform-main` laufen dann nicht mehr an der Regel
vorbei. Wollen Sie als Inhaber weiter normal per PR mergen, brauchen Sie eine bewusste Entscheidung (Variante ohne `update`, siehe
unten, oder ein protokolliertes, kurzzeitiges Anpassen des Rulesets). Einen allgemeinen Admin-Bypass sieht der Entwurf nicht vor.

*Variante ohne `update`:* Menschliche PRs mergen normal. Dann kann aber auch der Worker (Write) selbst mergen, sobald alle
Pflicht-Checks grün sind. Das ist nur dann vertretbar, wenn diese Pflicht-Checks luftdicht sind; die Zusatzprüfungen des Controllers
(Bindung der Checks an Workflow und Lauf, erneutes Gate, Regelprüfung) würden dabei umgangen.

## 3. Der Base-Race: welche Regel verhindert den Merge?

`sha=` im Merge-Aufruf schützt nur vor einem geänderten **Head**. Läuft `platform-main` nach der Prüfung weiter, schützt
ausschließlich `strict_required_status_checks_policy: true` („Branch muss vor dem Merge aktuell sein“): GitHub lehnt den Merge
dann ab (nach meinem Kenntnisstand mit HTTP 405 „Base branch was modified“; nicht selbst getestet, siehe Negativversuch 6). Der
Controller prüft zusätzlich unmittelbar vor dem Merge erneut `behind_by == 0` und die Merge-Basis; ein Restfenster von Millisekunden
schließt nur die Regel. Ohne die Regel meldet `GET .../rules/branches/platform-main` sie nicht, und der Controller merged nicht.

## 4. Negativversuche (nach dem Anlegen des Rulesets, vor jeder Aktivierung)

Jeder Versuch muss scheitern. Ergebnis und Zeitpunkt hier festhalten; **bis alle Zeilen belegt sind, bleibt `enabled: false`.**

| Nr. | Versuch | Erwartung | Beleg |
|---|---|---|---|
| 1 | Worker-Token: `git push origin HEAD:platform-main` | abgelehnt (Regel `update`/PR erforderlich) | offen |
| 2 | Worker-Token: Force-Push auf `platform-main` | abgelehnt (`non_fast_forward`) | offen |
| 3 | Inhaber (Admin): direkter Push auf `platform-main` | abgelehnt (kein Bypass) | offen |
| 4 | Worker-Token: Datei unter `.github/workflows/` auf einen Branch pushen | abgelehnt (App ohne Recht „Workflows“) | offen |
| 5 | Worker-Token: einen grünen PR mergen | abgelehnt (`update`, kein Bypass) | offen |
| 6 | Merger-Token: einen PR mergen, dessen Branch hinter `platform-main` liegt | abgelehnt (strikte Aktualität) | offen |
| 7 | PR ohne den Commit-Status `pr-gate/head` mergen | abgelehnt (Pflicht-Check) | offen |
| 8 | PR mit rotem `TIM full suite` mergen | abgelehnt (Pflicht-Check) | offen |
| 9 | `GET /repos/{repo}/rules/branches/platform-main` | fünf Regeln: `deletion`, `non_fast_forward`, `update`, `pull_request`, `required_status_checks` (strikt, drei Kontexte) | offen |
| 10 | Controller im Dry-Run mit `require_branch_rules: true` | meldet keine Regel-Blocker | offen |

## 5. GitHub-eigenes Auto-Merge

`allow_auto_merge` ist `false` und wird **nicht** gebraucht: Der Controller merged über die API. GitHubs eigenes Auto-Merge könnte
die Merge-Steuerung ersetzen, kennt aber weder die Autor-Identität noch das erneute Gate noch die Bindung der Checks an
Workflows; deshalb ist es hier nicht vorgesehen.
