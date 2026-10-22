# HC-1.0: konkrete Lösung für D01 und D02

**21.10.2026 — Vorschlag zur menschlichen Prüfung, nicht freigegeben.**
Referenz ist die unveränderte Spezifikation mit SHA256
`a0189a91c30b05fddfa3ad5524137a24c0bae3b4469adedd3dcf5870a20fcacc`.
Die folgenden Ersatztexte sind ein Vorschlag für eine neue Revision. Sie
ändern weder diesen Quellstand noch Runtime, Qualifizierung oder Altdaten.

## Empfehlung D01: direkte Quellreferenz statt zusätzlichem Referenzhash

`source_hash` soll den vollständigen Descriptor des unmittelbar referenzierten
Quellartefakts enthalten, wie bereits im Beispiel 11.1. Es entsteht kein
zusätzlicher Digest in der Domäne `source`. Die Referenz wird durch den
Eigenhash des konsumierenden Artefakts mitgeschützt. Der logische Identifier
ermöglicht die Auflösung; er ersetzt die Digest-Prüfung nicht.

| Variante | Vorteil | Zusätzlicher Vertrag / Nachteil |
|---|---|---|
| **A: direkter Descriptor (empfohlen)** | Passt zu Beispiel 11.1; ein Quell-Digest; klarer Prüfgegenstand | Abschnitt 8.2, Feldbindung im Validator und Registry müssen präzisiert werden; Domäne `source` entfällt für diese Revision |
| B: eigener `source`-Wrapper | Die unmittelbare Abhängigkeitskante hat einen eigenen Digest | Zusätzlicher Payload mit `logical_source_id` und eingebettetem Quell-Descriptor; eigener registrierter Typ für die Kante, Resolver und weitere Fixtures nötig; Beispiel 11.1 wäre umzubauen |

Variante A reicht für den hier beschriebenen Integritätszweck aus: Der
Artefakt-Eigenhash bindet bereits Identifier und Quell-Descriptor gemeinsam.
Ein zusätzlicher Kantendigest ist erst mit einem gesonderten Anwendungsfall
und vollständig registriertem Kantenschema sinnvoll.

### Vorgeschlagener Ersatztext für Abschnitt 8.2

> `source_hash` is a reference field containing the complete hash descriptor
> of the immediate source object. It is not a newly computed hash domain.
> Its `domain`, `artifact_type`, `algorithm`, `canonicalization` and
> `contract_version` describe the referenced object, not the consuming object.
> Every non-null source descriptor MUST additionally contain a non-empty
> `logical_source_id`, resolved within the namespace pinned by the consuming
> artifact's registered schema. The identifier MUST be compared exactly;
> validators MUST NOT case-fold it, rewrite it or derive it from a filename.
> Identifier spelling and the complete source descriptor are included in the
> consuming artifact's self-hash payload.
>
> The registered schema MUST specify which cardinality forms it permits.
> Every artifact MUST use exactly one of its permitted forms:
> (1) single-source: required `source_hash`, either one descriptor or null
> where an absent source is permitted; or (2) multi-source: required
> `source_hashes`, an array of descriptors. The two fields MUST NOT coexist.
> Empty-array permission is explicit in the schema and MUST NOT be inferred
> from permission for null. Source arrays MUST already be in ascending
> Unicode-code-point order by `(artifact_type, logical_source_id, digest)`.
> Duplicate `(artifact_type, logical_source_id)` pairs MUST be rejected,
> including pairs with conflicting digests. Validators MUST NOT reorder input
> artifacts in place. Producers MUST finalize ordering before hashing.
>
> A validator MUST resolve the source and verify its declared descriptor
> against that source object before accepting the reference. A missing source
> yields `HASH_REFERENCE_UNRESOLVED`; a source that fails its own validation
> yields `HASH_REFERENCE_INVALID`. Resolver cycles MUST be rejected as
> `HASH_REFERENCE_INVALID` with reason `REFERENCE_CYCLE`, without unbounded
> recursion. A logical identifier resolving to another valid object with a
> different descriptor does not satisfy the reference.
>
> The schema MUST enumerate permitted referenced type/domain/version tuples.
> A V2 source descriptor MUST NOT relabel a legacy digest as HC-1.0. Legacy
> references use a separately specified legacy-reference field and policy.
> There is no computable `source` domain in this revision; attempts to use it
> as a digest domain yield `HASH_DOMAIN_UNKNOWN`.

