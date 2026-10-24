# Studie S2: Die Live-Orderflow-Regeln als eigene Hypothese (Präregistrierung, Entwurf)

| Feld | Wert |
|---|---|
| Status | **ENTWURF, nicht freigegeben.** Erst vollständige Power-/Implementierungsnachweise und Freigabe durch Uzi erlauben Version 1.0; danach nur noch Änderungen über das Änderungsprotokoll unten. |
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

## 2. Festgelegte Hypothesen und Entscheidungsregel (Revision 0.2)

Familie: sechs gerichtete Arten × Horizonte {5, 15, 30} Minuten = 18 Hypothesen.
Je Hypothese lautet H0: Richtungs-Trefferquote nach K minus Basisrate ≤ 0.
Käuferarten sind STRONG_BUYER, RISING_CVD und EXTREME_BUY_RATIO; Verkäuferarten
STRONG_SELLER, FALLING_CVD und EXTREME_SELL_RATIO (jeweils vollständiger `_ACTIVITY`-Typ).
Die beiden ungerichteten Arten bleiben rein deskriptiv.

Ein Treffer erfordert gerichtete Rendite ≥ 0,10 % (Gleichheit zählt); ansonsten Nichttreffer.
Rendite ist Schlusskurs des vollständigen Horizontfensters / Schlusskurs des Startfensters − 1.
Fehlende oder unvollständige Start-/Zielfenster werden ausgeschlossen und gezählt, nicht als
Nichttreffer imputiert. Alle Grenzen und Kalenderwochen verwenden UTC/ISO-Wochen.

Pro Art wird chronologisch nur die erste Beobachtung behalten, danach werden alle weiteren
innerhalb von strikt weniger als 30 Minuten ausgeschlossen (greedy, kein gleitendes Neuankern).
Baseline sind alle vollständigen 60-s-Fenster derselben Woche ohne diese Art K, mit identischer
Labeldefinition. Kontrollfenster dürfen andere Arten enthalten. Wochen ohne mindestens einen
K-Fall und ein Kontrollfenster sind für beide Gruppen ausgeschlossen und separat berichtet.
Die Baseline wird auf die Wochenverteilung der K-Fälle standardisiert:
`delta = sum_w nK_w * (pK_w - pB_w) / sum_w nK_w`.
Damit wird eine andere zeitliche Verteilung der Kontrollen nicht mit dem Regeleffekt verwechselt.

**Primärer Test:** Je Trainings-/Validierungsabschnitt werden vollständige Wochen mit allen
zugehörigen Fällen und Kontrollen als Einheiten verwendet. Moving-block-Bootstrap mit vier
aufeinanderfolgenden Wochen, B = 19.999, Seed = 20261022. Aus allen möglichen zusammenhängenden
Vier-Wochen-Blöcken (ohne zyklischen Jahres-/Abschnittsübergang) mit Zurücklegen ziehen, bis die
ursprüngliche Wochenzahl erreicht ist; Überhang abschneiden. Auch ausgeschlossene Wochen bleiben
als leere Kalenderpositionen erhalten. `delta*` wird jedes Mal mit den resampelten Zählern und
Nennern neu berechnet. Degenerierte Ziehungen ohne auswertbare Fälle zählen konservativ im Zähler.
Einseitiges, nullzentriertes Bootstrap-p:
`p = (1 + count(delta* - delta >= delta)) / (B + 1)`.
Diese Inferenz setzt ausreichend schwache Abhängigkeit über Vier-Wochen-Blöcke voraus; sie ist
keine verteilungsfreie Garantie. Sensitivität mit zwei und acht Wochen wird berichtet, ersetzt
aber weder primären Test noch Urteil.

Training und Validierung müssen beide tragen: `p_joint = max(p_train, p_validation)`
(Intersection-Union-Test). Holm wird **einmal über diese 18 p_joint** angewandt, aufsteigend nach
p, bei Gleichstand Typname/Horizont. Adjustierte p-Werte sind die bei 1 gekappten laufenden Maxima
von `(18-i+1)*p_(i)`. Nicht beurteilbare Tests bleiben mit p=1 in der Familie.

