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

Ein persistierter fachlicher Stichtag gehört zum registrierten Payload und wird mitgehasht.
Nur flüchtige Ausführungszeiten und Dateimetadaten werden nicht nachträglich in den Hash-Input
injiziert. `as_of` pauschal auszuschließen wäre falsch: Der Snapshot-Stichtag muss gegen
Manipulation geschützt sein. Fehlende historische Wissenszeit wird nicht durch Ereigniszeit ersetzt.

## 2. Zwei getrennte Entscheidungen: D01 und D02

Die [ursprünglichen Ersatztexte vom 21.10.](hc1_d01_d02_resolution_proposal.md) sind hier
als prüfbare Referenz aufgenommen. Sie beziehen sich auf die unveränderte Spezifikation mit
SHA256 `a0189a91c30b05fddfa3ad5524137a24c0bae3b4469adedd3dcf5870a20fcacc`.
Beide Entscheidungen sind miteinander vereinbar; sie sind keine Auswahl „laufende Belege oder Abnahme“.

**D01 – Quellreferenzen:** Empfohlen ist der vollständige Descriptor des unmittelbar referenzierten
Objekts im Feld `source_hash`, einschließlich `digest`, `domain`, `artifact_type`, `algorithm`,
`canonicalization`, `contract_version` und `logical_source_id`. Kein zusätzlicher Digest der Domäne
`source`. Der Eigenhash des Verbrauchers bindet den Descriptor samt Identifier. Der Validator löst
die Quelle auf und prüft deren eigenen Descriptor. Quelle und Verbraucher dürfen beide Domäne
`artifact` haben; Feldrolle und Typ müssen trotzdem stimmen. Fehlende/ungültige Quellen und Zyklen
sind Fehler. Legacy-Digests dürfen nicht als HC-1.0 umetikettiert werden.

Das Schema erlaubt ausdrücklich entweder `source_hash` oder `source_hashes`, niemals beide.
Null- und Leerlisten-Erlaubnis sind getrennt. Mehrfachreferenzen sind bereits vor dem Hashen nach
`(artifact_type, logical_source_id, digest)` sortiert; doppelte `(artifact_type, logical_source_id)`
sind auch bei unterschiedlichen Digests ungültig. Der Validator repariert keine Reihenfolge.

**D02 – Snapshot-Projektion:** Empfohlen ist die gerichtete Berechnung
`snapshot_payload` → `snapshot_hash` → äußerer `artifact_hash` (falls das Schema ihn zulässt).
Der Snapshot-Hash bindet den gesamten persistierten Payload einschließlich Stichtag,
Quellen, Versionen, Zählungen und Inhalt. Unbekannte Felder sind Schemafehler. Der äußere
Eigenhash schließt ausschließlich sich selbst aus: Payload und vollständiger Snapshot-Descriptor
bleiben enthalten. Äußere Metadaten dürfen keinen Payload-Stichtag oder Inhalt überschreiben.
Ein korrekt neu berechneter Hüllenhash heilt keinen ungültigen inneren Snapshot-Hash.

**Status:** Vorschlag für eine neue freizugebende Vertragsrevision. Weder eine Zustimmung
noch ein Freeze der unveränderten HC-1.0-Spezifikation wird mit diesem PR behauptet.
Die heutigen Core-Referenzen sind keine nachträglich erklärten HC-1.0-konformen Descriptoren.

## 3. Registry und Feldbindung

HC-1.0 Abschnitt 9 verlangt elf Angaben je Typ: stabiler Typ-Identifier, Schema-Version,
erlaubte Hashdomänen, erforderliche Hashdescriptoren, Kanonisierung, Eigenhash-Ausschluss,
Array-Reihenfolgen, Dezimalregeln, Zeitregeln, optionale Felder und Referenzauflösung.
Die Revision ergänzt ausdrücklich die Bindung von Eigenobjekt und Quellobjekt sowie erlaubte
Referenz-Tupel aus Typ/Domäne/Version und die Kardinalität. Feldnamen wie `artifact_hash`
sind keine Domänennamen: der zugehörige Descriptor verwendet etwa `domain="artifact"`.
Die Domäne `source` entfällt bei Annahme von D01-A; `snapshot` bleibt für D02.

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

## 6. Entscheidungsprotokoll

| Datum (UTC) | Entscheider | Entscheidung | Geltungsbereich | Nicht enthalten |
|---|---|---|---|---|
| 2026-10-22 09:35 | Uzi (Governance) | **D01-A und D02-A als Design freigegeben.** Wortlaut: „D01-A und D02-A gebe ich als Design frei.“ | Designentscheidung für die neue Vertragsrevision (Abschnitt 2); Grundlage für Registry, Kanonisierung, Validator und Konformitätssuite in einem separaten Implementierungs-PR. | Keine Betriebsfreigabe, kein Freeze von HC-1.0, keine Änderung an Livebetrieb, Datenbank oder alten Artefakten. B07 bleibt offen, bis die Vertragsrevision mit Registry und Testvektoren gesondert freigegeben ist. |

Ebenfalls am 22.10.2026 09:35 UTC festgehalten: S2 bleibt Entwurf 0.2 (Power-Simulation und
Methodenprüfung vor jeder Studienfreigabe), die in Abschnitt 6.1 Punkt 3 genannten Rollen bleiben
Vorschlag, bis die Personen sie ausdrücklich annehmen, und PR #365 bleibt Entwurf ohne Merge.

## 6.1 Was Uzi entschieden hat beziehungsweise noch entscheidet

1. D01-A (direkter vollständiger Quell-Descriptor) und D02-A (expliziter Snapshot-Payload mit Hülle): **als Design freigegeben am 22.10.2026 09:35 UTC** (Abschnitt 6).
2. Danach neue Vertragsrevision mit vollständiger Registry, unabhängigen Testvektoren, Rollen,
   V2-only-Grenze und Cut-over-Policy prüfen und gesondert freigeben. Die unveränderte Spezifikation
   nicht voreilig einfrieren; B07 bleibt bis zum Entscheidungsnachweis offen.
3. Dispositionsrollen benennen (Vorschlag, nicht entschieden: Chris prüft, Uzi gibt frei).

Nach der Designentscheidung vom 22.10.2026 folgt ein separater Implementierungs-PR für Registry,
Kanonisierung, Validator und Konformitätssuite sowie ein Dispositionsregister.
Designfreigabe bedeutet weder Implementierungs- noch Betriebsfreigabe. Livebetrieb, Datenbank
und alte Artefakte werden durch diese Entscheidungsvorlage nicht verändert.