### Änderungen an Beispiel 11.1, Registry und Validator

Das Beispiel erhält am vorhandenen `source_hash` zusätzlich etwa
`"logical_source_id": "insights/example-001"`. Sein Descriptor behält
`domain=artifact` und `artifact_type=tim.v2.research-insights`. Der
`artifact_hash` des konsumierenden Readiness-Berichts bleibt vom Typ
`tim.v2.readiness-report`. Alle Beispiel-Digests müssen anschließend aus den
neuen, vollständigen Beispielbytes neu berechnet werden. Bestehende Platzhalter
mit `aaaa…` oder `bbbb…` sind keine gültigen Testvektoren.

Abschnitt 9 muss zwischen den Domänen des Eigenobjekts und erlaubten
Referenz-Tupeln unterscheiden. In Abschnitt 10 wird vor dem Typvergleich der
Prüfgegenstand anhand der registrierten Feldbindung bestimmt: Ein
Eigenhash-Descriptor beschreibt das aktuelle Objekt, ein Quell-Descriptor das
aufgelöste Quellobjekt. Ein fremder Typ im Eigenhash bleibt
`HASH_ARTIFACT_TYPE_MISMATCH`. Ein unzulässiger Referenztyp wird als
`HASH_ARTIFACT_TYPE_MISMATCH` mit Feldpfad und Prüfgegenstand dokumentiert;
eine unzulässige Referenzdomäne als `HASH_DOMAIN_NOT_ALLOWED`.
Schemafehler der Kardinalität, Reihenfolge oder Duplikate werden vor dem
Hashvergleich als `HASH_DESCRIPTOR_INVALID` mit genauer Begründung erfasst.

Auch die pauschale Erwartung in Abschnitt 12 „Source reference presented as
artifact self-hash → HASH_DOMAIN_NOT_ALLOWED“ ist anzupassen: Bei einer
direkten Referenz können Quelle und Verbraucher beide die Domäne `artifact`
haben. Dann muss die Prüfung den falschen Typ, eine unzulässige Feldstruktur
oder den tatsächlichen Eigenhash-Mismatch melden. Ein Domänenfehler ist nur
bei einer tatsächlich unzulässigen Domäne die richtige Erwartung.

## Empfehlung D02: logischer Snapshot in einer äußeren Artefakthülle

Der Snapshot-Digest wird über ein ausdrücklich abgegrenztes Objekt
`snapshot_payload` gebildet. Die äußere Hülle enthält dieses Objekt, dessen
`snapshot_hash` und optional ihren eigenen `artifact_hash`. Die Richtung lautet:

```text
persistierter snapshot_payload
          ↓ snapshot-Domäne
     snapshot_hash
          ↓ Bestandteil der äußeren Hülle
Hülle ohne artifact_hash
          ↓ artifact-Domäne
     artifact_hash
```

So kann der Snapshot fertig gehasht werden, bevor der Eigenhash der Hülle
berechnet wird. Der Eigenhash schützt dabei weiterhin alle übrigen Felder.

| Variante | Vorteil | Nachteil |
|---|---|---|
| **A: expliziter Payload und äußere Hülle (empfohlen)** | Gerichtete Berechnung; klare Trennung von fachlichem Zustand und Metadaten | Neues Snapshot-Schema und Projektion müssen ausdrücklich registriert werden |
| B: flaches Objekt, Snapshot-Digest lässt beide Hashfelder aus | Kleinerer Umbau eines flachen Formats | Zusätzliche Ausschlussausnahme; fachliche Snapshot-Grenze gegenüber Hüllenmetadaten bleibt ohne weitere Regeln unscharf |

