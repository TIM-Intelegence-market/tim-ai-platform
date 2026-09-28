# TIM V4 Developer Manual — Kapitel 06

# Data Quality

Version: **0.1.0**
Status: **Konsistent für IST-Gate; SOLL-Statuswerte als [SPEZIFIKATION]**
Verbindlichkeit: **Ja**

Dieses Kapitel dokumentiert das Data Quality Gate von TIM: welche Prüfungen
existieren, welche fehlen, welche Tests vorhanden sind und welche Invarianten
gelten. Es trennt strikt zwischen **IMPLEMENTIERT**, **GEPLANT [SPEZIFIKATION]**
und **OFFENEN LÜCKEN**.

## 1. Zweck

Der Data Quality Gate ist die erste, deterministische Hürde jeder
Szenario-Analyse. Er entscheidet, ob Eingaben verwendbar sind, und stoppt die
Pipeline bei unzureichenden Daten. Der Gate erfindet niemals Daten: Fehlendes
oder Unlesbares wird berichtet und senkt die Konfidenz.

## 2. Reale Implementierung

Referenz: `src/orderflow_scenario/engines/data_quality.py`.

### 2.1 Eingaben (`DataQualityInputs`)

Frozen Dataclass mit Feldern: candles, trades, open_interest, price_now,
price_timestamp, structured, screenshot_confidence, estimated_prices,
venue_mixed, delta_definition_verified, open_interest_venue_aggregated,
time_unit_verified, spot_futures_separated, instrument, source_name,
data_latency_seconds, extra_notes.

Konstruktionsinvarianten (bei Verletzung → `ValueError`):

- `price_now > 0`, wenn gesetzt.
- `0 ≤ screenshot_confidence ≤ 1`, wenn gesetzt.
- `data_latency_seconds ≥ 0`, wenn gesetzt.

### 2.2 Gate-Konfiguration

`DataQualityGate(max_price_age_seconds=90.0, min_candles=20)`. Verletzung der
Parameter (≤ 0 bzw. < 1) → `ValueError`.

### 2.3 Prüfungen (IMPLEMENTIERT)

| Prüfung | Quelle | Wirkung |
|---|---|---|
| `candles(<min_candles)` | Anzahl Kerzen | missing |
| `naive_candle_timestamps` | tzinfo fehlt | missing |
| `trades` fehlen | keine Trades | missing |
| `naive_trade_timestamps` | tzinfo fehlt | missing |
| `price_now` fehlt | kein Preis | missing |
| `stale_price(<s>)` | Alter > max_price_age | problem |
| `mixed_venues` | venue_mixed | problem |
| `delta_definition_unverified` | nicht verifiziert | problem |
| `time_unit_unverified` | nicht verifiziert | problem |
| `spot_futures_not_separated` | nicht getrennt | problem |
| `screenshot_based_data` | structured=False | problem |
| `screenshot_confidence_too_low` | < 0.6 | problem |
| `open_interest_aggregated` | venue-aggregiert | estimated |
| `latency(<s>)` | Latenz > max_age | problem |
| `extra_notes` | zusätzliche Hinweise | problem |

### 2.4 Status-Logik (IST)

```text
wenn (len(missing) >= 3) ODER (price_now ist None)  → INSUFFICIENT_DATA
sonst wenn missing oder problems                     → PARTIAL
sonst                                                → PASS
```

### 2.5 Konfidenz (IST)

```text
base = 0.9
penalty = 0.12 * #missing + 0.08 * #problems + 0.02 * #estimated
confidence = clamp(base - penalty, 0, 1)
wenn nicht structured   → confidence *= 0.7
wenn keine trades       → confidence *= 0.5
```

### 2.6 Report (`DataQualityReport`)

Felder: `status`, `confidence`, `missing_fields`, `estimated_fields`,
`problems`, `schema`. Validierung in `domain.py`:

- `status ∈ {PASS, INSUFFICIENT_DATA, PARTIAL}` (siehe §6 — Lücke).
- `0 ≤ confidence ≤ 1`.
- `passed()` → `status == "PASS"`.

## 3. Fehlende Prüfungen (SOLL — [SPEZIFIKATION])

| Fehlende Prüfung | Ziel |
|---|---|
| `open_interest` Konsistenz (Zeit- und Venue-Vollständigkeit) | über `open_interest`-Felder hinaus, aktuell nur aggregiert markiert |
| Bewertung der Sequenzlücken in trades | Framework prüft Candle-Gaps, nicht Trade-Lücken im Gate |
| Typüberprüfung (unsupported input) | Gate hat keinen expliziten UNSUPPORTED_INPUT-Zustand |
| Verifikation der Instrument-Identität | Feld `instrument` ist optional, ohne Pflichtvalidierung |

