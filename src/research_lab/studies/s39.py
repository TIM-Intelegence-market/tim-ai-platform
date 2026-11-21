"""S39 - Nach großen Bewegungen: Fortsetzung oder Umkehr? (Präregistrierung 1.0, Bauplan "Preisbewegungen erklären" P5).

Rules frozen in docs/research_lab/studien/S39_BEWEGUNG_FORTSETZUNG_UMKEHR_PRAEREGISTRIERUNG.md. Describes only: no
trade, no cost, no rule change. Moves are found with the live detector ``move-context/0.2`` on BTCUSDT hour candles
from the S8 minute bars (same store and loader as the calibration), typed by direction and by whether the spot
taker flow pushed in the direction of the move, and the move's direction-signed return over the next 24 hours is
compared with the same number of random hours (same sign), Holm over the four types.

Usage (PS5): ``PYTHONPATH=. ../.venv/bin/python -m src.research_lab.studies.s39 --root DATA --out DIR [--phase train|valid]``
"""

from __future__ import annotations

import argparse
import json
import random
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.dashboard import move_context as M
from src.research_lab.studies.move_calibration import four_hour_rows
from src.research_lab.studies.s35a import holm_adjusted

VERSION = "1.0"
TRAIN = (date(2020, 1, 1), date(2023, 12, 31))
VALID = (date(2024, 1, 1), date(2024, 12, 31))
HORIZON_H = 24  # main horizon, the only one tested
SIDE_H = 4  # shown only
FLOW_SHARE = M.DELTA_SHARE  # 0.08: taker delta / volume over the move, signed in the move's direction
TYPES = ("UP_FLOW", "UP_OHNE", "DOWN_FLOW", "DOWN_OHNE")
DRAWS = 1000
SEED = 39
ALPHA = 0.05
MIN_EFFECT = 0.005  # 0.5 percentage points over the random hours
MIN_TRAIN = 20
MIN_VALID = 5
QUIET = M.MERGE_GAP  # a move is over only when no flag followed within 4 h: measured from then on (no look-ahead)
SPACING = timedelta(hours=HORIZON_H)  # moves whose start of measurement is closer than 24 h to the one before are left out
NEAR = timedelta(days=15)  # random hours are drawn within +/- 15 days of each move (same volatility regime)


def rows_from(candles: Mapping[int, Any]) -> list[dict[str, Any]]:
    """Hour candles with taker buy and sell volume (hours without a trade or from a faulty day are left out)."""
    out = []
    for start in sorted(candles):
        c = candles[start]
        if not c.trades or c.faulty:
            continue
        opened = datetime.fromtimestamp(start / 1000, timezone.utc)
        buy, sell = float(c.buy_quote), float(c.sell_quote)
        out.append({"open_time": opened, "close_time": opened + timedelta(hours=1), "open": c.open, "high": c.high, "low": c.low,
                    "close": c.close, "volume": (buy + sell) or 1.0, "buy": buy, "sell": sell})
    return out