**BESTANDEN:** Holm-p ≤ 0,05 und delta ≥ 0,03 in beiden Abschnitten, außerdem alle Daten- und
Power-Voraussetzungen erfüllt. **NICHT_BEURTEILBAR:** fehlende Nachweise, weniger als 200
K-Fälle oder weniger als 26 auswertbare Wochen in einem Abschnitt oder unzureichende Power.
Sonst **NICHT_BESTANDEN**. Mindestens ein BESTANDEN erlaubt nur die Aussage, genau diese
Art/Horizont-Kombination habe den retrospektiven Test bestanden; keine Aussage über alle Regeln.
95-%-Perzentilintervalle (2,5/97,5 %) werden unadjustiert zur Beschreibung gezeigt und ausdrücklich
nicht als simultane Intervalle oder zusätzliches Erfolgskriterium bezeichnet.

## 3. Fallzahlprüfung als noch offenes Freigabe-Gate

+3 Prozentpunkte sind die vorab gewählte wissenschaftlich relevante Effektgröße, **keine**
Aussage über Profitabilität oder Kostendeckung. Eine Trefferquote alleine bestimmt weder
Gewinnhöhe noch Verlusthöhe. Kostenprüfung gehört in eine eigene Strategie-Studie S3.

Vor Einsicht in Archiv-Outcomes muss ein versioniertes Power-Simulationsprotokoll vorliegen:
10.000 Replikationen, Seed 20261023, tatsächliche wöchentliche Fall-/Kontrollzahlen aus einem
reinen Zähllauf, Basisraten {0,35; 0,50; 0,65}, wahre Differenz 0,03 und Wochen-ICC {0; 0,05; 0,10}.
Je Gruppe/Woche unabhängiger Beta-Binomial-Zähler: Mittel p, Konzentration `1/ICC-1`;
bei ICC=0 Binomial. K verwendet p+0,03, Kontrolle p. Dies ist ein explizites vereinfachtes
Planungsmodell, keine bewiesene Abhängigkeitsstruktur der Marktdaten.
Auswertung mit derselben standardisierten Statistik und demselben Vier-Wochen-Test; konservative
Schwelle 0,05/18 je Abschnitt. Gefordert sind mindestens 90 % Power **je Abschnitt** in jedem
Szenario für das statistische Kriterium (damit mindestens 80 % für gemeinsames Verwerfen per
Union-Bound). Die zusätzliche beobachtete Effektgrößenhürde ist separat als Gesamterfolgsrate
zu berichten; sie ist bei einem wahren Effekt genau an der Grenze nicht mit 80 % zugesichert.

200 Fälle sind lediglich die Untergrenze, kein Power-Nachweis. Kein Hochrechnen der Live-Dichte
auf frühere Marktjahre als Ersatz für Archiv-Zählungen. Wenn Power oder Modellangemessenheit
nicht belegt sind: NICHT_BEURTEILBAR. Keine nachträgliche Lockerung der Regeln, Alpha-Werte,
Horizonwahl oder Mindestzahlen. Simulation, Implementierung und unabhängige Prüfung stehen aus;
dieser PR führt sie nicht aus und erteilt keine Studienfreigabe.

## 4. Daten, Wissenszeit und prospektive Registrierung

Quelle: Binance-Archiv aggTrades BTCUSDT Spot, Dateiprüfsummen prüfen. Herunterladen,
Replay und Simulation ausschließlich im getrennten Labor, niemals auf dem Kampagnen-Mac.
Training [2020-01-01, 2023-01-01), Validierung [2023-01-01, 2025-01-01), UTC.
Der bestehende Holdout ab 2025-01-01 bleibt gesperrt. Live-Daten Juli–Oktober 2026 sind bereits
bekannt und kein frischer Bestätigungssatz.

**Ereigniszeit ist keine Wissenszeit.** `window_end` datiert das Marktfenster. Für reale
Verfügbarkeit zählen nachweisbare Empfangs-, Finalisierungs- und Persistenzzeiten;
`available_at` ist deren Maximum für genau die verwendete Inhaltsversion. Ein Outcome ist erst
bekannt, wenn auch seine vollständigen Horizontdaten empfangen, finalisiert und persistiert sind.
Eine Abschnittsauswertung verwendet nur bis zum Stichtag verfügbare Beobachtungen und Outcomes;
Start- und Zielereignis müssen zusätzlich im selben Abschnitt liegen. Verspätete Daten werden
gezählt und ausgeschlossen, niemals rückdatiert. Fehlende Wissenszeit bleibt unbekannt.

