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
| Vorhandene Felder inventarisiert | per Skript, Lauf auf dem Mac nach Deploy |
| Fehlende Felder inventarisiert | per Skript |
| Anzahl betroffener Einträge zu festem Stichtag | per Skript (`--cutoff`) |
| Nicht rekonstruierbare Einträge klassifiziert | per Skript |
| Keine nachträglichen Metadaten | eingehalten, kein Rewrite |
| Kein historischer Hash geändert | `bytes_unchanged` im Inventar |
| V2-Grenze freigegeben | **offen: Freigabe durch Research Lead / Governance Lead** |
| Herkunft im V2-Bereich 100 % | messbar ab Deploy (`prospective_complete_percent`) |
| Legacy-Einschränkung freigegeben | **offen: Freigabe durch einen Menschen** |
| V2-B05 mindestens VERIFIED | **offen** |

## Grenzen

- Das Audit (`src/research_ops/audit.py`) meldet die alten Einträge weiter als `MISSING_DOCUMENTATION`. Das ist
  gewollt: Alte Lücken bleiben sichtbar. Wie sie im V2-Bereich bewertet werden, entscheidet die
  Governance-Freigabe (HC-1.0), nicht dieses Skript.
- Das Inventar deckt nur den Research-Cache vollständig ab. Für andere JSON-Artefakte listet es die vorhandenen
  Felder auf, klassifiziert sie aber nicht.
- V2-B05 bleibt OPEN, bis ein Mensch die Grenze und die Einschränkung der Alt-Historie freigibt.
