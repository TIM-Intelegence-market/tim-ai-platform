"""Point-in-time external data for BTC research (docs/research_lab/EXTERNAL_DATA.md).

Flow: raw source payload -> ``alfred.parse_bundle`` (normalization and data
quality) -> ``pit.PointInTimeStore`` (what was known when) -> ``events`` and
``align`` (BTC alignment) -> ``replay.run_replay`` (deterministic research
dataset). Nothing here forecasts, scores or trades.
"""