## 4. Tests (IST)

Referenz: `tests/test_orderflow_scenario_data_quality.py` (11 Tests, derzeit
grün) und `tests/test_data_quality.py` (Framework).

| Test | Zweck |
|---|---|
| `test_gate_passes_on_complete_structured_input` | PASS bei vollständigen Daten |
| `test_gate_rejects_missing_price_as_insufficient` | INSUFFICIENT_DATA ohne Preis |
| `test_gate_marks_missing_trades_and_short_history` | PARTIAL bei fehlenden Trades |
| `test_stale_price_is_a_problem` | stale_price-Problem erzeugt |
| `test_screenshot_input_is_never_fully_trusted` | Screenshot: PARTIAL + estimated |
| `test_mixed_venues_and_unverified_delta_are_problems` | Flagge erzeugt Probleme |
| `test_confidence_stays_within_unit_bounds` | Konfidenz in [0,1] |
| `test_price_age_within_limit_passes` (param 0/1/1.5/2 min) | PASS vs. PARTIAL |

## 5. Invarianten

1. Der Gate erzeugt keine Daten (nie `invent`); er markiert nur.
2. `missing`-Struktur entspricht den im Report verlinkten Prüfungen.
3. Screenshot-Eingaben sind nie `PASS` (mindestens `PARTIAL`).
4. Ein fehlender `price_now` führt immer zu `INSUFFICIENT_DATA`.
5. Konfidenz ist immer in [0,1].

## 6. Statuswert-Lücke (IST vs. SOLL)

**GEWÜNSCHTE SOLL-Statuswerte** (aus der Zielarchitektur):
`PASS`, `DEGRADED`, `INSUFFICIENT_DATA`, `UNSUPPORTED_INPUT`, `INVALID`.

**IST-Statuswerte** (im Code): `PASS`, `PARTIAL`, `INSUFFICIENT_DATA`.

| SOLL | IST | Anmerkung |
|---|---|---|
| PASS | PASS | vorhanden |
| DEGRADED | PARTIAL | semantisch ähnlich, Name abweichend |
| INSUFFICIENT_DATA | INSUFFICIENT_DATA | vorhanden |
| UNSUPPORTED_INPUT | — | fehlt [SPEZIFIKATION] |
| INVALID | — | fehlt [SPEZIFIKATION] |

Konsequenz: `DataQualityReport.__post_init__` validiert `PARTIAL`, nicht
`DEGRADED`/`UNSUPPORTED_INPUT`/`INVALID`. Eine Umbenennung/Erweiterung ist eine
Breaking-Change am Report-Vertrag und benötigt einen dokumentierten
Schemawechsel (Kapitel 24) — nicht als Stille Anpassung.

## 7. Fehlerfälle

| Fall | Verhalten |
|---|---|
| Konstruktion ungültig | `ValueError` (Gatenparameter/Inputs) |
| ungenügende Daten | `INSUFFICIENT_DATA`, Pipeline stoppt |
| teilweise Daten | `PARTIAL`, Konfidenz-Abzug |
| Screenshot | nie vollvertraut; Confidence-Multiplikator 0.7 |

## 8. Bekannte Einschränkungen

- Kein `UNSUPPORTED_INPUT`-Zustand für unlesbare/unbekannte Eingaben.
- Lücke zwischen Gate-Status-Namen und Zielarchitektur (siehe §6).
- Open-Interest-Bewertung nur „aggregated“-Markierung, keine Vollständigkeit.

## 9. Offene Lücken (IST vs. SOLL)

| Bereich | IST | SOLL |
|---|---|---|
| Status-Menge | PASS/PARTIAL/INSUFFICIENT_DATA | +DEGRADED/UNSUPPORTED_INPUT/INVALID |
| Open-Interest | aggregiert markiert | vollständige Konsistenzprüfung |
| Trade-Lücken | im Gate nicht erkannt | Sequenzprüfung |

## 10. Roadmap [SPEZIFIKATION]

- Status-Modell erweitern (UNSUPPORTED_INPUT/INVALID) mit dokumentierter
  Schema-Migration.
- DEGRADED als formalen Zustand einführen und PARTIAL kompatibel abbilden.
- Open-Interest-Konsistenzprüfung und Trade-Sequenzprüfung im Gate ergänzen.
- Regressionstests für neue Statuswerte.

---

*Ende Kapitel 06.*