# TIM v1 Reproducibility Report

## Method

An isolated, explicitly `TEST_ONLY` raw aggTrade fixture traversed parsing, candle aggregation, orderflow metrics, observation generation, case creation and forward validation ten times. Inputs, dataset, every stage, complete output and replay were canonically serialized and SHA-256 hashed.

## Result

All 10/10 runs were identical.

- Dataset: `ee7c4b770368a035a816f306943d9a0211e55d538b625774192cd23beac5d8c7`
- Input: `71417848d23c90871f484973571cab2da54e57967358367fa64560b8bd22d8e4`
- Output: `dbe3a06dc91f7696687639b398ea95141a9306f50b516428a31407f6f5fb2c62`
- Replay: `c0c2e1fc8c1eb7e3be1fe35da0cbeebdf238e3c65b1cc2ba5b38f94552d30bd1`

Stage hashes are recorded in `artifacts/audits/tim_v1_validation_results.json`; individual runs are in `tim_v1_pipeline_runs.jsonl`.

## Scope

The fixture is not real-market evidence and is used only to verify lifecycle behavior. Live database integrity checks separately found zero duplicate aggTrade/candle keys and zero future rows.

## Reproducibility boundary

Scientific content and identifiers are deterministic. Wall-clock operational/report timestamps and `Observation.created_at` are deliberately outside the canonical scientific hash and are not byte-reproducible unless an explicit timestamp is injected.