Archive liefern keinen Beweis historischer TIM-Verfügbarkeit. Ein Archiv-Replay darf deshalb nur
als idealisierte Ereigniszeit-Studie unter expliziter Sofortverfügbarkeitsannahme ausgewiesen werden.
Es beweist weder historische Umsetzbarkeit noch einen realen Point-in-Time-Vorteil. Reale
Latenz-/Wissenszeitaussagen benötigen eine getrennte Auswertung mit gemessenen Zeitstempeln.

**Prospektiv:** kein automatischer Start am 24.11.2026. Vor dem ersten zulässigen Fall sind in einer
eigenen unveränderlichen Registrierung Startzeit, Ende exakt 90 Tage später, Datensatz-/Code-Version,
Wissenszeit-Erfassung, Power-Plan und dieselbe 18er-Familie festzuhalten und freizugeben.
Start erst nach bestätigtem Kampagnenabschluss und gesonderter Betriebsfreigabe. Ein fehlendes
Zeitstempel-Feld darf nicht während der Kampagne nachgerüstet werden. Keine Zwischenanalyse,
kein Verlängern bis zur Signifikanz. Bei zu wenigen Fällen am festen Ende: NICHT_BEURTEILBAR.
Prospektive Ergebnisse werden separat mit eigener Holm-Korrektur berichtet, nicht mit den
retrospektiven Ergebnissen gepoolt oder als Ersatz für deren Scheitern verwendet.

## 5. Bericht

Je Test: Fallzahl, Trefferquote, Basisrate, Differenz mit Intervall, korrigiertes p, Urteil, mittlere gerichtete Preisänderung
(rein deskriptiv, ohne Profitabilitätsurteil), Regimeaufteilung (Trend/Seitwärts nach 1d-Kerzen, Jahr). Zusätzlich Block-Bootstrap statt iid und die
Clusterregel aus Abschnitt 3 ausgewiesen. Alle Datensatz-Hashes und der Commit des Rechenstands werden angegeben.
Regime sind ausschließlich deskriptiv: Trend, wenn der absolute Return über die letzten
20 **vor dem Startzeitpunkt abgeschlossenen** UTC-Tageskerzen mindestens 5 % beträgt,
sonst Seitwärts. Fehlen die 21 nötigen Schlusskurse oder ihre Verfügbarkeitsnachweise,
lautet das Regime UNBEKANNT (Archive nur unter ihrer ausdrücklich idealisierten Annahme).
Keine begonnene Tageskerze, kein späteres Tageshoch/-tief; keine Auswahl von Tests anhand
dieser Aufteilung. Fehlende Fenster, ausgeschlossene Wochen, verspätete Versionen und
unbekannte Zeiten werden je Art/Horizont/Abschnitt mit Anzahl und Grund berichtet.
Unabhängige Wiederholung durch eine zweite Person mit denselben Dateien gehört zur Abnahme.

## 6. Was der Betrieb davon hat

Besteht kein Test, bleibt TIM ein Beobachtungs- und Forschungssystem; dann wird keine Strategie (S3) gebaut, und
Paper Trading (V9) wartet auf eine neue Hypothese. Besteht mindestens ein Test, folgt S3 (Strategieanspruch mit
Kosten, R-Einheit und Kapitalkurve mit Ruinregel) nach Protokoll 1.1.

## Änderungsprotokoll

| Datum | Version | Änderung | Grund | Bis dahin gesehene Daten |
|---|---|---|---|---|
| 2026-10-22 | 0.1 | Entwurf | T08 | Live-Trefferquoten Juli–Okt 2026 (deskriptiv); keine Archivdaten für diese Regeln |

| 2026-10-22 | 0.2 | Wissenszeit getrennt, Test/Multiplikität konkretisiert, Power-Gate und prospektiver Start präzisiert | Review R5 | Keine neuen Ergebnisdaten in dieser Korrektur gelesen |
