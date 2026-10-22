# Studie S2: Die Live-Orderflow-Regeln als eigene Hypothese (Präregistrierung, Entwurf)

| Feld | Wert |
|---|---|
| Status | **ENTWURF, nicht freigegeben.** Freigabe durch Uzi macht daraus Version 1.0; danach nur noch Änderungen über das Änderungsprotokoll unten. |
| Erstellt | 2026-10-22, Paket T08 des gemeinsamen Verbesserungsplans (Claude K2, Codex F01/F07) |
| Protokollbezug | `../PROTOKOLL.md` Version 1.1 (Kosten 4.4, Zufallsvergleich 7.1, Zeitgrenzen 7.3 neu) |
| Daten bis dahin gesehen | Live-Betrieb seit Juli 2026 inkl. Retrospektive-Trefferquoten im Control Center (deskriptiv, 5/15/30 min). Keine Historie vor Juli 2026 für diese Regeln ausgewertet. |

## 1. Genau festgelegt: Regelversion und Anspruch

- **Regelversion:** `src/orderflow/observations.py`, `RULE_VERSION = "1.0.0"`, acht Beobachtungsarten
  (STRONG_BUYER_ACTIVITY, STRONG_SELLER_ACTIVITY, RISING_CVD_ACTIVITY, FALLING_CVD_ACTIVITY,
  HIGH_TRADE_FREQUENCY, LARGE_INDIVIDUAL_TRADE_ACTIVITY, EXTREME_BUY_RATIO_ACTIVITY, EXTREME_SELL_RATIO_ACTIVITY),
  jeweils feste Schwellen über zwei benachbarte 60-s-Metrikfenster aus Binance-Spot-aggTrades (BTCUSDT).
  Die Regeln werden für die Studie **nicht** verändert; eine andere Version ist eine andere Studie.
- **Anspruch, der geprüft wird (nur einer):** *Vorhersage der Richtung.* Nach einer Beobachtung der Art K ist der
  Preis h Minuten später häufiger in Richtung R(K) als die Basisrate derselben Woche. R(K): Käuferarten → steigt,
  Verkäuferarten → fällt, HIGH_TRADE_FREQUENCY und LARGE_INDIVIDUAL_TRADE_ACTIVITY → *keine Richtung*, sie
  werden nur deskriptiv berichtet (Vorhersage nicht behauptet).
- **Nicht geprüft:** eine simulierte Strategie mit Einstieg, Stop und Ziel. Das wäre ein zweiter Anspruch mit eigener
  Präregistrierung (S3), erst sinnvoll, wenn S2 die Richtung bestätigt.
- Zwischen „deskriptiv“, „Vorhersage“ und „Strategie“ wird nachträglich nicht gewechselt.

## 2. Hypothese, Effektgröße, Baseline, Kriterium, Abbruch

- **H1 (je gerichtete Art K und Horizont h ∈ {5, 15, 30} min):** P(Richtung R(K) | K) − P(Richtung R(K) | Basis) > 0.
- **Primäre Effektgröße:** Differenz der Trefferquoten in Prozentpunkten, mit 95-%-Intervall aus Block-Bootstrap
  über Kalendertage (Blöcke, weil Beobachtungen innerhalb eines Tages abhängig sind).
