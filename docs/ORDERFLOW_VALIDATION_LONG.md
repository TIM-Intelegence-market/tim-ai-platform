# Nachprüfung auf höheren Zeitebenen (1h, 4h, 24h)

Stand 25.10.2026, Paket H1 aus `docs/audits/GRUEN_PLAN_11_SICHTEN.md`. Auftrag Uzi (25.10.): Die Nachprüfung nach 5, 15
und 30 Minuten reicht für die kurze Zeitebene; für die höheren Zeitebenen braucht TIM eigene Forschungsdaten.

## Was neu ist

Zu jeder Orderflow-Beobachtung dokumentiert TIM zusätzlich, wo der Preis **1 Stunde, 4 Stunden und 24 Stunden** später
stand. Die bisherige Nachprüfung (`src/orderflow/validation.py`, Version 1.0.0, Tabelle `orderflow_validations`) bleibt
unverändert; die neue läuft daneben:

| | kurz (bisher) | lang (neu) |
|---|---|---|
| Modul | `src/orderflow/validation.py` | `src/orderflow/validation_long.py` |
| Horizonte | 5, 15, 30 min | 60, 240, 1440 min |
| Eingabe | aggTrades | 1-Minuten-Kerzen |
| Tabelle | `orderflow_validations` | `orderflow_validations_long` (Migration 008) |
| Version | `1.0.0` | `long-1.0.0` |
| Einstufung | PRICE_INCREASED / DECREASED / SIDEWAYS (Schwelle 0,10 %) | **keine** |
| API | `/api/state`, `/api/orderflow/history` | `/api/validations-long` |

## Was je Horizont gespeichert wird

`price` (Schluss der letzten Kerze bis zum Zielzeitpunkt), `price_change_percent` gegen die Basis, `max_high_percent`
(bester Punkt im Fenster), `min_low_percent` (schlechtester Punkt), `candle_count`, `expected_candles`,
`coverage_percent`, `complete`, `source_hash` (SHA-256 über alle Kerzen des Fensters und den Eingabe-Hash der
Beobachtung).

Die Basis ist der Schluss der letzten 1-Minuten-Kerze, die **spätestens zum Beobachtungszeitpunkt** geschlossen hat.
Die Kerze, in der die Beobachtung liegt, schließt erst danach und wird nicht benutzt (kein Blick nach vorn).

## Bewusste Entscheidungen

- **Keine Einstufung.** Eine Schwelle von 0,10 % wie bei 30 Minuten ist bei 24 Stunden sinnlos; jede andere Schwelle wäre
  eine erfundene Zahl. Gespeichert werden nur Messwerte. Welche Bewegung als Treffer zählt, entscheidet eine Studie
  später auf den gespeicherten Daten (Register im Research Lab).
- **Einmal je Horizont.** Jeder Horizont wird genau dann gerechnet, wenn sein Zielzeitpunkt vorbei ist. Lücken in den
  Kerzen stehen als `coverage_percent < 100` und `complete = false` im Datensatz; sie werden live nicht erneut geprüft.
- **Nie blockierend.** Ein Fehler in der langen Nachprüfung wird protokolliert und übersprungen; der Dateneingang läuft
  weiter. Die kurze Nachprüfung und die Fälle sind davon unberührt.
- **Rückblick begrenzt.** Live werden Beobachtungen bis 28 Stunden zurück betrachtet. Ältere Beobachtungen bekommen ihre
  lange Nachprüfung nur über einen offline-Lauf (noch nicht gebaut).

## Wann Daten da sind

Nach dem Einspielen (`--init-schema` legt die Tabelle an) füllt sich die Tabelle ab der ersten Beobachtung: 1h-Werte
nach einer Stunde, 24h-Werte nach einem Tag. Für eine erste Auswertung sind 30 Tage vorgesehen (Paket F3), also frühestens
Ende November 2026. Vorher gibt es Einzelwerte, aber keine Aussage.

## Prüfen

```sh
python -m pytest tests/test_orderflow_validation_long.py -q
curl -s http://127.0.0.1:8765/api/validations-long | head -c 600     # auf dem Mac
```
