"""Study S12: reported liquidations versus the estimated liquidation heatmap (lab only).

Pre-registration: ``docs/research_lab/studien/S12_LIQUIDATIONS_HEATMAP_KALIBRIERUNG_PRAEREGISTRIERUNG.md``.

- ``events``: parse Binance ``forceOrder`` and Bybit ``allLiquidation`` messages.
- ``store``: append-only raw files per UTC day, manifests, connection coverage.
- ``collector``: websocket loops that only record (no account, no key, no orders).
- ``snapshots``: frozen heatmap inputs four times a day, recomputable bit for bit.
- ``gate``: outcome-blind count of valid windows for the feasibility gate.

Nothing here trades, writes a plan, changes a score or touches the runtime database.
"""
