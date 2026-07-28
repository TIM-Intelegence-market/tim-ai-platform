# TIM OUTPUT_HASH_MISMATCH Root Cause Report

## Executive Summary

Untersuchungsgegenstand war der persistierte Fehler:

`OUTPUT_HASH_MISMATCH` in `data/research/status/tim_v1_readiness.json`.

Die Ursache wurde eindeutig und reproduzierbar bestimmt. Es liegt **keine
nichtdeterministische Ausgabe** und **keine Beschädigung wissenschaftlicher
Ergebnisse** vor. Zwei Komponenten verwenden dasselbe Feld `output_hash` mit
unterschiedlichen Hash-Domänen:

1. Die Research Insights Engine berechnet `output_hash` als SHA-256 über das
   kanonisch serialisierte Insights-Ergebnis ohne das Feld `output_hash`.
2. Snapshot und Readiness übernehmen diesen Hash unverändert als Referenz auf
   das vorgelagerte Insights-Ergebnis.
3. Der Research Audit behandelt jedes beliebige Top-Level-Feld `output_hash`
   dagegen als Selbst-Hash des gerade geprüften JSON-Artefakts. Er entfernt
   `output_hash` aus dem Readiness-Dokument und hasht den gesamten übrigen
   Readiness-Inhalt.

Der Audit vergleicht daher Hashes zweier verschiedener Inhalte. Der Vergleich
muss scheitern, obwohl beide beteiligten Inhalte deterministisch sind.

**Klassifikation: B — Serialisierung.** Präziser: falscher
Serialisierungs-/Hash-Eingabebereich aufgrund einer nicht eindeutigen
Feldsemantik. Es handelt sich nicht um Unterschiede bei JSON-Parametern,
Whitespace oder Encoding.

## Untersuchungsgrenze

- TIM Core 1.0 wurde nicht verändert.
- Datenbank, Schema, Konfiguration, Regeln, Metriken, Validierung, Replay und
  Snapshots wurden nicht verändert.
- Es wurden keine Artefakte neu erzeugt oder überschrieben.
- Alle Reproduktionsläufe verwendeten unveränderliche, eingelesene Bytes.
- Diese Datei ist ausschließlich der angeforderte Untersuchungsbericht.

## Pipeline und Fehlerstelle

| Stufe | Verhalten | Ergebnis |
|---|---|---|
| Insights Engine | Kanonisiert das Insights-Ergebnis und setzt danach `output_hash` | Hashvertrag konsistent |
| Monthly Snapshot | Übernimmt `insights.output_hash` nach `scientific_health.output_hash` | Referenz unverändert |
| Readiness Builder | Übernimmt `scientific_health.output_hash` als Top-Level-`output_hash` | Referenz unverändert |
| Readiness Artifact | Besitzt zusätzlich einen separaten, gültigen `artifact_hash` | Selbstintegrität konsistent |
| Research Audit | Entfernt `output_hash` und hasht den übrigen Readiness-Inhalt | Falsche Hash-Domäne |
| Audit Result | Vergleicht Readiness-Selbsthash mit Insights-Output-Hash | `OUTPUT_HASH_MISMATCH` |

Die Abweichung entsteht erstmals in
`ResearchAuditEngine._validate_declared_hash()`, nicht bei der Erzeugung der
Insights, des Snapshots oder der Readiness-Datei.

## Verifizierte Hash-Verträge

### Insights Output Hash

- Algorithmus: SHA-256
- Eingabe: kanonisches Insights-Dictionary vor Einfügen von `output_hash`
- JSON-Parameter:
  - `sort_keys=True`
  - `separators=(",", ":")`
  - `ensure_ascii=False`
  - `default=str`
- Aktuelle unabhängige Live-Prüfung:
  - deklarierter Hash:
    `a452c40253584ab562210f58045cc230a961aa40a8b7558700f0e6845c1ef6db`
  - neu berechneter Hash:
    `a452c40253584ab562210f58045cc230a961aa40a8b7558700f0e6845c1ef6db`
  - Ergebnis: **MATCH**

### Readiness Artifact Hash

- Algorithmus: SHA-256
- Eingabe: kanonisches Readiness-Dictionary vor Einfügen von `artifact_hash`
- deklarierter Hash:
  `c67239f15325e430eab6d3d8defc0323435f6b34568515acf247c169839c6cb7`
- neu berechneter Hash:
  `c67239f15325e430eab6d3d8defc0323435f6b34568515acf247c169839c6cb7`
