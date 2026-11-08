"""Study S18: Kronos path fan for BTC (24h), forward only.

    python scripts/research_lab_s18.py forecast --log FILE --kronos-dir DIR [--device mps]
        # one forecast per symbol for the current 4h slot, appended to FILE; run hourly (idempotent)
    python scripts/research_lab_s18.py count --log FILE --out DIR   # blind: forecasts and outcomes counted
    python scripts/research_lab_s18.py run --log FILE --out DIR     # scores and verdict, only above the gate

`forecast` needs torch and the Kronos code at the pinned commit (own venv on the Mac, see section 6 of the
preregistration). `count` and `run` are stdlib only. Klines come from the public Binance USD-M endpoint and
are never requested before FORWARD_START minus the lookback (no archive, holdout untouched).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.research_lab.studies import s18

KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"
EARLIEST_MS = s18.FORWARD_START_MS - s18.LOOKBACK_H * s18.HOUR_MS


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def fetch(symbol: str, start_ms: int, end_ms: int) -> list[s18.Candle]:
    """Closed 1h candles with open_time in [start, end)."""
    if start_ms < EARLIEST_MS:
        raise SystemExit(f"refused: {symbol} candles before {_iso(EARLIEST_MS)} are not part of S18")
    out: list[s18.Candle] = []
    cur = start_ms
    while cur < end_ms:
        url = f"{KLINES_URL}?symbol={symbol}&interval=1h&limit=1500&startTime={cur}&endTime={end_ms - 1}"
        with urllib.request.urlopen(url, timeout=30) as resp:
            rows = json.load(resp)
        if not rows:
            break
        for r in rows:
            c = s18.Candle(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]), float(r[7]))
            if c.close_time <= int(time.time() * 1000):  # only closed candles
                out.append(c)
        cur = int(rows[-1][0]) + s18.HOUR_MS
    return out


def read_log(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            out.append({"broken": True})
    return out


def _sha(p: str) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def cmd_forecast(args: argparse.Namespace) -> int:
    now = int(time.time() * 1000)
    t0 = s18.slot_of(now)
    if not s18.is_forward_time(t0):
        print(f"{_iso(t0)}: outside the forward window, nothing to do")
        return 0
    if now - t0 > s18.MAX_LATE_MS:
        print(f"{_iso(t0)}: too late, slot missed (no backfill)")
        return 0
    log = Path(args.log)
    done = {(r.get("symbol"), r.get("t0_ms")) for r in read_log(log)}
    todo = [s for s in s18.SYMBOLS if (s, t0) not in done]
    if not todo:
        print(f"{_iso(t0)}: already written")
        return 0

    import numpy as np
    import pandas as pd
    import torch
    from huggingface_hub import hf_hub_download

    sys.path.insert(0, str(Path(args.kronos_dir).resolve()))
    head = subprocess.run(["git", "-C", args.kronos_dir, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if head != s18.KRONOS_COMMIT:
        raise SystemExit(f"refused: Kronos code at {head}, pinned {s18.KRONOS_COMMIT}")
    from model import Kronos, KronosPredictor, KronosTokenizer

    m_file = hf_hub_download(s18.MODEL_REPO, "model.safetensors", revision=s18.MODEL_REVISION)
    t_file = hf_hub_download(s18.TOKENIZER_REPO, "model.safetensors", revision=s18.TOKENIZER_REVISION)
    if _sha(m_file) != s18.MODEL_SHA256 or _sha(t_file) != s18.TOKENIZER_SHA256:
        raise SystemExit("refused: weight checksum differs from the pin")
    tok = KronosTokenizer.from_pretrained(s18.TOKENIZER_REPO, revision=s18.TOKENIZER_REVISION).eval()
    mod = Kronos.from_pretrained(s18.MODEL_REPO, revision=s18.MODEL_REVISION).eval()
    pred = KronosPredictor(mod, tok, device=args.device, max_context=s18.CONTEXT_H)

    for symbol in todo:
        candles = fetch(symbol, t0 - s18.CONTEXT_H * s18.HOUR_MS, t0)
        hist = s18.history_before(candles, t0, s18.CONTEXT_H)
        if hist is None:
            rec = {"symbol": symbol, "t0_ms": t0, "t0": _iso(t0), "missing": "context incomplete",
                   "written_ms": int(time.time() * 1000)}
        else:
            df = pd.DataFrame([[c.open, c.high, c.low, c.close, c.volume, c.amount] for c in hist],
                              columns=["open", "high", "low", "close", "volume", "amount"])
            x_ts = pd.Series(pd.to_datetime([c.open_time for c in hist], unit="ms"))
            y_ts = pd.Series(pd.date_range(x_ts.iloc[-1] + pd.Timedelta("1h"), periods=s18.HORIZON_H, freq="1h"))
            torch.manual_seed(s18.SEED)
            t_start = time.time()
            paths = pred.predict_batch([df] * s18.N_PATHS, [x_ts] * s18.N_PATHS, [y_ts] * s18.N_PATHS,
                                       pred_len=s18.HORIZON_H, T=s18.TEMPERATURE, top_k=s18.TOP_K, top_p=s18.TOP_P,
                                       sample_count=1, verbose=False)
            closes = np.stack([p["close"].to_numpy() for p in paths])
            c0 = hist[-1].close
            logret = 100 * np.log(closes / c0)
            rec = {"symbol": symbol, "t0_ms": t0, "t0": _iso(t0), "close0": c0,
                   "kronos_final_logret": [round(float(v), 6) for v in logret[:, -1]],
                   "kronos_paths_logret": [[round(float(v), 4) for v in row] for row in logret],
                   "seconds": round(time.time() - t_start, 1), "device": args.device,
                   "kronos_commit": head, "model_sha256": s18.MODEL_SHA256, "tokenizer_sha256": s18.TOKENIZER_SHA256,
                   "torch": torch.__version__, "written_ms": int(time.time() * 1000)}
        with log.open("a") as f:
            f.write(json.dumps(rec, separators=(",", ":")) + "\n")
        print(symbol, _iso(t0), "missing" if "missing" in rec else f"{rec['seconds']} s")
    return 0


def _load(args: argparse.Namespace) -> tuple[dict[str, list[dict]], dict[str, list[s18.Candle]], dict]:
    recs = read_log(Path(args.log))
    by_symbol: dict[str, list[dict]] = {s: [] for s in s18.SYMBOLS}
    info = {"lines": len(recs), "invalid": 0, "missing_context": 0, "duplicates": 0}
    seen = set()
    for r in recs:
        if "missing" in r:
            info["missing_context"] += 1
            continue
        if not s18.valid_record(r) or r.get("symbol") not in by_symbol:
            info["invalid"] += 1
            continue
        key = (r["symbol"], r["t0_ms"])
        if key in seen:
            info["duplicates"] += 1  # first one counts
            continue
        seen.add(key)
        by_symbol[r["symbol"]].append(r)
    now = int(time.time() * 1000)
    candles = {}
    for s, rs in by_symbol.items():
        if rs:
            last = max(r["t0_ms"] for r in rs) + s18.HORIZON_H * s18.HOUR_MS
            candles[s] = fetch(s, min(r["t0_ms"] for r in rs) - s18.LOOKBACK_H * s18.HOUR_MS, min(last, now))
    return by_symbol, candles, info


def _header(args: argparse.Namespace) -> dict:
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "unknown"
    return {"study": "S18", "commit": commit, "created": _iso(int(time.time() * 1000)), "log": str(args.log),
            "forward_start": _iso(s18.FORWARD_START_MS), "gate": s18.GATE_MIN_FORECASTS}


def cmd_count(args: argparse.Namespace) -> int:
    """Blind: how many forecasts are logged and how many have a complete outcome. No score."""
    by_symbol, candles, info = _load(args)
    counts = {}
    for s, rs in by_symbol.items():
        c = candles.get(s, [])
        complete = sum(1 for r in rs if s18.outcome(c, r["t0_ms"]) is not None
                       and s18.history_before(c, r["t0_ms"], s18.LOOKBACK_H) is not None)
        counts[s] = {"logged": len(rs), "with_outcome": complete}
    out = {**_header(args), **info, "counts": counts,
           "gate_reached": s18.gate(counts[s18.PRIMARY]["with_outcome"])}
    _write(args, "count", out)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    by_symbol, candles, info = _load(args)
    scored = {s: [x for x in (s18.score(r, candles.get(s, [])) for r in rs) if x is not None]
              for s, rs in by_symbol.items()}
    if not s18.gate(len(scored[s18.PRIMARY])):
        print(f"refused: {len(scored[s18.PRIMARY])} scored {s18.PRIMARY} forecasts, gate {s18.GATE_MIN_FORECASTS}")
        return 2
    out = {**_header(args), **info, "verdict": s18.verdict(scored[s18.PRIMARY]),
           "describe": {s: s18.describe(v) for s, v in scored.items()}}
    _write(args, "run", out)
    return 0


def _write(args: argparse.Namespace, kind: str, out: dict) -> None:
    d = Path(args.out)
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    p = d / f"s18_{kind}_{stamp}.json"
    p.write_text(json.dumps(out, indent=2, default=lambda o: o if not isinstance(o, float) or math.isfinite(o) else None))
    print(p)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("forecast")
    f.add_argument("--log", required=True)
    f.add_argument("--kronos-dir", required=True)
    f.add_argument("--device", default="mps", choices=["mps", "cpu"])
    for name in ("count", "run"):
        p = sub.add_parser(name)
        p.add_argument("--log", required=True)
        p.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    return {"forecast": cmd_forecast, "count": cmd_count, "run": cmd_run}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
