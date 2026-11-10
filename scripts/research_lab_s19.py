"""Study S19: orderflow thresholds measured on BTC (15m candles from the S8 store, spot 2020-2024).

    python scripts/research_lab_s19.py count    --bars <S8 root> --out DIR --workers 16 --cache DIR   # blind gate (5.1)
    python scripts/research_lab_s19.py evaluate --bars <S8 root> --out DIR --workers 16 --cache DIR   # only after 1.0

Rules: docs/research_lab/studien/S19_ORDERFLOW_SCHWELLEN_BTC_PRAEREGISTRIERUNG.md. Stdlib only; the
holdout from 2025-01-01 is refused before any file is read. Meant for the PS5 (16 threads) with the S8 store
``~/tim-research/data/orderflow_ml_120``; runs on the Mac the same way.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.research_lab.studies import s19  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(s19.main())
