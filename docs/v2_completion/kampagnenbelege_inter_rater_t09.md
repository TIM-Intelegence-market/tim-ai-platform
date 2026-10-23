# T09: Kampagnenbelege und wissenschaftliche Abnahme (Arbeitsstand und Pilotplan)

Stand 22.10.2026. Zone A. Nichts hier verändert Belege, Kampagne oder Datenbank.

## 1. Belegkette der Kampagne

| Beleg | Ort | Hashbindung | Stand |
|---|---|---|---|
| Vorregistrierung | `artifacts/v2_completion/qualification_preregistration.json` | `preregistration_hash`, `configuration_hash` | im Repo [V] |
| Kampagnendatei | `~/TIM-live/data/qualification/qualification_campaign.json` | bindet Vorregistrierungs-Hash, Software-Commit f469ad6, Start 2026-10-20 20:34 UTC | nur auf dem Mac [N] |
| Start-Gates | `~/TIM-live/data/qualification/start_gates.json` | Report-Hash im Kampagnenfile | nur auf dem Mac [N] |
| Tagesbelege | `~/TIM-live/data/qualification/daily/` (ein unveränderliches JSON je abgeschlossenem UTC-Tag) | Kampagnen-Hash je Beleg (PR #353 prüft Inhalt gegen Hash, offen) | erster Tag 2026-10-21 [N] |
| Repo-Spiegel | `artifacts/v2_completion/qualification_daily_manifests/` | – | bisher nur README [V] |

Offene PRs mit Bezug: #351 (Startbericht Hashgleichheit), #352 (Runtime-Zähler statt Null), #353 (Kampagnenhash
gegen Inhalt), #354 (UTC-Zeit der Startfreigabe), #357 (Health-Snapshot-Zeit erhalten). Sie gehören zu T09
Schritt 1–2 und sollten vor dem ersten Abgleich der Tagesbelege gemergt sein. Keiner läuft in `~/TIM-live`; die
Tagesbelege schreibt der eingefrorene Stand f469ad6. **Folge:** Fehler, die diese PRs beheben (etwa pauschale Null
bei Runtime-Zählern), stecken in den Belegen der laufenden Kampagne. Sie werden nicht nachträglich korrigiert,
sondern als verknüpfte neue Artefakte (`daily/<tag>.korrektur.json`) neben das Original gelegt, mit Verweis auf den
Fehler und den Commit der Korrektur.

## 2. Getrennte Bilanzen (Vorlage für das Abschlussdossier)

Je UTC-Tag und kumulativ: Coverage-Minuten (Zähler/Nenner), Fehlminuten mit Gap-ID, Kerzen gültig/ungültig,
Einheiten gesamt, davon strikt nicht überlappend, Qualitätslabels, Kontrollklassen (negativ/neutral), Regime.
Historische Fenster (vor 2026-10-20 20:34 UTC) und prospektive Fenster stehen in getrennten Spalten; die alte
Fallzahl 1.917 (seit Juli) zählt nicht zur Kampagne. Die 1.000er-Schwelle ist ein Registrierungskriterium, keine
Fallzahlplanung einer Studie (siehe S2-Präregistrierung, T08).

## 3. Historische Lücken (B02)

Die vier offenen Lücken vom 01.10., 03.–05.10., 06.10. und 07.–09.10. (Readiness-Befund 20.10.) bekommen je eine
Zeile im Dispositionsregister (T05 Abschnitt 5): Zeitraum, Rohdaten vorhanden ja/nein, bekannte Ereignisse
(Server-Ausfall, Router, Restore), Einstufung. „Ursache unbekannt“ ist zulässig; eine erfundene Ursache nicht.
Die Lücken liegen vor dem Kampagnenstart und betreffen die Kampagne nicht; sie begrenzen den Geltungsbereich
der Historie seit Juli.

## 4. Inter-Rater-Pilot (kann sofort beginnen, berührt den Mac nicht)

- **Material:** `artifacts/v2_completion/manual_review_workbook.json`, 24 Fälle vom 23.07.2026, alle Review-Felder
  leer (geprüft). Für den Piloten auf 50 Fälle ergänzen: 26 weitere aus einer Datenbank-Kopie, per Zufall (Seed
  dokumentiert) über die Beobachtungsarten geschichtet.
- **Verblindung:** Jeder Prüfer bekommt eine Kopie ohne `persisted_outcome` und ohne die Felder des anderen.
  Die Kopien werden aus dem Workbook erzeugt (`build_review_workbook`), nicht von Hand.
- **Prüfer:** zwei echte Personen. Vorschlag: Uzi und Chris. Chris ist Kandidat, nicht beauftragt; Identität,
  Unabhängigkeit (Chris hat Teile des Codes geschrieben) und Konflikte werden im Dossier benannt.
- **Felder:** die elf Pflichtfelder aus `validate_review_workbook` (PR #364 verlangt mindestens einen vollständigen Fall).
- **Auswertung:** Übereinstimmung je Feld (`observation_correct`, `label_correct`, `decision`), Cohens Kappa mit
  95-%-Intervall (Bootstrap über Fälle), Liste der Konflikte und ihre Auflösung. Kein pauschales PASS bei Kappa ≥ 0,6:
  das Intervall und die Klassenverteilung entscheiden, ob die Stichprobe für eine Aussage reicht; danach wird der
  Umfang für die eigentliche Abnahme geplant.
- **Zeitplan:** Vorbereitung der Kopien in der Cloud (dieser Branch), Bearbeitung durch die Prüfer offline, Rückgabe
  als JSON in `/mnt/project-files/reviews/inter-rater/`. Zusammenführung und Kappa per Skript (folgt nach T04-Merge,
  damit die Vollständigkeitsprüfung aus #364 genutzt wird).

## 5. Abschlussbewertung (frühestens 2026-11-23 20:34 UTC)

Am eingefrorenen Cut-off werden alle registrierten Kriterien ausgewertet: Mindestdauer, Coverage ≥ 95 %, 1.000
Einheiten, Kontrollen, Regimeabdeckung, Replay/Lookahead/Determinismus, menschliche Freigabe. Das Dossier bindet
Prüfpersonen, Datum, Begründung, Konfliktlösung und die Releaseentscheidung an Hashes der Belege. Datum, Fallzahl oder
ein guter Coverage-Wert allein schließen die Kampagne nicht ab.
