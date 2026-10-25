# V2-B05 Herkunftsnachweis (Historical Provenance): Inventar und V2-Grenze

Stand: 23.10.2026. Gehört zu `TIM_V2_BLOCKER_REGISTER.md` (V2-B05), Checkliste
`TIM_V2_READINESS_CHECKLIST.md` Abschnitt F, Programm `TIM_V2_REMEDIATION_PROGRAM.md` Workstream 5.

## Befund

`docs/TIM_V2_AUDIT_DISPOSITION_MATRIX_V1.md` legte eine V2-Grenze ab 2026-09-01 18:20 UTC fest: Alle neuen
Artefakte sollten `artifact_hash`, `generator_version` und `schema_version` tragen. Das galt laut Matrix als
„garantiert via `research_infrastructure_review.py`“.

Der Research-Cache `data/research/module_a_cache.jsonl` wird aber von `src/research/module_a/agent.py` geschrieben,
nicht von diesem Skript. Dieser Schreiber hat die drei Felder nie gesetzt.

- Am 23.10. meldete das stündliche Audit auf dem Mac deshalb 2.951 Einträge ohne die Felder
  (`MISSING_DOCUMENTATION`). Darunter sind auch Einträge nach dem 01.09.
- Die Grenze vom 01.09. war also nie wirksam. Der Anteil vollständiger Herkunft im V2-Bereich lag nicht bei 100 %.

## Änderung

1. `src/research/module_a/agent.py`: Jeder neue Cache-Eintrag bekommt `schema_version` 1.0.0,
   `generator_version` 1.0.0 und `artifact_hash`. Der Hash ist SHA-256 über den kanonischen Eintrag ohne
   `artifact_hash`, nach derselben Regel wie `src/research_ops/audit.py` `digest()`.
2. `src/v2_completion/provenance_inventory.py` und `scripts/v2_provenance_inventory.py`: ein Inventar, das nur liest.
   - Es zählt die vorhandenen und fehlenden Felder zu einem festen Stichtag (`--cutoff`).
   - Es ordnet jeden Cache-Eintrag einer Klasse aus Workstream 5 zu (siehe unten).
   - Es listet die Pflichtfelder aller JSON-Artefakte unter `data/research` auf.
   - Es hasht alle Dateien vor und nach dem Lauf (`bytes_unchanged`).

Alte Einträge werden nicht umgeschrieben und nicht nachträglich mit Feldern versehen.

| Klasse | Bedingung | Behandlung |
|---|---|---|
| COMPLETE_PROSPECTIVE | ab V2-Grenze, alle Felder da, Hash stimmt | zählt für den V2-Bereich |
| PARTIAL_LEGACY | vor der Grenze, Quelle (provenance, input_hash, created_at) da, V2-Felder fehlen | bleibt als Einschränkung dokumentiert |
| NON_RECONSTRUCTABLE | Quellfelder fehlen oder Zeile unlesbar | Einschränkung, nie rekonstruieren |
| CONFLICTING | Hash stimmt nicht, oder Eintrag ab Grenze ohne V2-Felder | aus dem V2-Bereich ausgeschlossen bis zur Entscheidung durch einen Menschen |

## V2-Grenze

Vorschlag: Die Grenze ist der Zeitpunkt des ersten Cache-Eintrags mit allen drei Feldern, also der Deploy dieser
Änderung auf dem Mac.

- Ohne `--boundary` leitet das Inventar die Grenze genau so ab.
- Die Grenze vom 01.09. wird nicht verwendet, weil sie nie durchgesetzt wurde.
- Einträge zwischen 01.09. und dem Deploy gelten als PARTIAL_LEGACY.

Aufruf auf dem Mac (nur lesend, Ausgabe außerhalb von `data/research`):

```
cd ~/TIM-live
.venv/bin/python scripts/v2_provenance_inventory.py --root . --cutoff <ISO-Zeit> \
  --output ~/Library/Application\ Support/TIM/provenance/inventory-<datum>.json
```

## Stand der Checkliste F

| Punkt | Stand |
|---|---|
| Vorhandene Felder inventarisiert | erledigt, Lauf auf dem Mac am 24.10. |
| Fehlende Felder inventarisiert | erledigt |
| Anzahl betroffener Einträge zu festem Stichtag | 3.302 Einträge zum Stichtag 2026-10-24T00:51:30Z |
| Nicht rekonstruierbare Einträge klassifiziert | 0 NON_RECONSTRUCTABLE, 0 CONFLICTING |
| Keine nachträglichen Metadaten | eingehalten, kein Rewrite |
| Kein historischer Hash geändert | `bytes_unchanged: true` |
| V2-Grenze freigegeben | freigegeben am 24.10.2026 (Uzi): 2026-10-24T00:51:14.905971Z |
| Herkunft im V2-Bereich 100 % | 100 % (`prospective_complete_percent`) |
| Legacy-Einschränkung freigegeben | freigegeben am 24.10.2026 (Uzi): 3.301 PARTIAL_LEGACY bleiben unverändert |
| V2-B05 mindestens VERIFIED | VERIFIED, siehe `TIM_V2_BLOCKER_REGISTER.md` |

## Ergebnis des Inventars (24.10.2026)

Lauf auf dem Mac in `~/TIM-live` (Stand 59388dd), Ausgabe
`~/Library/Application Support/TIM/provenance/inventory-2026-10-24.json`:

| Wert | Anzahl |
|---|---|
| Einträge im Research-Cache | 3.302 |
| COMPLETE_PROSPECTIVE | 1 |
| PARTIAL_LEGACY | 3.301 |
| NON_RECONSTRUCTABLE | 0 |
| CONFLICTING | 0 |
| unlesbare Zeilen | 0 |
| Herkunft im V2-Bereich | 100 % |
| Dateien unter data/research unverändert | ja |

## Grenzen

- Das Audit (`src/research_ops/audit.py`) meldet die alten Einträge weiter als `MISSING_DOCUMENTATION`. Das ist
  gewollt: Alte Lücken bleiben sichtbar. Wie sie im V2-Bereich bewertet werden, entscheidet die
  Governance-Freigabe (HC-1.0), nicht dieses Skript.
- Das Inventar deckt nur den Research-Cache vollständig ab. Für andere JSON-Artefakte listet es die vorhandenen
  Felder auf, klassifiziert sie aber nicht.
- Die Prüfung von Bytes und Hashes macht das Inventar selbst (vorher/nachher). Eine getrennte Prüfung durch den Integrity Lead steht noch aus.
- Das eingefrorene Artefakt `artifacts/v2_readiness/v2_readiness_matrix_final.json` bleibt unverändert und zeigt weiter den alten Stand.
