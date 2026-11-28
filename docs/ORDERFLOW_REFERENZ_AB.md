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

## A: Perp-Körbe as-of (kanonische Historie)

**Begriffe.** Jede Perp-Store-Fassung hat eine Schreibzeit `u` (`updated_at`) und den Zeitpunkt `s`, zu dem TIM sie
zuerst hielt: `s = max(now, u)`. Eine Fassung wird also nie vor ihrer Schreibzeit sichtbar (keine rückdatierte
Verfügbarkeit); eine Fassung ohne lesbares `updated_at` wird nicht vermerkt. Antwort bei `t` = Funktion allein der
Fassungen mit `s <= t`; Reihenfolge des Einlesens, Duplikate und alles mit `s > t` ändern sie nicht.

**Historie** (`live_state.PerpAsOf`). Je Fassung: ihre Breite (`bucket_size`, Status OK/MISSING/INVALID) und je
Korbstart `b` die Summe `(bid, ask)` über die Level-Zeilen (`math.fsum`, korrekt gerundet, reihenfolgefrei). Einträge
sind Mengen mit dem frühesten `s` je Inhalt.

**Breite bei `t`.** Die der neuesten Schreibzeit unter den Fassungen mit `s <= t`. Mehrere Breiten bei dieser
Schreibzeit: INCONSISTENT. Keine Fassung: NOT_AVAILABLE. Fehlend/ungültig: MISSING/INVALID. Über 900 s: TOO_WIDE.
In allen diesen Fällen kein Perp-Delta (Block „Bucket-Größe unbekannt“).

**Korb bei `t`.**

- MEHRDEUTIG, wenn die bis `t` gesehenen Fassungen, die `b` enthalten, mehr als eine Breite nennen, eine fehlende,
  ungültige oder zu breite Breite, eine unbrauchbare Zeile (kein Wert, NaN, negativ, bool) haben oder bei ihrer
  neuesten Schreibzeit verschiedene Werte. Derselbe Start unter anderer Breite ist ein anderer Korb; welcher gemeint
  ist, ist nicht entscheidbar. Ein Werte-Update unter kürzerer Breite verlegt das Korbende daher nie nach vorn.
- Sonst: Breite `w` = die eine Breite; geschlossen genau dann, wenn `b + w <= t`; Wert aus der neuesten Schreibzeit.

**Fenster.** 5m/15m summieren geschlossene Körbe mit `b >= t - Fenster - w` (unverändert gegenüber Runde 1). Liegt ein
mehrdeutiger Korb in Reichweite (`t - Fenster - r <= b < t`, `r` = größte genannte Breite, höchstens 900 s), ist das
Fenster UNKNOWN: `delta_5m`/`delta_15m`/`volume_15m` = `null`, `window_status` sagt welches. Nie eine Teilsumme.

**Metadaten** nur aus Information bis `t`: `buckets_open`, `buckets_ambiguous`, `buckets_revised` (mehr als ein Wert
bis `t`), `buckets_other_width`. Die Runde-1-Felder `buckets_unknown`/`buckets_revised_later` hingen von später
eingelesenen Fassungen ab und entfallen.

**Begrenzung ohne Antwortänderung.** `F` = neuestes `s` − 2 h. Zeilen, die mehr als 1800 s vor dem `s` ihrer Fassung
beginnen, werden nicht gehalten (sie liegen bei keinem `t >= s` in einem Fenster). Einträge mit `s <= F` werden auf das
verdichtet, was jede Antwort bei `t >= F` braucht (neueste Schreibzeit, Menge der Breiten und Werte); Körbe vor
`F − 1800 s` entfallen. Jeder Schnitt hängt nur von der Menge der Fassungen ab. `t < F`: HISTORY_GONE (Snapshots
laufen vorwärts, live tritt das nicht ein).

**Codex-Fälle #377 (27.11.).** A1: 12:00/300 s und 13:00/60 s (11:45 ask 2→9), beide zur Entscheidungszeit 12:00
eingelesen, in beiden Reihenfolgen: (0, 1). A2: 12:00:15/60 s ändert nur 11:56 ask 5→6: nicht mehr (6, 7), sondern
5m/15m UNKNOWN bei 12:00:15 und 12:01:01, in beiden Reihenfolgen; bei 12:00:10 die Mittagsantwort.

**Verträglichkeit.** `RevisionLog` (#381) bleibt unverändert und wird hier nicht mehr benutzt. Schema bleibt
`orderflow-lage/3`; Leser (`chart_verdict`, Schatten, Tagesbericht) vertragen `null` (`_num`, `.get`). Paket E liest
nur die Lage-Datei: `null` heißt „nicht belegt“, nie 0.

**Tests.** `tests/test_orderflow_live_state.py`: Orakel aus diesem Text (Schleifen über alle Fassungen, Fractions,
keine Verdichtung) gegen den Tracker in chronologischer, umgekehrter, gemischter Reihenfolge und mit Duplikaten
(Seed-Sweep + Hypothesis), Neustart mit gleicher Fassungsmenge, 4 h Live-Strom (Begrenzung, Antworten = Orakel bis
`F`), keine Rückdatierung, gleiche Schreibzeit mit verschiedenen Werten, unbrauchbare Zeilen, zu breite Körbe,
Codex A1/A2 wörtlich, gemeinsamer A+B-Snapshot durch JSON (gleicher `snapshot_hash` in beiden Reihenfolgen).