### Vorgeschlagener Ersatztext für Abschnitt 8.7

> A registered snapshot artifact MUST contain exactly one `snapshot_payload`
> object and one `snapshot_hash` descriptor. Its schema MAY permit an
> additional `artifact_hash` on the outer envelope. The logical snapshot input
> is exactly the complete persisted `snapshot_payload` object; the projection
> MUST NOT select arbitrary fields dynamically. `snapshot_payload` MUST NOT
> contain a hash descriptor of itself or of its containing envelope.
>
> The snapshot domain input is the section 6 structured domain envelope with
> `domain="snapshot"`, `artifact_type` equal to the registered outer snapshot
> type, and `payload` equal to `snapshot_payload`. No field is removed from
> that payload. The snapshot schema MUST enumerate all permitted payload
> fields and bind its schema version, persisted cut-off, source/dataset
> descriptors, component versions, counts, content and every ordering rule.
> Unknown payload fields MUST be rejected rather than silently excluded.
>
> The outer artifact self-hash follows section 8.1 without an additional
> exclusion: remove only the outer `artifact_hash`. Both `snapshot_payload`
> and the complete `snapshot_hash` descriptor remain in its hashed input.
> Outer metadata is permitted only when explicitly enumerated by the schema.
> No field may duplicate or override a payload's cut-off, version or content.
>
> Producers MUST finalize the logical payload, compute `snapshot_hash`,
> finalize the outer envelope, and then compute any outer `artifact_hash`.
> Validators MUST validate the schema and references, recompute the snapshot
> digest from the persisted payload, and then recompute the optional artifact
> digest. They MUST NOT inject time, mutate the payload or repair either hash.
> A mismatch yields `HASH_SELF_MISMATCH` with the failing descriptor's path
> and domain. Digest comparisons across snapshot and artifact domains remain
> prohibited even where a synthetic test supplies equal digest strings.

Abschnitt 8.1 bleibt unverändert. Die alternative flache Form wird nicht
stillschweigend zusätzlich akzeptiert. Eine spätere Formänderung benötigt
eine eigene Schema-Version und freigegebene Registry.

## Konkrete Abnahmebedingungen

Das Paket `hc1-resolution-proposals-20261021/` enthält synthetische vollständige
Beispielobjekte, die exakten vorgeschlagenen Hash-Eingabebytes und berechnete
Digest-Kandidaten. Die Bytes werden zusätzlich mit dem macOS-Werkzeug
`shasum -a 256` geprüft. Das ist eine zweite Rechenprüfung, keine unabhängige
menschliche Abnahme und keine vollständige TIM-JCS-1-Konformitätsprüfung.

Die Kandidaten müssen zeigen: gültige direkte Quellreferenz; ungültige und
fehlende Quelle; falscher Eigenhash-Typ; Mehrfachquellen mit eindeutiger
Ordnung; Snapshot-Inhaltsänderung verändert beide Digests; Änderung erlaubter
äußerer Metadaten verändert nur den Hüllenhash; Manipulation eines inneren
Digests wird auch bei neu berechnetem äußerem Digest abgewiesen;
domänenübergreifender Vergleich wird vor dem Digestvergleich abgewiesen.
Fehlerfälle besitzen vorgeschlagene Erwartungen, keine behaupteten
Validator-Ergebnisse.

Für eine Freigabe fehlen weiterhin: menschliche Entscheidung D01/D02,
vollständige Registry und Schemas für den tatsächlichen V2-Umfang,
unabhängige Fixture-Oracle-Prüfung, benannte Rollen, V2-only-Grenze und
Cut-over-Policy. Eine Zustimmung zu diesem Design ist keine
Implementierungs- oder Betriebsfreigabe. B07 bleibt bis zu den vorgeschriebenen
Entscheidungsnachweisen offen.
