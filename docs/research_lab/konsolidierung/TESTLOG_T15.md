# Testlog T15 (Zusatzprotokoll 1.1-T15)

Erzeugt von `t15_ausserhalb.py`, getrennt von `TESTLOG.md`, damit ein erneuter Lauf von `lauf.py` es nicht überschreibt.

| Schritt | Zeitraum | Code-Commit | Befehl | Ergebnisdatei | Status | Grenzen |
|---|---|---|---|---|---|---|
| Datenbericht (vor dem Handelslauf) | Spot 4h-Kerzen 2017-08 bis 2019-12 (keine Handelssimulation) | `b0e8575629` | `python3 -m src.research_lab.konsolidierung.t15_ausserhalb audit /home/user/work/t15 manifest_t15.json` | `ergebnisse/t15_datenaudit.json` | bestanden (keine Abbruchregel ausgelöst) | Prüfsummen belegen die Unverändertheit gegenüber dem Binance-Archiv, nicht die Richtigkeit der Kurse; Eine zweite, unabhängige Kursquelle für 2017 bis 2019 wurde nicht herangezogen; Lücken (zum Beispiel Wartungszeiten) werden gemeldet, nicht aufgefüllt; die Simulation setzt nach einer Lücke 200 Kerzen Vorlauf voraus |
