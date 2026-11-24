# F3: Nachprüfung 1 h / 4 h / 24 h nach 30 Tagen (beschreibend)

Stand 24.11.2026. Paket F3 aus `docs/audits/GRUEN_PLAN_11_SICHTEN.md`, Sicht 5. Version der Nachprüfung `long-1.0.0`
(`docs/ORDERFLOW_VALIDATION_LONG.md`), nur OBSERVE.

## Quelle und Weg

- Gelesen wurde das nächtliche Backup `tim_20261124T021504Z.dump` vom 24.11. (SHA-256 beginnt mit `19607ccb`), nicht die
  Live-Datenbank. Die Mac-Sitzung hat mit `pg_restore --data-only -n public` nur die Tabellen
  `orderflow_observations` und `orderflow_validations_long` als Text ausgegeben, die Aggregate gerechnet und die
  Zwischendateien gelöscht. Hier stehen nur Summen und Verteilungen, keine Einzelzeilen.
- Zeitraum der Nachprüfungen: 24.10.2026 17:38 bis 24.11.2026 02:15 (Ortszeit). 93.554 Nachprüfungen, davon 89.388
  (95,5 %) mit allen drei Horizonten vollständig; der Rest lag beim Dump noch innerhalb von 24 h. Jede Nachprüfung hat
  eine passende Beobachtung. Je Tag 2.718 bis 3.734 Nachprüfungen, im Mittel etwa 3.050; kein Tag fehlt.

## Ergebnis je Beobachtungsart und Horizont

Nur vollständige Horizonte. Preisänderung in Prozent gegen den Schluss der letzten 1-Minuten-Kerze vor der Beobachtung.

| kind | min | n | 25 % | Median | 75 % | Anteil > 0 | Ø bester Punkt | Ø schlechtester Punkt |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| EXTREME_BUY_RATIO | 60 | 4892 | -0.199 | -0.021 | 0.151 | 0.464 | 0.252 | -0.288 |
| EXTREME_BUY_RATIO | 240 | 4874 | -0.423 | -0.011 | 0.295 | 0.492 | 0.510 | -0.654 |
| EXTREME_BUY_RATIO | 1440 | 4710 | -1.575 | -0.301 | 0.557 | 0.396 | 1.139 | -2.054 |
| EXTREME_SELL_RATIO | 60 | 2809 | -0.209 | -0.013 | 0.185 | 0.478 | 0.281 | -0.335 |
| EXTREME_SELL_RATIO | 240 | 2800 | -0.568 | -0.057 | 0.301 | 0.457 | 0.570 | -0.786 |
| EXTREME_SELL_RATIO | 1440 | 2708 | -1.990 | -0.590 | 0.404 | 0.357 | 1.220 | -2.593 |
| FALLING_CVD | 60 | 12201 | -0.243 | -0.022 | 0.196 | 0.469 | 0.341 | -0.389 |
| FALLING_CVD | 240 | 12151 | -0.579 | -0.061 | 0.349 | 0.458 | 0.671 | -0.875 |
| FALLING_CVD | 1440 | 11637 | -2.098 | -0.430 | 0.541 | 0.384 | 1.360 | -2.662 |
| HIGH_TRADE_FREQUENCY | 60 | 3096 | -0.217 | -0.014 | 0.178 | 0.477 | 0.305 | -0.344 |
| HIGH_TRADE_FREQUENCY | 240 | 3079 | -0.543 | -0.042 | 0.333 | 0.474 | 0.590 | -0.797 |
| HIGH_TRADE_FREQUENCY | 1440 | 2979 | -1.784 | -0.414 | 0.575 | 0.393 | 1.261 | -2.378 |
| LARGE_INDIVIDUAL_TRADE | 60 | 43940 | -0.244 | -0.024 | 0.189 | 0.466 | 0.340 | -0.379 |
| LARGE_INDIVIDUAL_TRADE | 240 | 43750 | -0.563 | -0.048 | 0.357 | 0.468 | 0.665 | -0.846 |
| LARGE_INDIVIDUAL_TRADE | 1440 | 41908 | -2.037 | -0.381 | 0.561 | 0.390 | 1.337 | -2.569 |
| RISING_CVD | 60 | 13566 | -0.244 | -0.032 | 0.174 | 0.455 | 0.324 | -0.361 |
| RISING_CVD | 240 | 13505 | -0.542 | -0.042 | 0.343 | 0.471 | 0.634 | -0.807 |
| RISING_CVD | 1440 | 12952 | -1.933 | -0.345 | 0.561 | 0.393 | 1.278 | -2.447 |
| STRONG_BUYER | 60 | 6135 | -0.236 | -0.026 | 0.179 | 0.463 | 0.312 | -0.352 |
| STRONG_BUYER | 240 | 6111 | -0.539 | -0.065 | 0.332 | 0.455 | 0.602 | -0.793 |
| STRONG_BUYER | 1440 | 5871 | -1.927 | -0.428 | 0.533 | 0.381 | 1.267 | -2.452 |
| STRONG_SELLER | 60 | 6915 | -0.230 | -0.019 | 0.175 | 0.470 | 0.306 | -0.359 |
| STRONG_SELLER | 240 | 6882 | -0.557 | -0.047 | 0.322 | 0.466 | 0.601 | -0.818 |
| STRONG_SELLER | 1440 | 6623 | -1.912 | -0.374 | 0.579 | 0.396 | 1.284 | -2.443 |
| ALLE | 60 | 93554 | -0.236 | -0.024 | 0.183 | 0.465 | 0.326 | -0.367 |
| ALLE | 240 | 93152 | -0.552 | -0.048 | 0.342 | 0.467 | 0.639 | -0.825 |
| ALLE | 1440 | 89388 | -1.971 | -0.388 | 0.556 | 0.389 | 1.306 | -2.513 |

## Einordnung

- Alle Beobachtungsarten sehen fast gleich aus wie „ALLE“. Die 24-h-Mediane sind durchweg negativ (−0,30 bis −0,59 %),
  der Anteil mit Anstieg liegt bei 0,36 bis 0,40. Das spiegelt vor allem den fallenden BTC-Markt im Zeitraum.
- Kauf- und Verkaufsbeobachtungen trennen sich nicht in die erwartete Richtung: STRONG_BUYER 24 h Median −0,43 % gegen
  STRONG_SELLER −0,37 %, RISING_CVD −0,35 % gegen FALLING_CVD −0,43 %.
- LARGE_INDIVIDUAL_TRADE macht 47 % aller Nachprüfungen aus; das passt zum S2-Befund, dass die Regel fast immer anschlägt.
- Die Beobachtungen überlappen stark (etwa zwei pro Minute). Die n sind keine unabhängigen Fälle; es gibt keine
  Basisrate und keine Kontrollgruppe.

**Ergebnis:** Nach 30 Tagen zeigt keine Beobachtungsart auf 1 h, 4 h oder 24 h ein erkennbar anderes Verhalten als der
Markt insgesamt. Das bestätigt die Entscheidung vom 26.10.: Die Live-Orderflow-Regeln bleiben Beobachtungen, keine
Signale. Ein Test auf Vorhersagekraft bräuchte eine eigene Vorab-Registrierung (Treffer-Definition, Basisrate,
Clusterung) und ist nicht Teil von F3.
