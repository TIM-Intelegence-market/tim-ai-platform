# Deflated Sharpe für S7b und OF2 (11.11.2026)

Zusatzauswertung, keine Regel: ändert kein Urteil (wie SPA/StepM, PROTOKOLL Änderungsprotokoll 2026-10-23).
Anlass: Studien-Ideen 11.11., Punkt 5 („Was bleibt nach über 25 Fragen übrig?“), Uzis „go“ 11.11. 20:45 Ortszeit.

## Methode

`src/research_lab/stats/deflated.py` (Tests `tests/test_research_lab_deflated.py`, rechnet das Zahlenbeispiel aus
Bailey & López de Prado 2014 nach: DSR 0,9004).

- Sharpe je Trade (Netto-R, nicht annualisiert), Schiefe und Kurtosis aus denselben Trades.
- PSR(0): Wahrscheinlichkeit, dass der wahre Sharpe > 0 ist, **ohne** Korrektur für die Zahl der Versuche.
- DSR: Wahrscheinlichkeit, dass der wahre Sharpe über dem Bestwert liegt, den N Versuche ohne Vorteil im Mittel
  durch Glück erreichen (SR0). Varianz der Versuchs-Sharpes: Nullfall 1/(n−1), weil TIM nicht von jedem Versuch einen
  Sharpe hat.
- Übliche Lesart: DSR ≥ 0,95 gilt als belastbar.

## Zahl der Versuche N

| Teil | Versuche | Quelle |
|---|---:|---|
| Register (Holdout-Familie) | 58 | `REGISTER.jsonl`, Hash-Kette geprüft |
| Makro-Filter F1–F5 auf S7b | 5 | `studien/S7B_MAKRO_FILTER.md` |
| OF2 | 1 | `studien/OF2_ORDERFLOW_ENGINE_PRAEREGISTRIERUNG.md` |
| **Summe (Hauptwert)** | **64** | |

Nicht gezählt, weil ohne Sharpe-Frage oder ohne bekannte Versuchszahl: S8, S13–S23 außerhalb des Registers, die
OFX-Dauersuche auf PS5/PS4. Deshalb stehen auch N = 100 und N = 200 in der Tabelle. Die Registervarianten hängen
untereinander zusammen (z. B. S7 und S7b), die wirksame Zahl ist also eher kleiner als 64; die OFX-Suche wirkt in die
andere Richtung. Die Wahrheit liegt vermutlich zwischen den Spalten.

## Ergebnis

Daten: S7b-Tradeliste vom Mac (`s7b_train_2026-10-26T1305Z_trades.json`, Lauf 26.10., Training 2020–2022,
Validierung 2023–2024) und OF2-Trainingstrades (`of2_training_of_trades.json`, 2020–2022). Kein Holdout berührt.
Die Dateien liegen nicht im Repo; SHA-256 zum Nachprüfen:

- `s7b_train_2026-10-26T1305Z_trades.json` (Mac, Worktree `s7-gate/reports/`):
  `fa45d740da405a2fc96737a1a61d3fde151d81f68695f1951587ae0e85b88b26`
- `of2_training_of_trades.json` (Mac, `bitunix-check/`):
  `8bfcb8da8ead6e9aa5aeb4d9b525fd24350f0afd9c420d3b40dc1f93b67524ee`

| Reihe | n | E[R] | Sharpe/Trade | Schiefe | Kurtosis | PSR(0) | DSR N=58 | **N=64** | N=100 | N=200 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| S7b-D20-T3 Training | 292 | +0,227 | 0,131 | +0,74 | 1,73 | 0,991 | 0,46 | **0,45** | 0,38 | 0,29 |
| S7b-D20-T3 Validierung | 207 | +0,272 | 0,159 | +0,72 | 1,72 | 0,992 | 0,48 | **0,46** | 0,40 | 0,30 |
| S7b-D20-T3 beide | 499 | +0,246 | 0,143 | +0,73 | 1,72 | 1,000 | 0,82 | **0,81** | 0,76 | 0,67 |
| S7b-D20-T4 Training | 266 | +0,265 | 0,137 | +1,04 | 2,39 | 0,992 | 0,46 | **0,44** | 0,37 | 0,28 |
| S7b-D20-T4 Validierung | 189 | +0,251 | 0,131 | +1,09 | 2,54 | 0,973 | 0,28 | **0,27** | 0,21 | 0,15 |
| S7b-D20-T4 beide | 455 | +0,259 | 0,134 | +1,06 | 2,45 | 0,999 | 0,72 | **0,70** | 0,64 | 0,54 |
| OF2 Training | 56 | +0,269 | 0,145 | +2,54 | 12,47 | 0,902 | 0,07 | **0,06** | 0,04 | 0,02 |

## Lesart

- **S7b-D20-T3** ist die stärkste Reihe in TIM. Ohne Korrektur ist der Vorteil klar (PSR ≈ 1). Nach der Korrektur für
  64 Versuche bleibt über 2020–2024 zusammen eine Wahrscheinlichkeit von etwa 0,8, dass der Vorteil echt ist. Das ist
  ein ernsthafter Hinweis, aber kein Beleg (Schwelle 0,95). Training oder Validierung allein reichen nicht.
- **S7b-D20-T4** liegt darunter, vor allem in der Validierung (0,27).
- **OF2:** Nach der Korrektur bleibt praktisch nichts übrig (0,06). 56 Trades mit einem großen Ausreißer (Kurtosis 12)
  sind zu wenig. Das deckt sich mit dem Urteil „nicht prüfbar“. Der Zufallsvergleich (p = 0,006) misst etwas anderes
  (gegen zufällige Einstiege, ohne Korrektur für Versuche).
- Folge: Die einzige Kandidatin mit realistischer Chance ist S7b-D20-T3. Ein Holdout-Lauf könnte sie bestätigen,
  das bleibt Uzis Entscheidung (Studien-Ideen Punkt 2). Neue Varianten auf 2020–2024 würden N weiter erhöhen und
  den Wert senken.

## Grenzen

- Sharpe je Trade, nicht je Tag: Überlappende Positionen gibt es in S7b nicht (Positionsgrenze 1), bei OF2 höchstens
  eine je Tag.
- Die Nullvarianz ist eine Näherung. Mit den Sharpes aller Versuche (Papier-Variante) wäre SR0 vermutlich größer,
  weil viele Versuche deutlich negativ waren und so die Streuung erhöhen.
- Die Versuchszahl außerhalb des Registers ist geschätzt, siehe oben.