def moves(h1: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Moves of the live detector (thresholds of move-context/0.2) with direction, change and flow share."""
    h4 = four_hour_rows(h1)
    flags = M.flags_from(h1, "1h", M.scores(h1, "1h")) + M.flags_from(h4, "4h", M.scores(h4, "4h"))
    by_open = {c["open_time"]: c for c in h1}
    out = []
    for m in M.merge(flags):
        hours = [by_open[t] for t in _hours(m["start"], m["end"]) if t in by_open]
        if not hours:
            continue
        change = hours[-1]["close"] / hours[0]["open"] - 1.0
        if change == 0:
            continue
        sign = 1 if change > 0 else -1
        buy, sell = sum(c["buy"] for c in hours), sum(c["sell"] for c in hours)
        share = sign * (buy - sell) / (buy + sell) if buy + sell > 0 else 0.0
        kind = ("UP" if sign > 0 else "DOWN") + ("_FLOW" if share >= FLOW_SHARE else "_OHNE")
        known = max(f["end"] for f in m["triggers"]) + QUIET  # every flag of the move, 4h ones included, lies before
        out.append({"start": m["start"], "end": m["end"], "known": known, "sign": sign, "change": change,
                    "flow_share": round(share, 4), "type": kind})
    return out


def _hours(start: datetime, end: datetime) -> list[datetime]:
    out, t = [], start
    while t < end:
        out.append(t)
        t += timedelta(hours=1)
    return out


def forward(by_close: Mapping[datetime, float], at: datetime, hours: int) -> float | None:
    """Return from the close at ``at`` to the close ``hours`` later, None when either hour is missing."""
    a, b = by_close.get(at), by_close.get(at + timedelta(hours=hours))
    return None if a is None or b is None or a <= 0 else b / a - 1.0


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def evaluate(h1: Sequence[Mapping[str, Any]], first: date, last: date, *, draws: int = DRAWS, seed: int = SEED) -> dict[str, Any]:
    """Per type: n, mean direction-signed 24h return, random-hour mean, excess, two-sided p, per year (pure)."""
    if any(c["open_time"].date() > VALID[1] for c in h1):
        raise PermissionError("S39 reads no holdout hour")
    by_close = {c["close_time"]: c["close"] for c in h1}
    found, spaced, last_known = [], 0, None
    for m in moves(h1):
        if not first <= m["start"].date() <= last:
            continue
        if last_known is not None and m["known"] - last_known < SPACING:
            spaced += 1  # its 24 h would overlap the one before: left out, counted
            continue
        last_known = m["known"]
        found.append(m)
    pool = [t for t in sorted(by_close) if first <= t.date() <= last and forward(by_close, t, HORIZON_H) is not None]
    rng = random.Random(seed)
    result: dict[str, Any] = {"moves": len(found), "left_out_overlap": spaced, "pool_hours": len(pool), "types": {}}
    for kind in TYPES:
        mine = [m for m in found if m["type"] == kind]
        sign = 1 if kind.startswith("UP") else -1
        rows, near = [], []
        for m in mine:
            fwd = forward(by_close, m["known"], HORIZON_H)
            if fwd is None:
                continue
            nearby = [t for t in pool if abs(t - m["known"]) <= NEAR]
            if not nearby:
                continue
            side = forward(by_close, m["known"], SIDE_H)
            rows.append({"end": m["end"].isoformat(), "known": m["known"].isoformat(), "year": m["known"].year, "signed": sign * fwd,
                         "signed_4h": None if side is None else sign * side, "change": round(m["change"], 4), "flow_share": m["flow_share"]})
            near.append(nearby)
        n = len(rows)
        block: dict[str, Any] = {"n": n, "no_forward": len(mine) - n}
        if n:
            real = _mean([r["signed"] for r in rows])
            null = [_mean([sign * forward(by_close, rng.choice(hours), HORIZON_H) for hours in near]) for _ in range(draws)]
            mu0 = _mean(null)
            extreme = sum(abs(x - mu0) >= abs(real - mu0) for x in null)
            years = sorted({r["year"] for r in rows})
            block.update(mean=round(real, 5), random_mean=round(mu0, 5), excess=round(real - mu0, 5), p=(1 + extreme) / (1 + draws),
                         continuation_share=round(sum(r["signed"] > 0 for r in rows) / n, 3),
                         mean_4h=round(_mean([r["signed_4h"] for r in rows if r["signed_4h"] is not None]), 5),
                         years=len(years),
                         leave_one_year_out={str(y): round(_mean([r["signed"] for r in rows if r["year"] != y]) - mu0, 5) for y in years if len(years) > 1},
                         rows=rows)
        result["types"][kind] = block
    tested = {k: b["p"] for k, b in result["types"].items() if "p" in b}
    for k, p in holm_adjusted(tested, len(TYPES)).items():
        result["types"][k]["holm_p"] = round(p, 4)
    return result


def verdict(train: Mapping[str, Any], valid: Mapping[str, Any] | None = None) -> dict[str, str]:
    """Per type: "belegt: Fortsetzung" / "belegt: Umkehr" / "nicht belegt" / "nicht prüfbar" (criteria of the preregistration)."""
    out = {}
    for kind in TYPES:
        b = train["types"].get(kind) or {}
        if b.get("n", 0) < MIN_TRAIN or "holm_p" not in b:
            out[kind] = "nicht prüfbar"
            continue
        sign = 1 if b["excess"] > 0 else -1
        ok = (b["holm_p"] <= ALPHA and abs(b["excess"]) >= MIN_EFFECT and b.get("years", 0) >= 2
              and all(x * sign > 0 for x in b["leave_one_year_out"].values()))
        if ok and valid is not None:
            v = valid["types"].get(kind) or {}
            if v.get("n", 0) < MIN_VALID or "excess" not in v:
                out[kind] = "nicht prüfbar (Validierung zu klein)"
                continue
            ok = v["excess"] * sign > 0
        direction = "Fortsetzung" if sign > 0 else "Umkehr"
        out[kind] = "nicht belegt" if not ok else (f"belegt: {direction}" if valid is not None else f"Training bestanden: {direction}")
    return out


def report(train: Mapping[str, Any], valid: Mapping[str, Any] | None, verdicts: Mapping[str, str]) -> str:
    def pct(x: Any) -> str:
        return "–" if x is None else f"{x * 100:+.2f} %".replace(".", ",")

    lines = [f"# S39 – Fortsetzung oder Umkehr nach großen Bewegungen (Präregistrierung {VERSION})", "",
             f"Detektor {M.MOVE_RULES}, BTCUSDT 1h aus S8-Minutenbars. Training {TRAIN[0]} bis {TRAIN[1]}"
             + (f", Validierung {VALID[0]} bis {VALID[1]}" if valid is not None else ", Validierung noch nicht gelesen")
             + ". Holdout 2025 nicht gelesen. Nur Beschreibung, kein Trade, keine Kosten.", "",
             f"Bewegungen Training: {train['moves']}, Zufallsstunden-Pool: {train['pool_hours']}.", "",
             "| Typ | n | Ø 24h (in Richtung) | Zufall | Überschuss | Holm-p | Anteil Fortsetzung | Ø 4h | Validierung n / Überschuss | Urteil |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for kind in TYPES:
        b = train["types"].get(kind) or {}
        v = (valid or {}).get("types", {}).get(kind) or {}
        val = f"{v.get('n', 0)} / {pct(v.get('excess'))}" if valid is not None else "–"
        lines.append(f"| {kind} | {b.get('n', 0)} | {pct(b.get('mean'))} | {pct(b.get('random_mean'))} | {pct(b.get('excess'))} | "
                     f"{b.get('holm_p', '–')} | {b.get('continuation_share', '–')} | {pct(b.get('mean_4h'))} | {val} | {verdicts[kind]} |")
    lines += ["", "Positiv = der Kurs lief in Richtung der Bewegung weiter, negativ = Umkehr. Überschuss = gegen zufällige Stunden "
              "mit demselben Vorzeichen (der Aufwärtstrend 2020–23 ist damit herausgerechnet).", ""]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    from src.research_lab.studies import s17

    parser = argparse.ArgumentParser(prog="s39")
    parser.add_argument("--root", type=Path, required=True, help="S8 store with bars/ and bars_manifest.json")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--phase", choices=("train", "valid"), default="train", help="valid reads 2024 once, after the training run")
    args = parser.parse_args(argv)
    frozen = args.out / "s39_train.json"
    if args.phase == "train":
        if frozen.exists():
            raise FileExistsError(f"{frozen}: the training run exists, it is not repeated")
        # The detector needs a week (1h) and 15 days (4h) of history: early January 2020 finds no move (S8 starts 2020-01-01).
        candles, digest = s17.load_candles(args.root, TRAIN[0], TRAIN[1])
        train, valid = evaluate(rows_from(candles), *TRAIN), None
    else:
        if not frozen.exists():
            raise FileNotFoundError(f"{frozen}: validation only after the training run")
        if (args.out / "s39_valid.json").exists():
            raise FileExistsError("the validation run exists, 2024 is read once")
        train = json.loads(frozen.read_text())["train"]  # the training result as frozen, not recomputed with 2024 loaded
        candles, digest = s17.load_candles(args.root, TRAIN[0], VALID[1])  # 2023 only as detector history
        valid = evaluate(rows_from(candles), *VALID)
    verdicts = verdict(train, valid)
    out = {"studie": "S39", "version": VERSION, "phase": args.phase, "dataset_hash": digest, "train": train, "valid": valid, "verdicts": verdicts}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"s39_{args.phase}.json").write_text(json.dumps(out, indent=1, default=str))
    (args.out / f"s39_{args.phase}.md").write_text(report(train, valid, verdicts))
    print(report(train, valid, verdicts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
