# T05: Evidenz-, Hash- und Zeitvertrag – Entscheidungsvorlage

Stand 22.10.2026. Grundlage: `TIM_HASH_CONTRACT_SPECIFICATION_V2.md` (HC-1.0, Status „READY“, Abschnitt 17
verlangt eine Governance-Entscheidung), `TIM_V2_BLOCKER_REGISTER.md` (B03, B04, B05, B07),
`docs/v2_completion/independent_case_methodology.md`, der Readiness-Befund vom 20.10. und die Paketinventur.
Dieses Dokument entscheidet nichts; es stellt die Optionen so, dass Uzi mit einem Satz entscheiden kann und
die Umsetzung danach ohne Rückfrage startet.

## 1. Zeitvertrag (vier Zeiten, die nie vermischt werden)

| Zeit | Bedeutung | Quelle im Code heute | Regel |
|---|---|---|---|
| `event_time` | Zeitpunkt des Marktereignisses (Trade, Kerzenschluss, Beobachtung `observed_at`) | `Trade.event_time`, `Observation.observed_at`, `OrderflowMetric.window_end` | Pflicht, UTC, `Z` |
| `available_at` (Wissenszeit) | ab wann TIM das Ereignis kannte (Persistenzzeit, bei Feeds `known_at`) | `knowledge/*.known_at`, `research_lab/external/pit.py`, `retrospective._known_at` (Maximum aus `validated_through` und Horizont-`target_at`) | Pflicht für neue Artefakte; **fehlt sie historisch, bleibt sie `null` und wird nicht geschätzt** |
| `revision` | Version der Regel/des Codes, die das Artefakt erzeugt hat | `rule_version`, `validation_version`, `software_commit`, `PROTOCOL_VERSION` | Pflicht, Teil des Hash-Inputs |
| `as_of` (Abfragezeit) | Stichtag, zu dem eine Auswertung „weiß“ | `retrospective(as_of=…)`, `OrderflowValidationEngine.validate(as_of=…)`, neu `RAGQwenAssistant.build_context(as_of=…)`, Research Lab `known_at()` | Jede Auswertung nennt `as_of`; es zählt nur, was `available_at <= as_of` hat |

Verbot: `as_of` oder Dateizeiten dürfen nie in einen Hash einfließen (HC-1.0 Abschnitt 7.3). Eine Auswertung ohne
`as_of` ist keine historische Aussage, sondern ein Blick „von heute“.

## 2. Quellbindung von Evidenz: D01 oder D02

| Option | Beschreibung | Vorteil | Nachteil |
|---|---|---|---|
| **D01 direkte Quellhash-Referenz** | Jedes Evidenzelement trägt `{domain, hash}` der Quelle (`source_hash` der Metrikfenster, `input_hash` der Beobachtung, `validation_hash`). Prüfer rechnet die Quelle neu und vergleicht. | schlank, heute schon so im Code (`previous_source_hash`, `current_source_hash`, `observation_hash`) | Quelle muss abrufbar bleiben (DB, Archiv); bei Löschung ist die Referenz leer |
| **D02 Snapshot-Payload + äußere Hülle** | Artefakt enthält die kanonisch serialisierte Quelle (Payload) und eine äußere Hülle mit `artifact_hash`, `payload_hash`, Registry-Eintrag | selbsttragend, auch nach Löschung der Quelle prüfbar | Größe (Outbox-Zeilen, Trades), doppelte Daten, Kanonisierung der Payload nötig (TIM-JCS-1) |

**Empfehlung:** D01 für laufende Belege (Tagesmanifeste, Beobachtungen, Validierungen), D02 nur für die
wenigen Abnahme-Artefakte, die ohne Datenbank prüfbar sein müssen (Kampagnen-Abschlussdossier, Holdout-Lauf,
Manual-Review-Workbook). Begründung: Die Kampagne schreibt heute schon D01-Referenzen; D02 überall würde die
Datenbank vervielfachen.

## 3. Hashdomänen und Registry (aus HC-1.0 Abschnitt 8, hier nur die Entscheidung)

Domänen: `artifact_hash`, `source_hash`, `dataset_hash`, `replay_hash`, `manifest_hash`, `report_hash`,
`snapshot_hash`, `integrity_hash`. Jeder Hash nennt seine Domäne; ein Vergleich über Domänen hinweg ist ein
Fehler, kein Treffer. Kanonisierung: TIM-JCS-1 (sortierte Schlüssel, keine Leerzeichen, Dezimalzahlen als
Strings, Zeiten nach 7.3). Registry: `artifact_type`, `schema_version`, `hash_domain`, `required_fields`.

Fehlerzustände (müssen Tests haben): fehlende Domäne, Domänenverwechslung, manipulierte Quelle,
Zeit mit Offset statt `Z`, Float statt Dezimalstring, zyklische Referenz (Artefakt referenziert sich selbst),
`available_at` in der Zukunft relativ zu `as_of`.

## 4. Konformitätssuite (V2-only, keine Core-1.0-Mutation)

Ort: `tests/test_evidence_contract_v2.py` (neu), Fixtures unter `tests/fixtures/evidence_contract/` mit
unabhängig berechneten Sollbytes (Sollhashes einmal von Hand mit `sha256sum` über die kanonische Datei erzeugt
und als Kommentar notiert). Mindestens je ein Positiv- und ein Negativfall pro Fehlerzustand aus Abschnitt 3.
Die Suite prüft nur V2-Artefakte; alte Artefakte unter `artifacts/` bleiben bytegleich und werden nicht umgeschrieben.

## 5. Dispositionsregister für historische Befunde

Jeder alte FAIL (B03 Artefakt-Audit, B04 Research-Qualität, B05 Herkunft) bekommt genau eine Zeile:

| Befund | Quelle | Einstufung | Begründung | Beleg | Entscheider |
|---|---|---|---|---|---|
| … | Datei/Hash | ECHTER_FEHLER · BEKANNTE_FEHLKLASSIFIKATION · UNVERÄNDERLICHE_LEGACY_LÜCKE · OFFENER_NACHWEIS | … | … | Name, Datum |

Regel: Kein FAIL wird von Hand zu PASS. Eine Legacy-Lücke bleibt Lücke und wird als Grenze des Geltungsbereichs
ausgewiesen (Beispiel: die vier Kerzenlücken vom Oktober, Readiness-Befund 20.10.).

## 6. Was Uzi entscheidet (ein Satz genügt)

1. D01 für laufende Belege, D02 für Abnahme-Artefakte: ja/nein.
2. HC-1.0 als Vertrag Version 1.0 einfrieren und die Konformitätssuite bauen: ja/nein.
3. Wer trägt die Dispositionen ein (Vorschlag: Chris als unabhängiger Prüfer, Uzi gibt frei).

Nach „ja“ folgt die Umsetzung in zwei PRs: (a) Registry, Kanonisierung, Validator und Suite unter
`src/v2_completion/evidence_contract.py`; (b) Dispositionsregister als `docs/v2_completion/dispositionen.md`.
Beides berührt weder `~/TIM-live` noch die Datenbank.