- **Basisrate:** alle 60-s-Fenster derselben Kalenderwoche ohne Beobachtung der Art K (wie `src/reflection`, PR #361).
  „Richtung“ = Vorzeichen der Preisänderung nach h Minuten; |Änderung| < 0,10 % gilt als seitwärts und zählt
  für beide Seiten als Nichttreffer (Schwelle aus `validation.py`).
- **Kosten:** Für den Richtungsanspruch keine Kosten. Berichtet wird zusätzlich, ob die mittlere Preisänderung in
  Richtung R(K) nach h Minuten die Round-Trip-Kosten aus Protokoll 4.4 (0,16 % Gebühren und Slippage) übersteigt;
  das ist eine Vorabinformation für S3, kein Kriterium von S2.
- **Erfolgskriterium (vorab):** H1 gilt als bestätigt, wenn in Training **und** Validierung die untere Grenze des
  95-%-Intervalls > 0 ist, nach Holm-Korrektur über die Familie dieser Studie (6 gerichtete Arten × 3 Horizonte =
  18 Tests, m = 18). Mindestfallzahl je Test 200 Beobachtungen in jedem Abschnitt, sonst KEIN URTEIL.
- **Abbruchregel:** Zeigt die Fallzahlsimulation (Abschnitt 3) vor dem ersten Lauf, dass < 200 Fälle je Abschnitt
  erwartbar sind, wird der Test nicht gerechnet und als NICHT_BEURTEILBAR eingetragen; die Schwellen der Regel
  werden dafür nicht gelockert.
- **Zulässige Ergebnisse:** BESTANDEN, NICHT_BESTANDEN, NICHT_BEURTEILBAR je Test; die Studie gilt als
  „Richtung bestätigt“ nur, wenn mindestens ein Test BESTANDEN ist.

## 3. Fallzahl und minimale relevante Effektgröße (vor dem Lauf zu rechnen)

- Minimale relevante Effektgröße: +3 Prozentpunkte über Basisrate (darunter trägt keine Strategie die Kosten).
- Simulation: aus der Beobachtungsdichte der Live-Daten (Juli bis Oktober 2026, nur Zählung, keine Ergebnisse)
  wird die erwartete Fallzahl je Art für 2020-01 bis 2024-12 hochgerechnet. Power ≥ 0,8 bei α/m = 0,05/18 wird
  vorab ausgerechnet und in dieses Dokument eingetragen, bevor Ergebnisse angesehen werden.
- Serielle Abhängigkeit: Beobachtungen derselben Art innerhalb von 30 Minuten gelten als ein Cluster; nur die erste
  zählt (nicht überlappende Einheiten sind damit *definiert*, nicht als unabhängig *behauptet*, siehe T09).

## 4. Daten und Zeitgrenzen

- Quelle: Binance-Archiv aggTrades BTCUSDT Spot (`data.binance.vision`), monatlich, Prüfsummen PASS je Datei,
  Herunterladen und Rechnen **nur in einer getrennten Laborumgebung**, nicht auf dem Kampagnen-Mac.
- Training 2020-01-01 bis 2022-12-31, Validierung 2023-01-01 bis 2024-12-31 (wie Protokoll 3.2).
- **Holdout:** Der bestehende Holdout ab 2025-01-01 wird **nicht** benutzt. Die Regeln 1.0.0 wurden im Juli 2026
  auf Live-Daten entworfen und beobachtet; 2025/26 ist deshalb für sie kein frischer Zeitraum. Prospektiver Test:
  die laufende Live-Validierung ab 2026-11-24 (nach Ende der Kampagne), ausgewertet frühestens nach 90 Tagen,
  mit denselben 18 Tests und m = 18.
- Zeitgrenzen: Beobachtung zu `window_end`, Ergebnis zu `window_end + h`; eine Beobachtung zählt zu dem Abschnitt,
  in dem `window_end` liegt, und nur, wenn `window_end + h` noch im selben Abschnitt liegt (keine Grenzüberschreitung).
  Wissenszeit = `window_end` (Fenster abgeschlossen), Ergebnis bekannt ab `window_end + h`.

## 5. Bericht

Je Test: Fallzahl, Trefferquote, Basisrate, Differenz mit Intervall, korrigiertes p, Urteil, mittlere Preisänderung
gegen Kosten, Regimeaufteilung (Trend/Seitwärts nach 1d-Kerzen, Jahr). Zusätzlich Block-Bootstrap statt iid und die
Clusterregel aus Abschnitt 3 ausgewiesen. Alle Datensatz-Hashes und der Commit des Rechenstands werden angegeben.
Unabhängige Wiederholung durch eine zweite Person mit denselben Dateien gehört zur Abnahme.

## 6. Was der Betrieb davon hat

Besteht kein Test, bleibt TIM ein Beobachtungs- und Forschungssystem; dann wird keine Strategie (S3) gebaut, und
Paper Trading (V9) wartet auf eine neue Hypothese. Besteht mindestens ein Test, folgt S3 (Strategieanspruch mit
Kosten, R-Einheit und Kapitalkurve mit Ruinregel) nach Protokoll 1.1.

## Änderungsprotokoll

| Datum | Version | Änderung | Grund | Bis dahin gesehene Daten |
|---|---|---|---|---|
| 2026-10-22 | 0.1 | Entwurf | T08 | Live-Trefferquoten Juli–Okt 2026 (deskriptiv); keine Archivdaten für diese Regeln |
