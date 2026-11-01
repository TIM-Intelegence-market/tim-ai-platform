"""Frozen heatmap states four times a day (S12, package L2; pre-registration 3.2, 4.2, 4.3).

At each window start t (00:00, 06:00, 12:00, 18:00 UTC) the collector fetches, at t + 120 s,
exactly what the Control Center fetches (``src.dashboard.liquidation_data``: Binance futures open
interest history and 30 min klines, 500 periods) and stores the **raw answers**. Everything else
is recomputed from them, so a stored state can be checked bit for bit (``verify``):

- candles opened after t - 1800 s (the running one) and OI stamps after t - 1800 s are dropped
  (the meaning of a stamp, state at that moment or at the end of its period, is not documented;
  observed 01.11.2026: at t + 120 s the newest stamp is t - 1800);
- model ``tim``: ``build_heatmap`` unchanged, but without the display filters
  (``min_share = 0``, no cell limit);
- model ``baseline``: same call and candles, OI replaced at the same stamps by ``1 + rank``;
- validity: OI stamps on the 30 min grid, equal ``periods_with_oi`` >= 450 in both models,
  at least 10 active rows per side in both models, fetched no later than t + 15 min.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from src.dashboard import liquidation_data
from src.liquidation_map.heatmap import Candle, build_heatmap

FORMAT = "s12-snapshot/1"
SYMBOL = "BTCUSDT"
PERIOD_SECONDS = liquidation_data.PERIOD_SECONDS
WINDOW_HOURS = 6
FETCH_DELAY = timedelta(seconds=120)
MAX_FETCH_DELAY = timedelta(minutes=15)
MIN_PERIODS_WITH_OI = 450
TOP_ROWS = 10
NO_CELL_LIMIT = 10**9

Fetch = Callable[[str, Mapping[str, str]], Any]


def window_start(moment: datetime) -> datetime:
    """The 6 h window start at or before ``moment`` (UTC)."""
    moment = moment.astimezone(timezone.utc)
    return moment.replace(hour=moment.hour - moment.hour % WINDOW_HOURS, minute=0, second=0, microsecond=0)


def next_window_start(moment: datetime) -> datetime:
    start = window_start(moment)
    return start if start == moment.astimezone(timezone.utc) else start + timedelta(hours=WINDOW_HOURS)


def snapshot_path(root: Path, t: datetime) -> Path:
    t = t.astimezone(timezone.utc)
    return root / "snapshots" / t.date().isoformat() / f"{t:%H%M}.json.gz"


def code_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parent,
                             capture_output=True, text=True, timeout=10, check=True)
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _model(candles: list[Candle], oi: Mapping[int, float], t: datetime) -> dict[str, Any]:
    return build_heatmap(candles, oi, t, symbol=SYMBOL, period_seconds=PERIOD_SECONDS,
                         min_share=0.0, max_cells=NO_CELL_LIMIT)


def active_rows(model: Mapping[str, Any], side: str) -> dict[float, float]:
    """Active cells of one side on the right side of the price (section 4.2, step 2)."""
    last, step = float(model["last"]), float(model["step"])
    rows: dict[float, float] = {}
    for cell in model["cells"]:
        if cell["end"] is not None or cell["side"] != side:
            continue
        price = float(cell["price"])
        if float(cell["usd"]) <= 0:
            continue  # rounded to 0.00 in build_heatmap: no estimate left in this row
        if (side == "long" and price + step <= last) or (side == "short" and price > last):
            rows[price] = rows.get(price, 0.0) + float(cell["usd"])
    return rows


def top_rows(model: Mapping[str, Any], side: str, n: int = TOP_ROWS) -> list[float]:
    """The n strongest active rows; ties go to the row nearer the price (section 4.2, step 3)."""
    last = float(model["last"])
    rows = active_rows(model, side)
    return sorted(rows, key=lambda row: (-rows[row], abs(row - last)))[:n]


def compute(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Both models and the validity of a stored state, from its raw answers only."""
    t = datetime.fromisoformat(raw["t"])
    t_s = int(t.timestamp())
    candles = [c for c in liquidation_data.parse_candles(raw["klines"]) if c.time <= t_s - PERIOD_SECONDS]
    # OI stamps only up to t - 1800: whether a stamp means the state at that moment or at the end
    # of its 30 min period is not documented, so the stricter reading rules out any look-ahead.
    oi = {ts: v for ts, v in liquidation_data.parse_open_interest(raw["open_interest"]).items()
          if ts <= t_s - PERIOD_SECONDS}
    reasons = []
    fetched = datetime.fromisoformat(raw["fetched_at"])
    if fetched - t > MAX_FETCH_DELAY:
        reasons.append(f"fetched {int((fetched - t).total_seconds())} s after t")
    if len(candles) < 2 or len(oi) < 2:
        return {"valid": False, "reasons": reasons + ["fewer than two candles or OI stamps"], "tim": None, "baseline": None}
    off_grid = sorted(ts for ts in oi if ts % PERIOD_SECONDS)
    if off_grid:
        reasons.append(f"{len(off_grid)} OI stamps not on the 30 min grid")
    baseline_oi = {ts: 1.0 + rank for rank, ts in enumerate(sorted(oi))}
    tim, baseline = _model(candles, oi, t), _model(candles, baseline_oi, t)
    if tim["periods_with_oi"] != baseline["periods_with_oi"]:
        reasons.append("periods_with_oi differs between the models")
    if tim["periods_with_oi"] < MIN_PERIODS_WITH_OI:
        reasons.append(f"periods_with_oi {tim['periods_with_oi']} < {MIN_PERIODS_WITH_OI}")
    for name, model in (("tim", tim), ("baseline", baseline)):
        for side in ("long", "short"):
            if len(active_rows(model, side)) < TOP_ROWS:
                reasons.append(f"{name}: fewer than {TOP_ROWS} active {side} rows")
    return {"valid": not reasons, "reasons": reasons, "tim": tim, "baseline": baseline}


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def take(root: Path, t: datetime, fetch: Fetch | None = None, now: Callable[[], datetime] | None = None) -> Path:
    """Fetch and store the state for window start ``t``; an existing file is never replaced."""
    t = t.astimezone(timezone.utc)
    if window_start(t) != t:
        raise ValueError(f"{t.isoformat()} is not a 6 h window start")
    path = snapshot_path(root, t)
    if path.exists():
        return path
    fetch = fetch or liquidation_data._fetch_json
    now = now or (lambda: datetime.now(timezone.utc))
    params = {"symbol": SYMBOL, "period": liquidation_data.PERIOD, "limit": str(liquidation_data.LIMIT)}
    raw_oi = fetch("/futures/data/openInterestHist", params)
    raw_k = fetch("/fapi/v1/klines", {"symbol": SYMBOL, "interval": liquidation_data.PERIOD,
                                       "limit": str(liquidation_data.LIMIT)})
    raw = {"format": FORMAT, "study": "S12", "t": t.isoformat(), "fetched_at": now().isoformat(),
           "source": liquidation_data.BINANCE_FUTURES, "params": params, "code_commit": code_commit(),
           "open_interest": raw_oi, "klines": raw_k}
    result = compute(raw)
    record = {**raw, "raw_sha256": _digest({"open_interest": raw_oi, "klines": raw_k}),
              "valid": result["valid"], "reasons": result["reasons"], "tim": result["tim"],
              "baseline": result["baseline"], "result_sha256": _digest(result)}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as handle:
        json.dump(record, handle, sort_keys=True, separators=(",", ":"))
    tmp.replace(path)
    return path


def load(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def verify(path: Path) -> list[str]:
    """Problems of a stored state; empty when raw hash and recomputed result match."""
    record = load(path)
    problems = []
    if record.get("format") != FORMAT:
        problems.append(f"unknown format {record.get('format')!r}")
    if _digest({"open_interest": record["open_interest"], "klines": record["klines"]}) != record.get("raw_sha256"):
        problems.append("raw answers changed")
    result = compute(record)
    if _digest(result) != record.get("result_sha256"):
        problems.append("recomputed result differs")
    stored = {k: record.get(k) for k in ("valid", "reasons", "tim", "baseline")}
    if _digest(stored) != _digest(result):
        problems.append("stored result differs from recomputation")
    return problems
