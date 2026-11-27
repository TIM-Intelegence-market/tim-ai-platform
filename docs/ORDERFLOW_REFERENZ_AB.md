# Referenzsemantik Orderflow A + B (Runde 2, 27.11.2026)

Koordination: COORD-REF-AB-62de6bd-6a9a8fb-20261127 (#372). Diese Datei legt fest, was der Code tun soll; die Tests
prüfen den Code gegen unabhängige Orakel aus dieser Beschreibung, nicht gegen die Implementierung.

## B: Handelsseite bekannt (Policy-Kette)

**Regel.** Je Fenster mit `total = known + unknown > 0` gilt die Seite als belegt genau dann, wenn
`20 * unknown <= total` (Anteil bekannter Seite >= 95 %, Gleichheit besteht). Gerechnet wird rational exakt.

**Kette.**

1. *Eingabe.* Eine Trade-Menge ist ein Float aus dem Feed. Sie wird als die Dezimalzahl gelesen, als die sie
   geschrieben wurde: `Decimal(repr(float(q)))` (`live_state._exact`). Seite: `buyer_is_maker` True = Verkauf,
   False = Kauf, alles andere = unbekannt (kein bool ist keine Seite).
2. *Aggregation.* `known` und `unknown` je Fenster sind Summen dieser Dezimalzahlen (`Decimal`, exakt bei den
   vorkommenden Stellenzahlen; Reihenfolge der Trades ändert die Summe nicht).
3. *Lage/JSON.* Jedes Fenster trägt zusätzlich `side_evidence = {"schema": "side-evidence/1", "known": "<str>",
   "unknown": "<str>"}`: einfache Dezimalstrings (Ziffern, optional ein Punkt mit Ziffern; kein Vorzeichen, kein
   Exponent, keine Leerzeichen). Strings überstehen `json.dumps`/`json.loads` unverändert. Die Felder `volume`,
   `unknown_volume`, `buy_share`, `delta` bleiben als Float für Anzeige und Altleser; die Policy liest sie nicht.
4. *Consumer.* `orderflow_shadow.known_side` liest nur `side_evidence` und rechnet mit `Fraction(Decimal(s))`.
   `lage_view` speichert das Ergebnis (`side_ok`, `side_status`, `known_share` nur Anzeige); `gate` und
   `should_exit` folgen nur `side_ok`.

**Evidenzzustände je Fenster.**

| Zustand | Wann |
|---|---|
| MISSING | Block fehlt oder `null`; `known` oder `unknown` fehlt oder `null` (z. B. Lage vor diesem Schema) |
| INVALID | Fenster kein Mapping; Block kein Mapping; anderes `schema`; Betrag kein einfacher Dezimalstring (Float, int, bool, `"1e-5"`, `"-1"`, `" 1"`, `"nan"`, Unicode-Ziffern …) |
| VALUE | beide Beträge gültig |

Gesamtstatus: INVALID vor MISSING vor EMPTY/BELOW/OK. MISSING auch, wenn ein vom Modell gebrauchtes Fenster
(`REQUIRED_WINDOWS`) fehlt oder `windows` fehlt; `windows` kein Mapping = INVALID. EMPTY: kein Fenster hat Volumen.
Nur OK bestätigt eine Seite; jeder andere Status ergibt im Schatten UNBEKANNT und keinen Ausstieg.

**Kompatibilität.** Additiv: `SCHEMA_VERSION` bleibt `orderflow-lage/2`, neue Unterstruktur mit eigener
Schema-Kennung `side-evidence/1`. Alte Lagen ohne Block sind MISSING (nie bestätigt). Gespeicherte Views älterer
Pläne werden wie bisher über `side_unknown` gelesen.

**Codex-Fall #376 (27.11.).** known `0.0001332602127840482`, unknown `0.000007013695409686748`: total
`0.000140273908193734948` < 20 × unknown `0.000140273908193734960` → BELOW, UNBEKANNT, kein Ausstieg, auch nach
JSON-Rundreise der Lage und der View. Mit known `…483` statt `…482` → OK.

**Tests.** `tests/test_orderflow_known_side_properties.py` (eigener String-Parser + Ganzzahl-Orakel, Grenzfälle eine
Einheit in der letzten Stelle bei 0–30 Nachkommastellen, Junk-Strings, metamorphe Wegnahme, Anzeige-Floats ohne
Wirkung, Hypothesis), `tests/test_orderflow_side_policy_e2e.py` (echter Tracker → JSON → View, Codex-Fall, Patch
ungültiger Evidenz, Reihenfolge- und Skalierungsinvarianz), alte Negativtests über `tests/_side_evidence.py`.
