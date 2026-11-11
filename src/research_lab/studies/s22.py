"""S22: does the Chart-Urteil sort trades? Candle rules R1-R5 of chart-urteil/1.0 on BTCUSDT 1h, 2020 to 2024.

Rules: docs/research_lab/studien/S22_CHART_URTEIL_RUECKBLICK_PRAEREGISTRIERUNG_ENTWURF.md (version 0.1).
Observation study on hypothetical standard trades, no register slot; the holdout from 2025-01-01 is never loaded.

    python -m src.research_lab.studies.s22 count    --root data/research_lab --out DIR [--fetch] [--workers N]
    python -m src.research_lab.studies.s22 evaluate --root data/research_lab --out DIR [--workers N]

The live shadow (src/dashboard/chart_verdict.py, PR #217) weighs every 15m/1h paper plan with fixed rules. Its
comparison needs 30 closed plans and 28 days. S22 asks the same question on history for the part of the rules that
candles can rebuild: value edge (R1), 1h/4h structure (R2), stop behind the strong low/high (R3), levels before the
target (R4), 1h trend lines (R5). Absorption, wave and CVD (R6-R8) need the live order flow and are not tested.

Every closed 1h candle is one moment. At each moment a Long and a Short are opened at the close with a fixed stop
(1 ATR14) and target (2 ATR14) and at most 48 hours. ``chart_verdict.chart_lage`` and ``judge`` are called
unchanged, on the candles closed by then. The question: is the net R of NEHMEN above the net R of AUSLASSEN (H1)
and above the net R of all trades (H2)? Nothing is fitted; training (to 2022) is a first look, the verdict counts
in the validation (2023-2024).

``count`` is results-blind (moments and decisions, no outcome). ``evaluate`` refuses to run while ``VERSION`` is
a draft.
"""
from __future__ import annotations

import argparse
import json
import random
import time
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import multiprocessing
from pathlib import Path

from src.research_lab.data.parse import Kline
from src.research_lab.protocol import HOLDOUT_START_MS, VALIDATION_START_MS
from src.research_lab.stats.inference import holm
from src.research_lab.studies.s20 import HOUR, atr_series, week_of

VERSION = "0.1"
SEED = 22
SYMBOL = "BTCUSDT"
FIRST_MONTH = (2019, 10)  # warm-up: 60 days of 1h candles before the first moment
LAST_MONTH = (2024, 12)
EVENT_START_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
HALF = HOUR // 2
WINDOW_1H = 60 * 24  # candles handed to the chart functions: 60 days of 1h ...
WINDOW_30M = 30 * 48  # ... and 30 days of 30m (previous day and week, naked POCs)
STOP_ATR = 1.0
TARGET_ATR = 2.0
HORIZON = 48  # hours; then the trade leaves at the close
COST_BPS_PER_SIDE = 5.0  # as the paper shadows (orderflow_shadow.COST_R_PER_SIDE_BPS)
DIRECTIONS = ("LONG", "SHORT")
RULES = ("R1", "R2", "R3", "R4", "R5")
SECTIONS = {"training": (EVENT_START_MS, VALIDATION_START_MS), "validierung": (VALIDATION_START_MS, HOLDOUT_START_MS)}
MIN_TRADES = 300  # per group (NEHMEN, AUSLASSEN) and section
MIN_WEEKS = 50
MIN_DIFF_R = 0.05
ALPHA = 0.05
HOLM_M = 2
BOOT_DRAWS = 9_999
BLOCK_WEEKS = 4
SHIFT_DRAWS = 199
MIN_SHIFT = 14 * 24  # moments; a shift below two weeks would keep the trend the rules read


@dataclass(frozen=True, slots=True)
class Row:
    time: int  # close of the 1h candle = entry, UTC ms
    section: str
    direction: str
    score: int
    decision: str
    sides: tuple[int, ...]  # per rule in RULES: +1 points for, -1 against, 0 none (net of several points)
    net_r: float | None  # None in the results-blind count


