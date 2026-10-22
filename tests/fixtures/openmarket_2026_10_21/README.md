# OpenMarket-Antworten vom 21.10.2026

Abgerufen auf dem Mac mit `scripts/openmarket_capture_samples.py` (nur lesend), BINANCE_FUTURES BTCUSDT,
`interval=HOUR`, `from=1792562400`, `period=21600`.

- `OPEN_INTEREST_AGG.json`, `FUNDING_RATE_AGG.json`, `LIQUIDATION_AGG.json`: vollständige Antworten.
- `VOLUME_PROFILE_AGG.json`: echte Hülle und echtes Punktformat (`profile` = `[Preis, Buy, Sell, ...]`,
  Preisschritt 5, neueste Stunde zuerst). Echt sind die ersten fünf Zeilen des ersten Punkts (1792584000)
  und die ersten zwei Zeilen des zweiten (1792580400). Alle übrigen Zeilen und der dritte Punkt sind
  **synthetisch**, damit der Test eine eindeutige POC und Value Area hat (Original 19,8 KB, 7 Punkte).
- `TPO_AGG`: HTTP 500 `{"code":13,"message":"internal error"}`, keine Datei.

Keine Zugangsdaten in diesen Dateien.
