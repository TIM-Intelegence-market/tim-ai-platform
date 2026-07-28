# TIM Intelligence Manager — S11 Contradiction Remediation

Prüfobjekt: `/Users/tim/Documents/TIM/tim`  
Ausgangsstatus: `REQUIRES LIMITED REMEDIATION`

## 1. S11 vor der Änderung

Definition: Zwei widersprüchliche, belegte Aussagen zum selben Subject und
Predicate müssen sichtbar bleiben.

Bestehende Testfunktion:
`tests/tim_manager/test_mandatory_acceptance.py::test_s11_conflicting_sources_are_visible`.

Erwartetes Verhalten:

- deterministische Erkennung inkompatibler Werte,
- Erhalt beider Claims und Evidenzreferenzen,
- Ausgabe im kanonischen Snapshot,
- Sichtbarkeit in einer Managementantwort oder einem Statusbericht.

Tatsächliches Verhalten:

- `src/tim_manager/state.py::build_snapshot` setzte `contradictions`
  unabhängig vom Eingang fest auf `[]`;
- `src/tim_manager/query.py::answer` gab ebenfalls immer eine leere
  Widerspruchsliste aus;
- der Statusbericht besaß keinen Widerspruchsabschnitt;
- S11 war deshalb mit `strict=True` als XFAIL markiert.

## 2. Root Cause

`ClaimRecord` existierte als Datenmodell, war aber nicht mit dem State Builder
verbunden. Es gab weder einen deterministischen Extraktor für explizit
strukturierte Artifact-Claims noch Regeln für Werte-, Zeit-,
Supersession- oder Claim-Klassen-Konflikte. Das Snapshot-Schema erlaubte nur
eine untypisierte Widerspruchsliste.

## 3. Kleinstmögliche sichere Korrektur

Die Korrektur bleibt auf TIM-IM beschränkt:

- nur explizit strukturierte Claims aus Artifact-Metadaten auswerten;
- keine pauschale Freitext- oder Ähnlichkeitserkennung;
- stabile Claim- und Contradiction-IDs;
- Konflikte nur bei gleichem Subject und Predicate, regelbasiert
  inkompatiblen Werten, ausreichender Evidenz und überlappender oder
  unbekannter Zeitauflösung;
- supersedierte Claims nicht als offenen Widerspruch behandeln;
- Interpretation und validiertes Resultat unterscheidbar halten und beide
  Claims bewahren;
- Snapshot, Query und Statusbericht mit derselben kanonischen
  Widerspruchsstruktur versorgen.

## 4. Neues Verhalten

Explizite JSON-Metadaten unter `tim_manager_claims` werden passiv übernommen.
Der State Builder normalisiert Subject und Predicate, verlangt mindestens eine
Evidenzreferenz und erkennt nur kontrollierte Status- oder Boolean-Konflikte.

Ein Konflikt wird nur erzeugt, wenn Subject und Predicate gleich sind, die
Werte regelbasiert inkompatibel sind und die Zeitintervalle überlappen oder
nicht auflösbar sind. Unterschiedliche bekannte Zeiträume, supersedierte
Claims und unterschiedliche dokumentierte Messmethoden erzeugen keinen offenen
Direktkonflikt.

`model_inference` und `agent_interpretation` überschreiben keine
`validated_result`-Claims. Die deterministische Priorität kann einen Claim
provisorisch bevorzugen; beide Claims und beide Evidenzketten bleiben im
Contradiction Record erhalten.

## 5. Geänderte Dateien

- `src/tim_manager/contradictions.py`
- `src/tim_manager/models.py`
- `src/tim_manager/state.py`
- `src/tim_manager/query.py`
- `src/tim_manager/reporting.py`
- `src/tim_manager/adapters.py`
- `schemas/tim_manager/project_snapshot.schema.json`
- `tests/tim_manager/test_contradictions.py`
- `tests/tim_manager/test_mandatory_acceptance.py`
- TIM-IM-Dokumentations- und Verwaltungsartefakte

Kein wissenschaftlicher TIM-Core, keine historische Research-Datei, keine
Trading-Komponente und keine globale Client-/Agent-Konfiguration wurde
verändert.

## 6. Schemaauswirkung

Das bestehende Feld `contradictions` bleibt erhalten. Die
Snapshot-Schema-Version wurde für die präzisierte Claim- und
Contradiction-Struktur von `1.0` auf `1.1` erhöht. Das Schema akzeptiert
weiterhin historische `1.0`-Snapshots; die formale Prüfung eines bestehenden
1.0-Snapshots ist Bestandteil des finalen Schema-Probes. Eine
Datenbankmigration war nicht erforderlich.

## 7. Testabdeckung

Die neue kontrollierte Suite deckt ab:

1. direkten Statuswiderspruch,
2. Erhalt beider Evidenzreferenzen,
3. Snapshot-Sichtbarkeit,
4. Query-Sichtbarkeit,
5. Statusbericht-Sichtbarkeit,
6. unterschiedliche Zeiträume,
7. Supersession,
8. Modellinterpretation gegen validiertes Ergebnis,
9. identische Claims,
10. unveränderten zweiten Build ohne Duplikat,
11. stabile Contradiction-ID,
12. getrennte Messmethoden,
13. passives namespaced JSON-Ingest.

Der ursprüngliche S11-Test ist nicht mehr XFAIL und prüft weiterhin zwei
gegensätzliche Quellen, jetzt mit explizitem Subject, Predicate,
Claim-Klasse und Evidenz.

## 8. Regressionsergebnisse

| Prüfung | Ergebnis |
|---|---|
| Pflichtmatrix | 20 passed, 0 skipped/XFAIL, 1 warning |
| TIM-IM-Suite | 58 passed, 1 warning |
| vollständige TIM-Suite | 237 passed, 145 warnings |
| Doctor | PASS, Exit 0 |
| Validate | PASS, Exit 0 |
| Folge-Scans | zweimal 234 unchanged, sonst 0 |
| Snapshot-ID | `43312fa2-a863-5f56-9765-0d7a224239be` in beiden Folge-Scans |
| Snapshot/Version/Export | bytegleich, SHA-256 `73c6481e3f33ed0ccdc8514fa81bdaf481d104f1bf0b2002da211592b82ebb7d` |
| Protected-Prüfung | 44 baselinegleich, vier bekannte volatile Runtime-Dateien geändert, 0 fehlend, 5/5 Schreibproben verweigert |
| MCP-Prüfung | Exit 0, 0 Mutationswerkzeuge, Protected- und Indexzustand vor/nach identisch |

Vollständige Befehle, Exit-Codes und Probe-Ausgaben:
`artifacts/tim_manager/reports/final_verification_probe_results.md`.

## 9. Verbleibende Einschränkungen

- Freitext wird bewusst nicht als Claim interpretiert.
- Unterstützte automatische Wertkonflikte sind auf kontrollierte
  Status-/Boolean-Regeln beschränkt; unbekannte Predicates führen nicht zu
  geratenen Widersprüchen.
- Die 145 pytest-asyncio-Warnungen bleiben technische Schuld.
- Die Workspace-Agent-Anbindung bleibt eine separate, nicht implementierte
  externe Integration.
