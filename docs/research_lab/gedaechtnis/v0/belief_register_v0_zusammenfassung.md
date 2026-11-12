# Überzeugungsregister v0 – Zusammenfassung (P0, 12.11.2026)

Die Daten liegen in `belief_register_v0.jsonl` im selben Ordner, eine Aussage pro Zeile. Für die Inventur habe ich nur gelesen und nichts am Live-System geändert.

## Bestand

| Herkunft | Aussagen |
|---|---|
| Live-Regeln im Code (Chart-Urteil, Grade, Orderflow, Kosten, Ausführung, Journal, Reflexion) | 64 |
| Eigene Forschung (Register R4, S1–S27, K1, OF2/OFX, KI, Daten) | 99 |
| Externe Quellen (Bootcamp/Mega-Orderflow, GoatHub, Reels, Quant Finance, Telegram) | 90 |
| **Gesamt** | **253** |

Jede Zeile enthält die Aussage, die Herkunft und die Stelle im Code, falls sie live genutzt wird. Dazu kommen der Evidenzstatus, der Beleg, Verknüpfungen zu Studien und ein Konflikt-Text.

## Abgleich (P1)

| Gruppe | Anzahl | Bedeutung |
|---|---|---|
| 1 live genutzt **und widerlegt** | 7 | dringend |
| 2 live genutzt, ungeprüft oder nur schwach | 66 | Prüfliste |
| 3 belegt/schwach, aber nicht genutzt | 42 | Wissen, das noch nicht genutzt wird |
| 4 widerlegt, nicht genutzt | 43 | Negativwissen, dient als Filter gegen Wiederholungen |
| 5 ungeprüft, nicht genutzt | 95 | Ideenvorrat |
| 0 live genutzt und belegt | **0** | – |

**Kernbefund:** Keine einzige Live-Regel stützt sich auf eine bestandene Studie. `RULE_EQUIVALENCES` ist leer. Nach Kosten belegt ist bisher kein Handelsvorteil.

### Gruppe 1: live genutzt, aber widerlegt
1. **Chart-Urteil R1** (Einstieg am 1D VAL/VAH): Laut S22 trennt die Regel nicht (−0,28 R gegen −0,27 R).
2. **Chart-Urteil R5** (1h-Trendlinie): Laut S22 wirkt die Regel verkehrt herum, sowohl im Training als auch in der Validierung.
3. **Chart-Urteil gesamt** (NEHMEN ab +2): S22 nicht bestanden. Nach Kosten sind alle Gruppen negativ.
4. **Funding-Schwellen als Signal** (LIVE-OF-12): R4, S16 und der S7b-Filter haben das widerlegt. Trotzdem fließen die Schwellen live in den Score ein.
5. **Broncx-Einfluss auf den Score** (±0,08 und eigene Szenarien): Die Broncx-Muster sind in R4 widerlegt.
6. **GARCH-Größengewichtung**: Die Prognose ist belegt (S15), der Nutzen für die Positionsgröße aber nicht (S25 nicht bestanden).
7. **BOS als Einstiegssignal** (extern; TIMs SICHERN-Logik nutzt BOS): R4 hat das widerlegt.

## Vorschlag: Top 10 für die erste Prüfwoche (P2)

Die Reihenfolge ergibt sich aus Einfluss auf Live-Entscheidungen mal Unsicherheit, wobei billig zu prüfende Punkte vorgezogen sind.

| # | Was | Warum | Aufwand |
|---|---|---|---|
| 1 | **S19-Ergebnis ins Repo holen** | Prüft genau die Live-Schwellen für Footprint, Imbalance und Absorption. Das Ergebnis liegt nur auf der PS5. | sehr klein |
| 2 | **R1 und R5 aus dem Chart-Urteil nehmen oder als widerlegt kennzeichnen** | S22 belegt das bereits | Entscheidung, kein Test |
| 3 | **Funding- und Broncx-Zuschläge im Szenario-Score** | Widerlegte Signale verschieben live den Score | Entscheidung, dann Replay |
| 4 | **Kostensätze vereinheitlichen** | Es gibt vier verschiedene Modelle (5+3 bp, 6/2/2 bp, 5 bp, 6+3 bp). Die Kosten bestimmen das ganze Netto-R. | klein |
| 5 | **Sichern/Trail-Logik** (be_cost/1, verdict/1, Swing-Trail) auf Historie gegen feste Ziele | Sie bestimmt das Netto-R aller Journale und ist nie getestet | mittel (Replay mit Standard-Trades wie S22) |
| 6 | **Szenario-Score kalibrieren**: Steigt die Trefferquote mit dem Score? | Grade A/B/C hängen daran, der Code nennt den Score selbst „unkalibriert“ | mittel |
| 7 | **Marktzustand als Filter** (AGAINST_TREND) | Die Papier-Rückschau spricht dagegen (+2,72 R gestrichen). Auf der Historie prüfen. | mittel |
| 8 | **Kostenlimit 0,25 R** gegen 0,15 R und ohne Limit | Das Limit filtert live Pläne, die Wahl der Grenze ist ungeprüft | klein |
| 9 | **Level-Pläne (level/1)** | 8 Trades, −17,7 R, danach keine Pläne mehr. Klären, ob sie noch erzeugt werden. | klein |
| 10 | **Naked POC / 80-%-Regel**: Anlaufquoten messen | Werden live als Ziele benutzt (vp/1, R4), Quote nie gemessen | klein (beschreibend) |

## Methodische Warnungen

Sie gelten für jede weitere Prüfung.
- **Mehr als 150 Prüfungen** auf BTC 2020–2024, aber kein fortlaufender Gesamtzähler. Der Deflated Sharpe zählt S8 und S13–S23 nicht mit, und OFX sucht ohne Obergrenze (8644 Konfigurationen, 0 bestanden).
- **Validierung 2023–2024 ist mehrfach verbraucht** (S7b, S9, S13–S27, OF2). Ein Bestehen dort ist nur noch schwacher Beleg. Neue Belege brauchen frische Daten: Vorwärtsläufe oder den Holdout 2025 genau einmal.
- **Papier-Journale hängen stark an den Ausschlüssen.** Das Hauptjournal kippt durch 27 Ausschlüsse von −27,6 R auf +0,9 R.
- **Lücken im Repo:**
  - S19- und S24-Ergebnisse fehlen.
  - S22-Ergebnis fehlt, es liegt nur am Mac.
  - Der R4-Bericht wurde nach den Methodenfehlern nie neu gerechnet.
- **Die Studien sind nicht unabhängig.** S19–S27 schneiden dieselben Daten neu, deshalb dürfen sich ihre Befunde nicht gegenseitig „bestätigen“.

## Nächster Schritt

- Uzi entscheidet über Gruppe 1 und die Top 10.
- Danach geht das Register als versionierte Datei ins Repo (`docs/research_lab/UEBERZEUGUNGEN.jsonl` o. ä.) und wird in den tim-graph eingebunden (P4).
- Die Research-Engine bekommt die Prüfschleife (P2) als eigenen Bauplan.
