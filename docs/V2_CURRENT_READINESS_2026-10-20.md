# TIM — Readiness-Befund vom 20.10.2026, 04:28 MESZ

**Historische Bestandsaufnahme, keine Qualifizierung oder Handelsfreigabe.**
Eine neue Messung für den heutigen Mittag ist beim Owner angefragt. Dieser
Bericht bleibt als eigener Messstand erhalten.

## Betriebsreparatur abgeschlossen

Restore am 20.10. um 04:30:13 MESZ PASS. Dump-Prüfsumme bestätigt; Restore nicht
leer und Testdatenbank entfernt. 72.288.941 AggTrades stimmen im gezählten
Cut-off überein. Restore enthielt 152.865 Kerzen; der laufende Bestand enthielt
152.866, also eine zusätzliche spätere historische Kerze. Der Bericht weist
`match=false` und `backfilled_after_dump=1` ausdrücklich aus; der bestehende
monotone Vergleich akzeptiert diesen Zuwachs. Keine vollständige Bytegleichheit
aller Live-Tabellen behauptet.

Liveness nach dem Fix wiederholt 1440/1440 PASS mit zwei Minuten Settlement.
Die aktuelle Runtime läuft weiterhin OBSERVE und emittiert null Handelsaktionen.

## Zeiträume und Ergebnisse

| Messung | Umfang | Ergebnis |
|---|---|---|
| Abdeckung geschlossener 1m-Kerzen | 01.10. 00:00 UTC bis 20.10. 02:28 UTC | 19.755 / 27.508 = 71,816 %, FAIL gegen 95 % |
| Fehlende Minuten | dasselbe Fenster | 7.753 in fünf Bereichen |
| Ungültige Kerzen / Duplikate / synthetische Kerzen | dasselbe Fenster | jeweils 0 laut Audit |
| Strikte unabhängige 30m-Fenster | gesamter persistierter Fallbestand bis Cut-off, beginnt bereits im Juli | 1.899; reine Mengenprüfung PASS |
| Negativ-/Neutralkontrollen | Fall-Audit | ABSENT |
| Menschliches Review / Inter-Rater-Belege | Fall-Audit | PENDING / ABSENT |
| V2 und Trading | keine erteilte Freigabe | false / false |

Die 1.899 Fenster sind kein Oktober-only-Wert und keine bereits absolvierte
prospektive Qualifizierung. Der alte Auditor hat im äußeren `gate_reason` noch
einen pauschalen Text über fehlende 1.000 Fenster. Dieser Teil ist angesichts
der tatsächlich gemessenen 1.899 überholt; der Rohbericht wird nicht umgeschrieben.
Die unabhängigen Kontrollen, Regime-Nachweise und menschlichen Entscheidungen
fehlen weiterhin, daher bleibt die Gesamtfreigabe aus.

## Fehlende Kerzen im Messfenster

| Beginn UTC | Ende UTC (exklusiv) | Minuten | Minuten mit Rohdaten |
|---|---|---:|---:|
| 2026-10-01T00:00:00Z | 2026-10-01T19:57:00Z | 1197 | 1197 |
| 2026-10-03T17:21:00Z | 2026-10-05T13:14:00Z | 2633 | 2633 |
| 2026-10-06T00:42:00Z | 2026-10-06T00:45:00Z | 3 | 3 |
| 2026-10-07T06:25:00Z | 2026-10-09T23:38:00Z | 3913 | 3913 |
| 2026-10-20T02:21:00Z | 2026-10-20T02:28:00Z | 7 | 1 |

Alle fünf Ursachen sind im Audit als **PROBABLE / PARTIAL_WRITE** eingestuft,
nicht als abschließend bewiesene RCA. Die vier großen alten Bereiche liegen
außerhalb des aktuellen siebentägigen Reparaturfensters. Der letzte kleine
Bereich liegt am Ende der damaligen Messung während des Restores; heutige
Liveness ist wieder vollständig. Eine neue Messung muss dessen aktuellen
Bestand klären.

Vorhandene Rohdaten machen technische Rekonstruktion denkbar. Der Audit stuft
sie ausdrücklich als governance-beschränkt ein. Keine künstlichen oder
interpolierten Kerzen verwenden, alte wissenschaftliche Belege nicht umschreiben,
und rekonstruierte Historie nicht als vorab deklarierte Live-Qualifizierung zählen.

## Herkunft und Zeitnähe

Der Rohdatenbestand im Coverage-Fenster enthält 15,482,177 Datensätze; davon 9,300,926 mit mehr als fünf Minuten Ingestionsverzug (60.08 %). Das ist ein weiterer Grund, den reparierten historischen Bestand und ein
zukünftiges prospektives Beobachtungsfenster getrennt zu behandeln. Es beweist
für sich genommen keine erfundenen Rohdaten und erklärt nicht jede einzelne Lücke.

## Nächste Schritte

1. Frische Mittagsmessung ergänzen und jeden Lückenbereich mit Belegen und Owner
   dispositionieren; keine Lücke allein durch Statusumschreiben schließen.
2. Server-Abgleich #339 ist im Repo gemergt, /opt/tim läuft noch auf c121efa mit
   Hotfixes. Kontrollierten Rollout samt Safe-stop, Cursor-/Outbox-Abnahme und
   Konfigurations-/Code-Freeze vorbereiten; kein blindes Reset oder Pull.
3. Netzwerkstabilität und Portal-DNS/Client-Vertrauen abnehmen. Externes Backup,
   Hardware/Rückkehrweg und die übrigen Startgates nachweisen.
4. Rollenentwurf tatsächlich annehmen, unabhängige Prüfer benennen und HC-1.0/
   menschliche Entscheidungen auf exakte Dokumentstände beziehen.
5. Erst nach diesen Gates das mindestens 34 volle UTC-Tage lange, vorab deklarierte
   Qualifizierungsfenster beginnen. Kein rückwirkender Start aus dieser Messung.

## Unveränderte Eingaben

- Vollständiger Audit: `artifacts/v2_readiness/current_states/20261020T022800Z.json`, SHA256 `4ed3950d80c9806d7fe9679911d36605e41bc013513fcbd1ac6b23799583e384`.
- Restore-Beleg: `artifacts/v2_readiness/current_states/restore_20261020T023013Z.json`.
- Datenbank-Lesevorgang: repeatable-read, readonly; historische Artefakte unverändert.

## Anzeige im Control Center

`artifacts/v2_readiness/current_state.json` ist eine kompakte, als Darstellung
gekennzeichnete Projektion des vollständigen datierten Rohberichts. SHA256 und
Quellpfad verweisen auf das unveränderte Original. Die neue Coverage-Zeile,
das Lückenregister und der aktuelle historische Fallzähler zeigen denselben
Cut-off. Qualifizierungs-, Frozen- und Freigabegates werden nicht überschrieben.
Eine spätere Messung erhält einen eigenen datierten Rohbericht; die Darstellung
kann in einem geprüften Commit auf diesen neuen Stand zeigen.

Journalbeleg für #331: Im Zeitraum 04:20–04:45 MESZ sind zwölf FAIL-Läufe bei
unvollständiger Abdeckung und dreizehn PASS-Läufe bei 100 % gespeichert.
Die zugehörigen neuen datierten Artefakte liegen unter current_states/.