- Ergebnis: **MATCH**

### Vom Audit fälschlich erwarteter Readiness Output Hash

- im Readiness-Artefakt deklarierter, aus Insights stammender Hash:
  `00f7c5ab0e458063bd105cbd98cd40c3c4ad2ff76b9ed3026a192ac972d61b31`
- vom Audit über Readiness ohne `output_hash` berechneter Hash:
  `00e3e9cedc9b70bff65e396705cd5ab83d75ea8ca9977e8bcf9112ce8728cce5`
- Ergebnis: **MISMATCH**, weil die Hash-Eingaben nicht identisch sind.

## Zehn identische Reproduktionsläufe

Eingefrorene Eingabe:

- Readiness-Datei SHA-256:
  `7b682c57521f766c90e18900e490892d0faec2def4e3dbd65343e8380ab2ef6a`
- Dataset Hash:
  `915ea39fa265eb78ebe3589e1d1024ab61426e679f1aa4d5118fe011cc38b9c0`
- Replay-Datei SHA-256:
  `2eb9d872d43e5ec25255b49bcee72ceb41a41ee2eea0cd9b4d9051947cd4db8e`
- Snapshot-Datei SHA-256:
  `81fb9617b01ddd2f9dcf6651a0a433b8a9641052d6152d9c4541344b0aa0ada3`

| Run ID | Input | Dataset | Declared Output | Audit-Recompute | Replay | Artifact valid |
|---|---|---|---|---|---|---|
| RUN-01 | identisch | identisch | identisch | identisch | identisch | ja |
| RUN-02 | identisch | identisch | identisch | identisch | identisch | ja |
| RUN-03 | identisch | identisch | identisch | identisch | identisch | ja |
| RUN-04 | identisch | identisch | identisch | identisch | identisch | ja |
| RUN-05 | identisch | identisch | identisch | identisch | identisch | ja |
| RUN-06 | identisch | identisch | identisch | identisch | identisch | ja |
| RUN-07 | identisch | identisch | identisch | identisch | identisch | ja |
| RUN-08 | identisch | identisch | identisch | identisch | identisch | ja |
| RUN-09 | identisch | identisch | identisch | identisch | identisch | ja |
| RUN-10 | identisch | identisch | identisch | identisch | identisch | ja |

Anzahl unterschiedlicher Werte über alle zehn Läufe:

- Input Hash: 1
- Dataset Hash: 1
- deklarierter Output Hash: 1
- vom Audit berechneter Output Hash: 1
- Replay Hash: 1
- Snapshot-Dateihash: 1
- deklarierter Artifact Hash: 1
- neu berechneter Artifact Hash: 1

Der Fehler ist somit **vollständig deterministisch reproduzierbar**.

## Byte- und Serialisierungsprüfung

Alle Formate wurden aus derselben eingefrorenen Eingabe jeweils zehnmal
erzeugt.

| Format | Unterschiedliche Hashes | SHA-256 des ersten Laufs | Ergebnis |
|---|---:|---|---|
| JSON, pretty | 1 | `7b682c57521f766c90e18900e490892d0faec2def4e3dbd65343e8380ab2ef6a` | stabil |
| JSON, compact | 1 | `b34afbd724c61519c2142ac332ea961455380f319238bf7c10eb46368807839f` | stabil |
| CSV | 1 | `95ee9973bce596d2e21ef46b1fde1bfded0077943654e9b8b30f6287f18ce63e` | stabil |
| Markdown | 1 | `5c0079c0a5e3321c2a04621baf9208958d7cf054ea3c5f39ef860e6c74f2a8d2` | stabil |

Zusätzliche Ergebnisse:

- Encoding: gültiges UTF-8; Byte-Roundtrip identisch.
- Zeilenenden: erzeugte Formate verwenden LF.
- Whitespace und CRLF verändern erwartungsgemäß den **Dateibytehash**.
- Nach JSON-Parsing und kanonischer Neu-Serialisierung sind Pretty- und
  Compact-JSON identisch.
- Das aktuelle Testobjekt enthält keine Nicht-ASCII-Zeichen; deshalb ergaben
  `ensure_ascii=True` und `ensure_ascii=False` hier identische Bytes.
- Zehn zufällig veränderte Dictionary-Einfügereihenfolgen ergaben wegen
  `sort_keys=True` genau einen kanonischen Hash.
- Der Fehlerhash entspricht keiner beobachteten Variation von Whitespace,
  Zeilenende oder Encoding, sondern ausschließlich dem anderen Hash-
  Eingabebereich.

