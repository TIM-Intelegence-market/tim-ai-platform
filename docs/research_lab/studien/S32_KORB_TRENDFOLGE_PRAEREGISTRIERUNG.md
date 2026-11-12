# S32: Korb-Trendfolge auf anderen Coins: Trägt die S7b-Regel außerhalb von BTC, ETH und SOL? (Präregistrierung)

| Feld | Wert |
|---|---|
| Studie | S32 (12.11.2026) |
| Version | **1.0, eingefroren am 12.11.2026 auf Uzis Wort („einfrieren“), nach dem Trainingslauf und vor jedem Blick auf Validierung oder Holdout.** Die Validierung wird erst nach dem Merge dieses PR und auf ein weiteres Wort von Uzi gerechnet, genau einmal. |
| Anlass | E0 und S30 (12.11.2026): Auf Kerzen-Levels (4h) war Brutto überall um null, die Kosten (0,12 bis 0,42 R je Trade) fraßen alles. S7b-D20-T3 (S7b, 26.10.2026) hat bei weitem Stop (im Mittel > 1 %) geringere Kosten je R. Frage: Hält die Regel unverändert auf anderen Coins? |
| Protokoll | `../PROTOKOLL.md` Version 1.3 |
| Daten | Binance USD-M Perps, 4h, öffentliche Monatsdateien von data.binance.vision bis 2024-12 (394 Symbole mit Daten); Funding je Symbol (öffentliche Raten) |
| Holdout | ab 2025-01-01, wird nicht geladen. Training 2020–2022 (Universum ab 2020-07), Validierung 2023–2024 |

## 1. Fragestellung

Ist die unveränderte Regel S7b-D20-T3 (Donchian-Ausbruch Kanal 20 in Richtung SMA 200, 4h, Stop max(1,5 × ATR14, 1 %), Ziel 3 R, Zeitstopp 30 Kerzen) auf einem Korb von Coins außerhalb von BTC, ETH und SOL nach Bitunix-Kosten mit Funding im Mittel positiv, besser als Zufalls-Einstiege mit gleicher Stopweite, und nicht von wenigen Coins getragen?

## 2. Festgelegt (nicht verändert, keine Suche)

- **Regel:** `src/research_lab/hypotheses/s7.py` und `s7b.py`, Variante S7b-D20-T3, unverändert. Je Symbol mit der Projekt-Engine (`run_backtest`), eine Position je Symbol (Engine-Regel).
- **Universum:** je Monat die 25 USDT-USD-M-Perps mit dem höchsten Quote-Volumen der 30 Tage vor dem Monat (point-in-time), ohne BTCUSDT, ETHUSDT, SOLUSDT (gesehen). Ein Symbol handelt nur in Monaten, in denen es im Universum ist. Die Regel wurde auf BTC/ETH/SOL gefunden; unabhängig ist nur der Teil auf anderen Coins.
- **Kosten:** Bitunix wie S27 (Taker 0,0006, Schlupf 0,0003, Stop-Schlupf 0,0005 je Seite) plus das veröffentlichte Funding des Symbols über die Haltedauer. Brutto = dieselben Signale mit Kosten 0 und ohne Funding, **gepaart über die Signalzeit**.
- **Auswertung:** Trades, Brutto/Kosten/Netto in R, mittlere Stopweite in %, Cluster-Bootstrap nach Woche (10.000 Ziehungen, Seed 32), Zufalls-Entries (gleiche Anzahl, Seite und Stopweite je Symbol, Ziel 3 R, 30 Kerzen, gleiche Kosten, Seed 3232; **1.000 Ziehungen in der Validierung** statt 100 im Training, sonst identisch), Anteil der drei stärksten Symbole an der Summe, Ergebnis je Symbolgruppe (Terzile nach mittlerem Volumen-Rang), je Jahr, eine Position über den ganzen Korb als beschreibende Näherung. Eine Variante, daher Holm trivial.

## 3. Trainingslauf 2020-07 bis 2022-12 (Stand des Einfrierens, kein Urteil)

**Maßgeblich ist der zweite Lauf.** Der erste Lauf brach Symbol-Fenster mit abweichender Trade-Menge zwischen Kostenlauf und Nullkostenlauf ab (19 Fenster, u. a. ADA, LINK, XRP, ETC fehlten) und lieferte n 3093, Netto +0,040 R, Intervall [−0,072, +0,155], Zufalls-p 0,168. Das war ein Fehler der Auswertung (die 1-Position-Sperre verschiebt sich durch Kosten leicht), keine Regeländerung. Der zweite Lauf paart Brutto über die Signalzeit.

