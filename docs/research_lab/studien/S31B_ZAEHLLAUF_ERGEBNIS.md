# S31b Zähllauf Training 2020–22: Ergebnis (12.11.2026)

STATUS: PARTIAL (Zähllauf fertig; Auswertung entfällt nach Vorab-Regel „n < 100 = nicht prüfbar“)
SCOPE: S31b-Präregistrierung 1.0, Konfigurationen 1h und 4h, Modelle M1–M7 (OF2 1.0), B6, B7. PS5, results/s31/countb_tf60.json und countb_tf240.json. Metrics erst ab 2020-09.

EVIDENCE: Trades Training (OF = mit Orderflow-Bestätigung / Preis-Zwilling = alle Signale)
| Regel | 1h OF | 1h Preis | 4h OF | 4h Preis |
|---|---|---|---|---|
| M1 Failed Auction | 16 | 23 | 1 | 2 |
| M2 Akzeptanz | 2 | 39 | 0 | 47 |
| M3 SFP | 0 | 4 | 0 | 13 |
| M4 Absorption | 0 | 0 | 0 | 0 |
| M5 Stacked-Retest | 2 | 15 | 1 | 33 |
| M6 Stop-Run | 11 | 70 | 3 | 28 |
| M7 Poor Edge | 0 | 10 | 0 | 14 |
| B6 Spot-/Perp | 0 | 0 | 0 | 0 |
| B7 OI-Sweep | 39 | 117 | 26 | 75 |

Keine Orderflow-Variante erreicht 100 Trades (höchster Wert B7 1h mit 39). Der Preis-Zwilling von B7 auf 1h hat 117, ist aber nur der Vergleichswert; ohne ≥ 100 OF-Trades kann der Orderflow-Vorsprung nicht geprüft werden.

RISKS: Größere Kerzen senken die Kosten in R, aber die Signalzahl fällt stärker: 1h und 4h liefern weniger OF-Trades als 15m/30m (M1: 34 auf 15m/30m, 16 auf 1h, 1 auf 4h). Dalton-/Bootcamp-Regeln lösen auf BTC mit täglich zurückgesetzter Kerzenhistorie selten aus.
NEXT: Kein Validierungslauf, kein Holdout. Mit Orderflow-Regeln dieser Art gibt es auf BTC 2020–22 keine genug große Stichprobe, um ein Ja oder Nein nach den Messlatten zu belegen. Wege nur mit Uzis Wort: mehr Daten (weitere Märkte, z. B. ETH/SOL, derselbe Rahmen) oder lockerere Auslöser als neue, vorab registrierte Studie.