## Prüfung der Hypothesen

| Hypothese | Test | Ergebnis |
|---|---|---|
| Nichtdeterministische Listen | Insights sortiert Quelllisten, Versionsgruppen, Exclusions, Evidenzkombinationen und zeitliche Verteilungen deterministisch; 10 Replay-Testserien identisch | ausgeschlossen |
| Dictionary-Reihenfolge | 10 zufällige Einfügereihenfolgen, kanonisches JSON mit `sort_keys=True` | ausgeschlossen |
| Dateisystemreihenfolge | Audit sortiert alle `rglob`-Pfade vor Verarbeitung; Fehler tritt bei direkter Prüfung einer einzelnen Datei auf | ausgeschlossen |
| Datenbankreihenfolge | Mismatch entsteht nach Persistenz beim Audit einer bestehenden JSON-Datei; keine DB-Abfrage liegt auf diesem Vergleichspfad | ausgeschlossen |
| JSON-Whitespace/Indent | Pretty/compact unterscheiden sich byteweise, sind kanonisch aber identisch; Audit nutzt compact canonical JSON | ausgeschlossen |
| Encoding/Unicode | UTF-8-Roundtrip und `ensure_ascii` geprüft | ausgeschlossen |
| Zeilenenden | LF/CRLF verändern nur Dateihash; Audit hasht geparstes Objekt | ausgeschlossen |
| Zeitstempel | Alle zehn Läufe verwendeten dieselben gespeicherten Zeitstempel und ergaben denselben Mismatch; kein `now()` im Hashprüfer | ausgeschlossen |
| Floating Point | Float und Decimal können allgemein unterschiedliche Hashes erzeugen; die Readiness-Hashwerte sind jedoch Strings/Integers und der konkrete Mismatch bleibt ohne numerische Konvertierung identisch | ausgeschlossen |
| Threads | 10 parallele Thread-Hashes, 1 eindeutiger Wert | ausgeschlossen |
| Async | 10 parallele Async/Thread-Aufgaben, 1 eindeutiger Wert | ausgeschlossen |
| Multiprocessing | 10 getrennte Python-Prozesse, 1 eindeutiger Wert | ausgeschlossen |
| Python-Version | Python 3.9.6 und 3.14.6 berechnen denselben Audit-Recompute-Hash | ausgeschlossen |
| Bibliotheksversion | Hash- und JSON-Pfad verwendet ausschließlich Standardbibliothek; gleiche Eingabe unter beiden installierten Python-Versionen identisch | ausgeschlossen |
| Betriebssystem | Reproduktion erfolgte auf macOS 26.5.1 ARM64; der geprüfte Pfad verwendet nur geparstes JSON und SHA-256. Kein OS-abhängiger Wert liegt auf dem Vergleichspfad. Andere Betriebssysteme waren lokal nicht verfügbar und wurden daher nicht behauptet getestet. | kein Hinweis auf Beteiligung |
| Replay | 10 vollständige Serien der relevanten Replay-, Export-, Readiness- und Snapshot-Tests: jeweils 22/22 PASS | ausgeschlossen |

## Testmatrix

| Test | Wiederholungen | Resultat |
|---|---:|---|
| Eingefrorene Hash-Reproduktion | 10 | identisch, Mismatch jedes Mal |
| Separate Prozesse | 10 | identischer Dateihash |
| Research Insights und Readiness Replay-Tests | 10 Serien | 220/220 Einzeltests PASS |
| JSON-Export | 10 | byteidentisch |
| CSV-Export | 10 | byteidentisch |
| Markdown-Export | 10 | byteidentisch |
| Dictionary-Reihenfolge | 10 | identischer kanonischer Hash |
| Thread-Hashing | 10 | identisch |
| Async-Hashing | 10 | identisch |
| Python-Versionen | 3 Aufrufe, 2 Versionen | identischer Audit-Recompute-Hash |

Ein erster Prozess-Pool-Harness aus einem Standard-Eingabeskript konnte unter
Python 3.14/macOS nicht gestartet werden, weil `multiprocessing` für
`<stdin>` keinen importierbaren Hauptdateipfad besitzt. Dieser Harnessfehler
trat vor jeder TIM-Berechnung auf. Die Parallelismushypothese wurde danach mit
zehn echten getrennten Python-Prozessen erfolgreich geprüft.

## Evidence im Quelltext