| | Zweiter Lauf (maßgeblich) |
|---|---|
| Trades / Wochen | 4682 / 151 |
| Brutto / Kosten / Netto (R je Trade) | +0,1254 / 0,0579 / **+0,0660** (Brutto und Kosten gepaart für 4668 Trades) |
| Stopweite (Mittel) | 6,1 % |
| Ziel / Stop | 22,5 % / 64,7 % |
| Cluster-Bootstrap Woche | 95 %-Intervall [−0,040, +0,174], 88,6 % der Ziehungen > 0 |
| Zufalls-Entries (100 Ziehungen) | Netto −0,006 R (sd 0,0235), p = 0,0099 (Auflösung 1/101) |
| Top 3 Symbole | ADA 59,5 R, VET 36,1 R, FIL 33,8 R = 41,9 % der Summe 308,8 R; Netto ohne Top 1 / 2 / 3: +0,056 / +0,048 / +0,042 |
| Symbolgruppen | liquide +0,074 (n 2759), mittel +0,078 (n 1327), weniger liquide +0,002 (n 596) |
| Je Jahr | 2020 +0,033, 2021 +0,051, 2022 +0,114 |
| Eine Position über den Korb (Näherung) | n 417, Netto +0,081 |

Ehrlich vermerkt: Dies ist der achte Versuch auf Binance-Kerzen in dieser Forschungslinie (E0, E1, S30 Fade, S30 Raster, S30 Ausbruch ×2, S33, S32); die Regel selbst stammt aus S7b (BTC/ETH/SOL, Training und Validierung). 2020–2022 war ein starker Altcoin-Aufwärtsmarkt. Das Universum enthält nur Symbole, für die Binance Dateien führt (Survivorship möglich). Das Bootstrap-Intervall schließt 0 ein.

## 4. Validierung 2023–2024: ein Lauf

Gate (ergebnisblind, vorab): mindestens 100 Trades und 50 Signal-Wochen in der Validierung. Danach genau ein Lauf mit denselben Skripten (Anlagen). Keine Nachsuche, keine anderen Parameter, kein zweiter Lauf, auch nicht bei Fehlern der Auswertung ohne neues Wort von Uzi. Das Holdout bleibt zu.

**Bestehensregel (alle Punkte, Vorschlag zur Bestätigung vor dem Merge):**
1. Netto-Mittel je Trade > 0 (gleichbedeutend: Brutto-Mittel > Kosten-Mittel).
2. Untere Grenze des Cluster-Bootstrap-Intervalls (95 %) > −0,05 R.
3. Zufalls-Entries: p < 0,05 bei 1.000 Ziehungen.
4. Die drei stärksten Symbole tragen < 50 % der Summe.
5. Netto-Mittel > 0 in mindestens zwei der drei Symbolgruppen.

Nicht erfüllt = S32 ist beendet; die Trendfolge auf Kerzen ist dann auf diesen Daten erledigt.

## 5. Grenzen

- Der Trainingslauf ist kein Beleg. Die Validierung kann nur widerlegen oder eine Kandidatin stehen lassen; belegt ist nichts vor einem Lauf auf Daten, die niemand gesehen hat (Holdout, nur mit Uzis ausdrücklichem Wort).
- Rebalancing, Marktauswirkung bei weniger liquiden Coins und Ausführungsverzögerung sind nicht modelliert.
- Der Code liegt als Anlage (`S32_ANLAGEN/*.txt`, SHA-256 in `SHA256SUMS.txt`). Eine Überführung nach `src/research_lab/studies/` mit Tests ist ein Folgeschritt und ändert keine Regel.
- Dieser PR enthält keinen ausführbaren Code und lädt keine Daten.

## 6. Anlagen und Fingerabdrücke

Skripte: `s32_universe_train.py`, `fetch_funding.py`, `fetch_perp_klines.py`, `s32_train.py` (als `.txt`). Beim Trainingslauf (PS5, 12.11.2026): `s32_train.py` SHA-256 `f371497285d99a7b2a9881037a17634958dbd105ef119eb01c0c43202c90e3c8`; Ergebnisdatei `s32_train_2026-11-12.json` `93845c895bc5a9994205a8630213e231369d3c346a2e5606c33c727285ee8bb4`; Universum `universe_train.json` `46a123ca30705c96b04d60baac68aeb0135cd229e33310b3dc761a141791520d`.