def section_of(time_ms: int) -> str | None:
    return next((name for name, (lo, hi) in SECTIONS.items() if lo <= time_ms < hi), None)


def _candle(bar: Kline, tf: str, step: int) -> dict:
    opened = datetime.fromtimestamp(bar.open_time / 1000, tz=timezone.utc)
    closed = datetime.fromtimestamp((bar.open_time + step) / 1000, tz=timezone.utc)
    return {"symbol": SYMBOL, "timeframe": tf, "open_time": opened, "close_time": closed, "open": bar.open,
            "high": bar.high, "low": bar.low, "close": bar.close, "volume": bar.volume}


def outcome(bars: Sequence[Kline], i: int, direction: str, atr: float) -> float | None:
    """Net R of the standard trade opened at the close of ``bars[i]``. Stop first when one candle holds both.

    None when the 48 following candles are not all there (gap or end of data): nothing is filled in.
    """
    if i + HORIZON >= len(bars) or bars[i + HORIZON].open_time - bars[i].open_time != HORIZON * HOUR:
        return None
    entry = bars[i].close
    risk = STOP_ATR * atr
    sign = 1.0 if direction == "LONG" else -1.0
    stop, target = entry - sign * risk, entry + sign * TARGET_ATR * atr
    exit_price = bars[i + HORIZON].close
    for bar in bars[i + 1:i + HORIZON + 1]:
        if (bar.low <= stop) if sign > 0 else (bar.high >= stop):
            exit_price = stop
            break
        if (bar.high >= target) if sign > 0 else (bar.low <= target):
            exit_price = target
            break
    gross = sign * (exit_price - entry) / risk
    return gross - (entry + exit_price) * COST_BPS_PER_SIDE / 10_000 / risk


def moments(bars: Sequence[Kline], atrs: Sequence[float | None]) -> list[int]:
    """Indices of the 1h candles that open a trade: inside a section, full warm-up without a gap, horizon inside
    the same section (no trade of the training runs into the validation, none into the holdout)."""
    out = []
    for i in range(WINDOW_1H - 1, len(bars)):
        close_time = bars[i].open_time + HOUR
        section = section_of(close_time)
        if section is None or atrs[i] is None or atrs[i] <= 0:
            continue
        if close_time + HORIZON * HOUR > SECTIONS[section][1]:
            continue
        if bars[i].open_time - bars[i - WINDOW_1H + 1].open_time != (WINDOW_1H - 1) * HOUR:
            continue
        if i + HORIZON >= len(bars) or bars[i + HORIZON].open_time - bars[i].open_time != HORIZON * HOUR:
            continue  # the 48 candles after it are not all there (times only, no price is read)
        out.append(i)
    return out


def candles(bars: Sequence[Kline], tf: str, step: int) -> list[dict]:
    return [_candle(b, tf, step) for b in bars]


def verdicts(bars_1h: Sequence[Kline], candles_1h: Sequence[dict], candles_30m: Sequence[dict], opens_30m: Sequence[int],
             i: int, atr: float) -> dict[str, dict]:
    """Chart-Urteil for a Long and a Short at the close of ``bars_1h[i]``, from the live code, candles only.

    The chart functions get nothing after that close: 1h candles up to ``i``, 30m candles closed by then.
    """
    from src.dashboard import chart_verdict

    close_time = bars_1h[i].open_time + HOUR
    end_30m = bisect_right(opens_30m, close_time - HALF)  # 30m candles closed by then
    series = {"1h": candles_1h[i - WINDOW_1H + 1:i + 1], "30m": candles_30m[max(0, end_30m - WINDOW_30M):end_30m]}
    at = datetime.fromtimestamp(close_time / 1000, tz=timezone.utc)
    chart = chart_verdict.chart_lage(series, at)
    entry = bars_1h[i].close
    out = {}
    for direction in DIRECTIONS:
        sign = 1.0 if direction == "LONG" else -1.0
        out[direction] = chart_verdict.judge(direction, entry, chart, entry - sign * STOP_ATR * atr,
                                             entry + sign * TARGET_ATR * atr)
    return out


