# TIM Research Benchmark Suite

The versioned dataset `benchmarks/market_cases_v1.json` permanently covers
bullish BOS, bearish BOS, rejection/absorption context, failed continuation, and
multi-timeframe conflict. Cases use fixed timestamps and deterministic candles.

Run and write the comparison report:

```bash
.venv/bin/python scripts/run_benchmarks.py
```

The output is `data/benchmarks/latest.json`, including the dataset SHA-256,
expected/actual values, individual results, and aggregate status. It is research
regression evidence only, never live market evidence.

