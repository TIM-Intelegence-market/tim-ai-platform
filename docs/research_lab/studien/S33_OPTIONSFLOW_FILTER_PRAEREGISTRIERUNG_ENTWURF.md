# S33: Verbessert Optionsflow vorhandene Trades nach Kosten? (Präregistrierung, Entwurf)

| Feld | Wert |
|---|---|
| Studie | S33 (Entwurf 13.11.2026) |
| Version | **0.1, Entwurf, nicht eingefroren.** Einfrieren (1.0) nur auf Uzis Wort und vor jedem Blick auf das Testfenster |
| Anlass | Plan `../SELBSTVERBESSERNDE_KI_PLAN.md`, Uzi am 13.11.2026: „Mehr Daten und Regeln sammeln, dann testen“ |
| Protokoll | `../PROTOKOLL.md` Version 1.3 |
| Regeln | `OPTIONSFLOW_REGELKATALOG.md`: R1–R6 (Richtung, Filter), V1–V2 (Volatilität), zusammen 8 Tests |
| Daten | Eigene Aufzeichnung (A1, `src/research_lab/options_flow`), BTC, ab Dienststart; Kerzen und Trades wie S27 |

## 1. Fragestellung

Haben Optionsflow-Merkmale einen Zusammenhang mit dem Ergebnis der S27-Trades (Stop 3 ATR14, Ziel 6 ATR14, höchstens 168 h)
nach Bitunix-Kosten mit Funding, so dass der Filter „nehmen“ im Mittel **positiv** ist und besser als „auslassen“?
V1/V2: Sagen sie die Spanne der nächsten 24 h (ATR-normiert) besser voraus als die Spanne der letzten 24 h allein?

## 2. Daten und Fenster

Es gibt keine kostenlose Historie für 2020–2024. Darum gilt ein **Vorwärts-Aufbau**, ohne Holdout-Bezug:

1. **Kalibrierung:** die ersten 60 Tage der Aufzeichnung. Nur hier werden Terzile und die P95-Schwelle für „groß“ bestimmt.
2. **Test:** alle Tage danach, bis jede R-Regel mindestens 100 gefilterte Trades oder 12 Monate erreicht hat, je nachdem was
   zuerst kommt. Das Testfenster wird genau einmal ausgewertet.
3. Tage mit Lücke > 10 min in der Aufzeichnung (`audit.gaps`) fallen für die betroffenen Merkmalsfenster heraus und werden gezählt.

Wird später bezahlte Historie gekauft (Tardis), wird eine **neue Version** mit den üblichen Fenstern registriert
(Training 2020–2023, Validierung 2024, Holdout 2025 nur mit Uzis ausdrücklichem Wort). Daten beider Wege werden nicht gemischt.

Zeitregel: Merkmale zum Signalzeitpunkt t nur aus Zeilen mit `recv_ms <= t` (Datenvertrag). Einstieg zur nächsten Kerze.

## 3. Was gleich bleibt (aus S27, ohne Suche)

Trade-Erzeugung, Kosten (Taker 0,06 %, Schlupf 0,03 %, Stop-Schlupf 0,05 % je Seite, Funding), Auswertung in R,
Cluster-Bootstrap nach Woche, Verschiebungstest.

## 4. Entscheidung

Eine R-Regel gilt als **bestanden**, wenn im Testfenster alle Punkte erfüllt sind:

1. n „nehmen“ ≥ 100,
2. Mittel netto „nehmen“ > 0 R, Bootstrap-Intervall 95 % über 0,
3. Abstand „nehmen“ − „auslassen“ > 0 mit Holm-korrigiertem p < 0,05 über alle 8 Tests dieser Version,
4. Vorzeichen im Kalibrierfenster gleich.

V-Regeln: Holm-korrigiertes p < 0,05 für den Zuwachs gegenüber der Basis (Spanne der letzten 24 h).
Sonst: „nicht bestanden“ oder bei n < 100 „nicht prüfbar“. Keine Nachbesserung im selben Fenster.

## 5. Ablauf

1. Dienst läuft (A1), `audit` wöchentlich ohne Blick auf Ergebnisse (nur Zählung, Lücken, Ablehnungen).
2. Nach 60 Tagen: Kalibrierlauf, Schwellen festschreiben, Version 1.0 auf Uzis Wort einfrieren.
3. Zähllauf im Testfenster (nur n je Regel, ergebnisblind), dann einmalige Auswertung.
4. Ergebnis ins Gedächtnis; bestandene Regeln nur in den Schatten-Score (Paket A5), nie direkt live.

## 6. Grenzen

- Kurze Historie, eine Marktphase: ein Bestehen wäre ein Hinweis, kein Beweis. Darum folgt danach Papier-Vorwärtslauf (A8).
- Aggressor bei Blocktrades und Spreads unsicher (R2/R3).
- Parameter der Deribit-API nicht aus der Cloud geprüft; erster `audit` am Mac entscheidet, ob die Daten taugen.