def _sides(verdict: Mapping) -> tuple[int, ...]:
    from src.dashboard.chart_verdict import FOR

    net = dict.fromkeys(RULES, 0)
    for point in verdict["points"]:
        if point["rule"] in net:
            net[point["rule"]] += 1 if point["side"] == FOR else -1
    return tuple((v > 0) - (v < 0) for v in net.values())


_STATE: dict = {}


def _rows_for(i: int) -> list[Row]:
    bars, atrs, with_outcome = _STATE["bars_1h"], _STATE["atrs"], _STATE["with_outcome"]
    close_time = bars[i].open_time + HOUR
    both = verdicts(bars, _STATE["candles_1h"], _STATE["candles_30m"], _STATE["opens_30m"], i, atrs[i])
    rows = []
    for direction in DIRECTIONS:
        net_r = outcome(bars, i, direction, atrs[i]) if with_outcome else None
        if with_outcome and net_r is None:
            continue
        v = both[direction]
        rows.append(Row(close_time, section_of(close_time), direction, v["score"], v["decision"], _sides(v), net_r))
    return rows


def build_rows(bars_1h: Sequence[Kline], bars_30m: Sequence[Kline], *, with_outcome: bool, workers: int = 1) -> list[Row]:
    atrs = atr_series(bars_1h)
    _STATE.update(bars_1h=bars_1h, candles_1h=candles(bars_1h, "1h", HOUR), candles_30m=candles(bars_30m, "30m", HALF),
                  opens_30m=[b.open_time for b in bars_30m], atrs=atrs, with_outcome=with_outcome)
    todo = moments(bars_1h, atrs)
    if workers > 1:
        # The workers read _STATE, so they must be forked: Python 3.14 starts them with forkserver by default
        # (empty module state; the first PS5 count run ended with KeyError 'bars_1h').
        with multiprocessing.get_context("fork").Pool(workers) as pool:
            parts = pool.map(_rows_for, todo, chunksize=200)
    else:
        parts = [_rows_for(i) for i in todo]
    return [row for part in parts for row in part]


# -- statistics ---------------------------------------------------------------------------------------


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _group(rows: Sequence[Row], name: str) -> list[Row]:
    return list(rows) if name == "ALLE" else [r for r in rows if r.decision == name]


def diff_bootstrap_p(rows: Sequence[Row], a: str, b: str, *, seed: str, draws: int = BOOT_DRAWS,
                     block: int = BLOCK_WEEKS) -> float | None:
    """One-sided p for H0 mean(a) - mean(b) <= 0: moving blocks of ``block`` consecutive weeks."""
    cells: dict[int, list[float]] = {}
    for name, column in ((a, 0), (b, 2)):
        for row in _group(rows, name):
            cell = cells.setdefault(week_of(row.time), [0.0, 0.0, 0.0, 0.0])
            cell[column] += 1
            cell[column + 1] += row.net_r
    weeks = [cells[w] for w in sorted(cells)]
    if len(weeks) < 2:
        return None
    width = min(block, len(weeks))
    starts = len(weeks) - width + 1
    rng = random.Random(f"{SEED}:{seed}")
    at_or_below = 0
    for _ in range(draws):
        total = [0.0, 0.0, 0.0, 0.0]
        covered = 0
        while covered < len(weeks):
            s = rng.randrange(starts)
            for cell in weeks[s:s + width]:
                for k in range(4):
                    total[k] += cell[k]
            covered += width
        if total[0] == 0 or total[2] == 0 or total[1] / total[0] - total[3] / total[2] <= 0:
            at_or_below += 1
    return (at_or_below + 1) / (draws + 1)


def diff(rows: Sequence[Row], a: str, b: str) -> float | None:
    ma, mb = _mean([r.net_r for r in _group(rows, a)]), _mean([r.net_r for r in _group(rows, b)])
    return None if ma is None or mb is None else ma - mb


