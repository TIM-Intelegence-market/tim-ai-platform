# TIM — Readiness-Befund 20.10.2026, 13:22 MESZ

Neue datierte Bestandsaufnahme nach Restore und unabhängigem Server-Abgleich. Keine Qualifizierung oder V2-/Handelsfreigabe. Der ältere 04:28-MESZ-Bericht bleibt unverändert erhalten.

PR #340 wurde nach ausdrücklicher Owner-Freigabe und grünen Pflichtchecks regulär gemergt, Merge `9505c6904b6edec59c18c39214ebced1a442e4d9`.

| Messung | Ergebnis |
|---|---|
| Coverage 01.10. 00:00 bis 20.10. 11:22 UTC | 20.296/28.042 = 72,377 %, FAIL gegen 95 % |
| Fehlende Minuten | 7.746 in vier historischen Bereichen |
| Ungültige / doppelte / synthetische Kerzen | jeweils 0 |
| Strikte 30m-Fenster im gesamten Fallbestand seit Juli | 1.917, reine Mengenschwelle PASS |
| Kontrollen / Inter-Rater / manuelles Review | ABSENT / ABSENT / PENDING |

Die sieben Fehlminuten am Ende der alten Messung sind aufgeholt. Der Nenner ist seitdem um 534 Minuten gewachsen; der Zähler um 541. Die vier alten Lücken sind unverändert. Die neue Fallzahl steigt um 18, ist aber weiterhin keine prospektive Qualifizierung. Der pauschale äußere `gate_reason` des alten Auditors bleibt im Rohbericht erhalten; seine Aussage über eine fehlende aktuelle 1.000er-Menge ist überholt.

## Disposition der historischen Lücken — Entwurf, nicht freigegeben

| Gap-ID | Zeitraum UTC, Ende exklusiv | Minuten | Rohdaten-Minuten | Disposition |
|---|---|---:|---:|---|
| gap-b297e1cb4d969bc7555d3def | 2026-10-01T00:00:00Z → 2026-10-01T19:57:00Z | 1197 | 1197 | OPEN: probable PARTIAL_WRITE; historische Einschränkung erhalten, unabhängige RCA/Disposition ausstehend |
| gap-585ddfd3f19a460b3aeb9507 | 2026-10-03T17:21:00Z → 2026-10-05T13:14:00Z | 2633 | 2633 | OPEN: probable PARTIAL_WRITE; historische Einschränkung erhalten, unabhängige RCA/Disposition ausstehend |
| gap-f2a873b86a60189e29984b13 | 2026-10-06T00:42:00Z → 2026-10-06T00:45:00Z | 3 | 3 | OPEN: probable PARTIAL_WRITE; historische Einschränkung erhalten, unabhängige RCA/Disposition ausstehend |
| gap-14d977d8dc10d9cecfff7728 | 2026-10-07T06:25:00Z → 2026-10-09T23:38:00Z | 3913 | 3913 | OPEN: probable PARTIAL_WRITE; historische Einschränkung erhalten, unabhängige RCA/Disposition ausstehend |

Für alle vier Bereiche liegen Rohdaten-Minuten vor. Das beweist noch keine lückenlose Trade-ID-Sequenz oder zulässige Rekonstruktion. Der vorhandene operative Reparaturjob begrenzt Kerzen auf sieben Tage; alle vier Bereiche liegen davor. Diese Grenze wird nicht still erweitert. `TIM_V2_BLOCKER_REGISTER.md` verlangt für B01 ein vorab definiertes Fenster ohne rekonstruierte Intervalle und für B02 eine unabhängig geprüfte Disposition. Historische Datenreparatur kann diese Qualifizierung nicht ersetzen. Daher wird kein schreibender Reparaturbefehl als automatische B01/B02-Schließung ausgeführt.

Vorgeschlagener nächster Schritt: Integrity Lead prüft für jeden Bereich Finalizer-/Netz-/Persistenzbelege und ordnet eine belegte Ursache samt wissenschaftlicher Einschränkung zu. Scientific Lead und unabhängige QA entscheiden über die zukünftige V2-Evidenzgrenze. Kein Owner-Akzeptanz- oder Signaturfeld ist ausgefüllt.

## Nächste Betriebsabnahme

Der letzte lesende Abgleich zeigt sauberen Server-Code auf #339 (`efd49d1`), aktive Runtime seit 11:02:20 UTC, `NRestarts=0`. Aktuelle Health/Liveness sind positiv. Der Owner-Export vom 20.10. 11:29 UTC belegt Safe-stop PASS um 11:02:18 UTC, Verarbeitung beim Checkpoint 0 und gültigen dauerhaften Cursor; anschließend Start PASS um 11:02:25 UTC. Die aktuelle separat als repeatable-read/readonly ausgeführte DB-Prüfung bestätigt Cursor-Hash und Version 1, Recovery NORMAL sowie keine offenen Ingestion-Incidents. Outbox: 23.360.663 COMPLETED und 2.857.192 DEFERRED, keine anderen Status im Snapshot. DEFERRED ist historische zurückgestellte Arbeit und nicht als abgearbeitet oder qualifiziert dargestellt. Die vier Kerzenlücken sind eine andere Messung und bleiben offen. Beleg: `artifacts/v2_readiness/current_states/lifecycle_20261020T112902Z.json`. Konfigurations-Freeze und unabhängige Abnahme der gesamten Startgates bleiben erforderlich. DNS/Client-Vertrauen, externes Backup und kontrollierter Reboot/Rückweg bleiben offen.

## Herkunft

Rohbericht: `artifacts/v2_readiness/current_states/20261020T112200Z.json`; SHA256 `1b622c21fb2b6b9ca4b27a8fbfb2bf016e0a98f91f3af076f8b7e6deca29113b`. Auditcode SHA256 `4009852dc81cd5393ef7db546e981fb04115897e99e60721e3f0acdd3250bd71`. Neue kompakte Anzeige zeigt diesen Cut-off; historische Belege werden nicht überschrieben.
