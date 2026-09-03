# TIM V4 Developer Manual — Kapitel 04

# Coding Standard

Version: **0.1.0**
Status: **Konsistent (reflektiert TIM Constitution Band 2, Abschnitt Code Standards)**
Verbindlichkeit: **Ja**

Dieses Kapitel definiert die verbindlichen Schreib- und Strukturregeln für
allen Python-Code in TIM. Es ergänzt die Golden Rules aus Kapitel 00 durch
konkrete, prüfbare Anforderungen.

## 1. Ziel

Lesbare, wartbare, deterministische und reviewbare Codebasis sicherstellen.
Lesbarkeit hat Vorrang vor Cleverness. Kein Code ohne Tests (Golden Rule 1).

## 2. Grundprinzipien

- Klare, sprechende Namen.
- Kleine Funktionen (eine Aufgabe pro Funktion).
- Keine Magie: jede Konstante, jeder Schwellwert ist benannt.
- Keine versteckten Seiteneffekte.
- Keine globalen Zustände.
- Keine impliziten Abhängigkeiten.
- Kein Copy-Paste: wiederverwenden statt duplizieren.

## 3. Verbotene Praktiken

| Verbot | Begründung |
|---|---|
| Magic Numbers | unbenannte Schwellwerte sind nicht nachvollziehbar |
| Mutation globaler Objekte | bricht Replay und Determinismus |
| Silent Exception Catch | verbirgt Fehler |
| `type()`-Vergleiche | versteckte Typabhängigkeit |
| Bare `except:` | verschluckt Systemfehler |
| Tote Pfade | ungetestetes, unlesbares Verhalten |
| Mutables Default-Argument | klassische Quelle für Seiteneffekte |

## 4. Struktur und Schreibweise

- Paket: `src/<domaene>/`, Module klein und fokussiert.
- Dateien < 400 Zeilen bevorzugt; sonst aufteilen.
- Module imports: stdlib → third-party → project, leere Zeile dazwischen.
- Python-Konventionen nach PEP 8 mit Black-Kompatibilität.
- Typannotationen für alle öffentlichen Signaturen.

## 5. Determinismus-Konvention

- Keine Zufalls- oder Zeitabhängigkeit in reinen Berechnungsfunktionen.
- Zeitwerte werden als Parameter übergeben (Injektion), nie `datetime.now()`
  direkt in Engine-Logik.
- Jede Engine besitzt deterministische Eingabe- und Ausgabedatentypen
  (siehe Kapitel 24, 25).

Beispiel:

```python
def compute(data: MarketSnapshot, now: datetime) -> ScenarioResult:
    ...
```

## 6. Fehlerbehandlung

- Exceptions sind spezifisch und benannt.
- Fehlerbehandlung folgt: Stop → Diagnose → Dokumentation → Korrektur →
  Regressionstest (Kapitel 02, Abschnitt 10).
- Logging über `src/operational/logging.py` (siehe Kapitel 22).

## 7. Konventionen für Engines und Adapter

- Engines sind reine Funktionen oder stateless Klassen; Zustand nur via
  Konfiguration.
- Adapter normalisieren fremde Formate in kanonische Records (Kapitel 02).
- Der Screenshot-Adapter kennzeichnet abgeschätzte Werte explizit
  (`estimated=True`) und erfinden keine fehlenden Werte
  (siehe `src/orderflow_scenario/adapters/mmt_screenshot.py`).

## 8. Dokumentationsanforderung an Code

- Öffentliche Module: Docstring mit Zweck, Eingaben, Ausgaben, Invarianten.
- Komplexe Regeln: Verweis auf Fachkapitel, nicht Prosa im Code.
- Keine überflüssigen Kommentare; Code erklärt sich durch Namen.

## 9. Testanforderungen (Verweis)

- Unit-, Integration-, Schema-, Regression-, Replay-, Determinismus-, Hash-,
  Lineage-, Acceptance-Tests (Kapitel 25).
- Tests niemals abschwächen; keine `skip`-Missbrauch.

## 10. Akzeptanzkriterien

- [ ] Konformität zu Band 2 Abschnitt Code Standards verifiziert.
- [ ] Verbotene Praktiken sind als Negativtests abgedeckt (Kapitel 25).
- [ ] Determinismus-Konvention in Engines nachweisbar (Code-Referenz).

---

*Ende Kapitel 04.*