def shift_test(rows: Sequence[Row], observed: float, *, draws: int = SHIFT_DRAWS) -> dict:
    """Luck test: the decisions are moved in a circle against the outcomes (per direction, by whole moments).

    A shift keeps how often and in which runs the rules say NEHMEN, and breaks their link to what came after.
    """
    from src.dashboard.chart_verdict import SKIP, TAKE

    by_direction = {d: sorted((r for r in rows if r.direction == d), key=lambda r: r.time) for d in DIRECTIONS}
    n = min(len(v) for v in by_direction.values())
    if n < 2 * MIN_SHIFT + 1:
        return {"getestet": False, "grund": f"weniger als {2 * MIN_SHIFT + 1} Momente"}
    rng = random.Random(f"{SEED}:shift")
    at_or_above = 0
    for _ in range(draws):
        offset = rng.randrange(MIN_SHIFT, n - MIN_SHIFT + 1)
        take, skip = [], []
        for series in by_direction.values():
            for j, row in enumerate(series):
                decision = series[(j + offset) % len(series)].decision
                if decision == TAKE:
                    take.append(row.net_r)
                elif decision == SKIP:
                    skip.append(row.net_r)
        if take and skip and _mean(take) - _mean(skip) >= observed:
            at_or_above += 1
    return {"getestet": True, "verschiebungen": draws, "p": (at_or_above + 1) / (draws + 1)}


def describe(rows: Sequence[Row]) -> dict:
    """Mean net R by decision, by score and per rule (for / against). No test, for the report only."""
    from src.dashboard.chart_verdict import NEUTRAL, SKIP, TAKE

    def cell(values: Sequence[float]) -> dict:
        return {"n": len(values), "mittel_netto_r": round(_mean(values), 4) if values else None}

    by_score: dict[int, list[float]] = {}
    for r in rows:
        by_score.setdefault(r.score, []).append(r.net_r)
    rules = {}
    for k, rule in enumerate(RULES):
        rules[rule] = {"dafuer": cell([r.net_r for r in rows if r.sides[k] > 0]),
                       "dagegen": cell([r.net_r for r in rows if r.sides[k] < 0])}
    return {"alle": cell([r.net_r for r in rows]),
            "entscheidung": {name: cell([r.net_r for r in rows if r.decision == name]) for name in (TAKE, NEUTRAL, SKIP)},
            "score": {str(s): cell(v) for s, v in sorted(by_score.items())}, "regeln": rules,
            "wochen": len({week_of(r.time) for r in rows})}


def count(rows: Sequence[Row]) -> dict:
    """Results-blind: moments, trades and decisions per section. No outcome is read."""
    from src.dashboard.chart_verdict import NEUTRAL, SKIP, TAKE

    out = {}
    for name in SECTIONS:
        part = [r for r in rows if r.section == name]
        decisions = {d: sum(1 for r in part if r.decision == d) for d in (TAKE, NEUTRAL, SKIP)}
        out[name] = {"momente": len({r.time for r in part}), "trades": len(part), "entscheidungen": decisions,
                     "wochen": len({week_of(r.time) for r in part}),
                     "gate": decisions[TAKE] >= MIN_TRADES and decisions[SKIP] >= MIN_TRADES}
    out["gate"] = all(out[name]["gate"] for name in SECTIONS) and out["validierung"]["wochen"] >= MIN_WEEKS
    return out


