# Methodenbefund 2026-10-22: Zukunftsinformation in der Walk-Forward-Auswahl

Paket T03 des gemeinsamen Verbesserungsplans (Codex-Befund F01, Claude H5). Protokoll 1.0 → 1.1,
siehe Änderungsprotokoll in `../PROTOKOLL.md`. Holdout wurde nicht geladen.

## Befund

`src/research_lab/stats/inference.py`, `walk_forward()`: Die Wahl der besten Rastervariante am Ende
eines 24-Monats-Anpassungsfensters mittelte `trade.r` über alle Trades mit `entry_time` im Fenster.
Ein Trade, der im Fenster eröffnet, aber erst danach geschlossen wurde, brachte sein späteres
Ergebnis in eine Entscheidung ein, die zum Fensterende fiel.

Reproduktion (Test `test_walk_forward_choice_ignores_outcomes_unknown_at_fit_end`): Zwei Verläufe,
die bis zum Fensterende identisch sind und sich nur im späteren Ergebnis eines offenen Trades
unterscheiden, führten zu unterschiedlichen Wahlen (`a` bei +5 R, `b` bei −5 R).

Zweiter Punkt derselben Stelle: Die Zuordnung zum Fenster lief über `entry_time`, der R4-Runner
(`_split`) und Abschnitt 3.2 des Protokolls ordnen Trades über `signal_time` zu.

## Korrektur (Version 1.1)

- Anpassung: nur Trades mit Signal im Fenster **und** `exit_time <= fit_end` (`known_at`).
- Testfenster: Trades mit Signal in `[fit_end, test_end)` (`signalled_in`).
- Ein am Fensterende offener Trade zählt in keines der beiden Fenster.
- Tests für exakte Grenzen (Ausstieg genau am Fensterende zählt zur Anpassung, Signal genau am
  Fensterende zum Test), verspätete Daten, leere Anpassungsfenster und fehlende Fenster.

Die Korrektur ist strenger als 1.0 (sie entfernt Information), was das Änderungsprotokoll nach
Beginn von R4 verlangt.

## Betroffene Berichte

| Bericht | Protokoll | Einschränkung |
|---|---|---|
| `r4_2026-09-29T2219Z.md` / `.json` | 1.0 | `walk_forward_mean` je Hypothese (L1 1,92; L2 0,10; M1 0,37; M2 −0,01; M3 −0,10; S1 −0,43; S2 −0,00; T1 −0,26; T2 −0,34; T3 −0,43) wurde mit Zukunftsinformation berechnet und ist als Zahl nicht mehr belastbar. |

Auswirkung auf die Urteile: keine. Von 48 Varianten scheiterten 42 schon im Training. Die sechs
Varianten mit `failed_validation` (L1-n100-l, L1-n100-ls, L1-n150-ls, L2-L30-l, L2-L30-ls, M3-mi-long)
scheiterten alle an „Validierung: p ≥ 0,05 gegen Zufall“; nur M3-mi-long trug zusätzlich den
Walk-Forward-Grund. Kein Kandidat wurde allein durch den Walk-Forward verworfen oder zugelassen.
Das Gesamtergebnis „kein Vorteil in Training/Validierung gefunden, Holdout unberührt“ bleibt bestehen.

Der Originalbericht bleibt unverändert. Ein Neulauf von R4 mit Version 1.1 steht aus; er braucht die
Binance-Archive (im Cloud-Container gesperrt) und läuft nicht auf dem Kampagnen-Mac, solange die
V2-Qualifizierung dort läuft (bis mindestens 23.11.2026).

## Nicht geändert

Datensplit (Validierung ab 2023-01-01, Holdout ab 2025-01-01), Kriterien K1–K5, Raster, Register
(m = 48), Holdout-Sperre. Die Jahresstatistik (`expectancy_by_year`) und der Monats-Bootstrap ordnen
weiter über `entry_time` zu; das ist eine Zuordnung abgeschlossener Trades, keine Auswahl, und
verschiebt höchstens einen Trade um eine Kerze an der Jahresgrenze.