1. `src/insights/engine.py`, Zeile 357:
   `result["output_hash"] = _hash(result)`
2. `src/research_ops/snapshot.py`, Zeile 47:
   Snapshot übernimmt `insights.get("output_hash")` als
   `scientific_health.output_hash`.
3. `scripts/research_infrastructure_review.py`, Zeile 58:
   Readiness übernimmt `health.get("output_hash")` als Top-Level-Feld.
4. `scripts/research_infrastructure_review.py`, Zeile 59:
   Readiness erzeugt separat einen gültigen `artifact_hash`.
5. `src/research_ops/audit.py`, Zeilen 149–152:
   Der Audit entfernt jedes Top-Level-`output_hash` und erwartet, dass der
   verbleibende Inhalt genau diesen Hash ergibt.

Diese fünf Stellen bilden eine vollständige, geschlossene Beweiskette.

## Root Cause

**Root Cause ist eine Hash-Domänen-Kollision im Artefaktvertrag.**

`tim_v1_readiness.json.output_hash` bezeichnet den Output Hash der
vorgelagerten Insights-Ausgabe. Der Audit besitzt jedoch keine Feld- oder
Artefakttyp-spezifische Semantik und interpretiert denselben Feldnamen als
Selbst-Hash des Readiness-Artefakts.

Formal:

`SHA256(canonical(insights_without_output_hash))`

wird verglichen mit:

`SHA256(canonical(readiness_without_output_hash))`

Da `insights_without_output_hash` und `readiness_without_output_hash`
verschiedene Dokumente sind, sind unterschiedliche Hashes korrekt und
deterministisch.

## Risikoanalyse

### Datenintegrität

**Nicht betroffen durch diesen Mismatch.** Der persistierte Readiness-
`artifact_hash` ist gültig, der aktuelle Insights-`output_hash` ist gültig und
die geprüften Dataset-/Replay-/Snapshot-Hashes waren in zehn Läufen stabil.

### Wissenschaftliche Resultate

**Inhaltlich nicht betroffen durch diesen Mismatch.** Es wurde keine
Abweichung in Statistiken, Outcomes, Cases oder Exporten gefunden.

### Governance und Freigabe

**Betroffen.** Der Audit erzeugt einen reproduzierbaren False Positive und
setzt dadurch Audit/Quality/Scientific Readiness auf einen Fehlerzustand.
Solange der Hashvertrag nicht formal geklärt ist, ist ein GO weiterhin nicht
zulässig. Unabhängige bestehende Blocker wie Coverage und DATA_GAPs werden
durch diese Untersuchung weder bestätigt noch aufgehoben.

### Priorität

P0 für den wissenschaftlichen Freigabeprozess, nicht für die Integrität der
persistierten Marktdaten.

## Reproduktionsschritte

1. `data/research/status/tim_v1_readiness.json` als Bytes einlesen.
2. JSON parsen.
3. Den gespeicherten `output_hash` sichern und aus einer Kopie entfernen.
4. Die Kopie mit
   `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False,
   default=str)` serialisieren.
5. SHA-256 über die UTF-8-Bytes bilden.
6. Der berechnete Wert ist reproduzierbar
   `00e3e9...2e5`; der gespeicherte Wert ist
   `00f7c5...1b31`.
7. Den `artifact_hash` stattdessen entfernen und denselben Vorgang
   wiederholen. Der berechnete Wert stimmt exakt mit
   `c67239...6cb7` überein.
8. Das aktuelle Insights-Ergebnis abrufen, dort `output_hash` entfernen und
   kanonisch hashen. Deklarierter und berechneter Insights-Hash stimmen
   überein.

## Empfehlung

Keine Korrektur wurde vorgenommen.

Für einen später ausdrücklich freigegebenen Bugfix sollte zuerst ein
artefakttyp-spezifischer Hashvertrag beschlossen werden. Er muss eindeutig
zwischen einem Selbstintegritätshash und einer Referenz auf den Output einer
vorgelagerten Komponente unterscheiden. Anschließend muss ein adversarialer
Regressionstest exakt den hier dokumentierten False Positive abdecken.

Bis dahin:

- `OUTPUT_HASH_MISMATCH` nicht als Beweis beschädigter Forschungsdaten
  interpretieren;
- den Status dennoch nicht manuell auf PASS setzen;
- den dokumentierten NO-GO-Status beibehalten;
- keine historischen Artefakte verändern.

## Klassifikation

**B — Serialisierung**

## STATUS

**P0 INVESTIGATION COMPLETE**
