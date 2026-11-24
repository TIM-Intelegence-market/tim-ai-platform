# Signalgruppe: drei Kanäle getrennt auswerten

Stand 29.10.2026. Bauplan „TIM × Signalgruppe: Three-Channel Plan“, Schritte 2 und 3 (Leser und
Nachprüfung). Schritte 1, 4 und 5 (Bot einladen, Board in #tim-live) warten auf die Zustimmung
der Signalgruppe-Admins.

## Was gebaut ist

| Profil | Kanäle | Autor | Leser | Laufzeit |
| --- | --- | --- | --- | --- |
| `futures_btc` | Kanal 1, Kanal 2 | Autor A | BTC, wenn nicht ETH/SOL genannt; Long-/Short-Box aus dem Chart-Anhang zählt als Call | 72 h |
| `spot_coins` | Kanal 3 | Autor B | Coin (Cashtag hat Vorrang), Topf risky/safe, Kontoanteil, DCA-Schritt | 30 Tage |
| `gold_silber` | Kanal 4 | Autor C | XAU, bei reinem Silber-Post XAG | 72 h |

Code: `src/knowledge/signalgruppe_channels.py`, Aufruf: `scripts/signalgruppe_channels.py`, Tests:
`tests/test_signalgruppe_channels.py`.

## Regeln der Nachprüfung

- Einstieg ist der Eröffnungskurs der ersten Kerze, die in oder nach der Minute des Posts
  beginnt. Frühere Kerzen zählen nie (kein Blick in die Zukunft).
- Ein Ziel muss auf der Gewinnseite, ein Stop auf der Verlustseite des Einstiegs liegen, sonst
  wird die Zahl ignoriert.
- Berührt eine Kerze Ziel und Stop, zählt der Call als gestoppt (die Kerze sagt nicht, was zuerst kam).
- Die Trefferquote nutzt nur Calls mit Ziel **und** Stop. Calls mit nur einem davon stehen im
  Board, verändern die Quote aber nicht.
- Ein Symbol ohne Kursreihe heißt „no price data“, es wird nichts geschätzt.
- Bedingte Calls („wenn der Tag unter 1945 schließt, short“) werden ab dem Post gemessen, nicht ab
  dem Eintreten der Bedingung. Das ist eine bekannte Grenze.

## Aufruf

```
python scripts/signalgruppe_channels.py read --transcript 11-futures-t-1.md --out calls.json
python scripts/signalgruppe_channels.py evaluate --feed-dir data/signalgruppe_feed \
  --transcript kanal-4.md --bars BTC=btc_1h.csv --bars XAU=paxg_1h.csv \
  --out auswertung.json --board board.txt
```

Kursdateien sind CSV mit `open_time,open,high,low,close` (ISO mit Zeitzone oder Epoch-ms).
TIM hat noch keine Goldquelle; für XAU kann vorerst PAXGUSDT von Binance als Näherung dienen
(Gold-Token, folgt dem Goldpreis, kleine Abweichung möglich).

## Grenzen

- Nichts hier postet in Discord. `--board` schreibt nur den Text für eine spätere Freigabe.
- Calls sind Hypothesen. Eine Trefferquote beschreibt vergangene Calls, sie ist kein Signal und
  keine Empfehlung. Nur Papier, kein Echtgeld.
- Abschriften vom Bildschirm können Zahlen falsch lesen; Chart-Werte sind geschätzt (Quelle `chart`).