def evaluate(rows: Sequence[Row], *, boot_draws: int = BOOT_DRAWS, shift_draws: int = SHIFT_DRAWS) -> dict:
    from src.dashboard.chart_verdict import RULESET, SKIP, TAKE

    if VERSION.startswith("0"):
        raise SystemExit(f"S22 {VERSION} ist ein Entwurf: erst nach dem Einfrieren als 1.0 auswerten")
    train = [r for r in rows if r.section == "training"]
    valid = [r for r in rows if r.section == "validierung"]
    gate = count(rows)
    result = {"regelwerk": RULESET, "gate": gate, "training": describe(train), "validierung": describe(valid)}
    if not gate["gate"]:
        result["urteil"] = "nicht testbar (Gate)"
        return result
    h1, h2 = diff(valid, TAKE, SKIP), diff(valid, TAKE, "ALLE")
    p = {"H1": diff_bootstrap_p(valid, TAKE, SKIP, seed="H1", draws=boot_draws),
         "H2": diff_bootstrap_p(valid, TAKE, "ALLE", seed="H2", draws=boot_draws)}
    passed = holm({k: v for k, v in p.items() if v is not None}, HOLM_M, ALPHA)
    shift = shift_test(valid, h1, draws=shift_draws)
    train_h1 = diff(train, TAKE, SKIP)
    checks = {
        "training_gleiches_vorzeichen": train_h1 is not None and train_h1 > 0,
        "h1_abstand": h1 >= MIN_DIFF_R, "h1_holm": "H1" in passed, "h2_holm": "H2" in passed,
        "glueckstest": bool(shift.get("getestet")) and shift["p"] < ALPHA,
    }
    take_mean = result["validierung"]["entscheidung"][TAKE]["mittel_netto_r"]
    result.update(
        h1={"nehmen_minus_auslassen_r": round(h1, 4), "p": p["H1"], "training": round(train_h1, 4) if train_h1 is not None else None},
        h2={"nehmen_minus_alle_r": round(h2, 4), "p": p["H2"]}, glueckstest=shift, kriterien=checks,
        nehmen_positiv_nach_kosten=take_mean is not None and take_mean > 0,
        urteil="BESTANDEN (Kandidat)" if all(checks.values()) else "NICHT BESTANDEN",
    )
    return result


# -- data and CLI --------------------------------------------------------------------------------------


def refs(interval: str):
    from src.research_lab.data.archive import ArchiveRef, Dataset, Market
    from src.research_lab.data.store import months
    return [ArchiveRef(Market.SPOT, Dataset.KLINES, y, m, interval=interval, symbol=SYMBOL) for y, m in months(FIRST_MONTH, LAST_MONTH)]


def load(root: Path, *, fetch: bool = False) -> tuple[list[Kline], list[Kline], str]:
    from src.research_lab.data.store import ArchiveStore
    store = ArchiveStore(root)
    out = []
    for interval in ("1h", "30m"):
        rs = refs(interval)
        if fetch:
            for ref in rs:
                store.fetch(ref)
        out.append([k for k in store.load_klines(rs) if k.open_time < HOLDOUT_START_MS])
    return out[0], out[1], store.dataset_hash(refs("1h") + refs("30m"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="s22")
    parser.add_argument("step", choices=("count", "evaluate"))
    parser.add_argument("--root", type=Path, default=Path("data/research_lab"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fetch", action="store_true", help="fehlende Monatsdateien von data.binance.vision laden (nur bis 2024-12)")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args(argv)
    if args.step == "evaluate" and VERSION.startswith("0"):
        raise SystemExit(f"S22 {VERSION} ist ein Entwurf: erst nach dem Einfrieren als 1.0 auswerten")
    bars_1h, bars_30m, digest = load(args.root, fetch=args.fetch)
    rows = build_rows(bars_1h, bars_30m, with_outcome=args.step == "evaluate", workers=args.workers)
    stamp = time.strftime("%Y-%m-%dT%H%MZ", time.gmtime())
    result = {"studie": "S22", "version": VERSION, "seed": SEED, "datensatz_sha256": digest,
              "kerzen": {"1h": len(bars_1h), "30m": len(bars_30m)}, "zaehllauf": count(rows)}
    if args.step == "evaluate":
        result["auswertung"] = evaluate(rows)
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"s22_{args.step}_{stamp}.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(path)
    print(json.dumps(result["zaehllauf"], ensure_ascii=False))
    if "auswertung" in result:
        print(result["auswertung"]["urteil"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
