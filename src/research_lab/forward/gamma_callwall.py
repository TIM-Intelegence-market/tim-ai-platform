"""S41: Call-Wall als Widerstand, Vorwärtsbeobachtung (Papier, nur lesend).

Liest TIMs eigenes Gamma-Log (``data/options/gamma_levels.jsonl``, Einträge mit ``as_of``, ``spot``,
``call_wall``) und BTCUSDT-1h-Kerzen. Bewertet nur Stände ab ``START`` (nach dem Einfrieren), nie davor.
Regel und Schwellen sind in ``docs/research_lab/studien/S41_GAMMA_CALLWALL_VORWAERTS_PRAEREGISTRIERUNG.md``
eingefroren (Version 1.0); Änderungen nur als neue Version mit neuem Start.

Kein Handel, keine Order, kein Netz außer dem optionalen Kerzenabruf im CLI.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import pathlib
import urllib.request
from dataclasses import dataclass
from typing import Iterable, Sequence

VERSION = "1.0"
FROZEN = True
START = dt.datetime(2026, 11, 25, 0, 0, tzinfo=dt.timezone.utc)
SAMPLE_EVERY_H = 4
MIN_DIST, MAX_DIST = 0.003, 0.10
TOUCH_TOL, BACK, BEYOND = 0.001, 0.015, 0.01
LOOK_H, HOLD_H = 168, 48
CONTROL_FACTORS = (0.7, 1.3)
MIN_EVENTS = 30
MIN_EDGE = 0.15
MAX_DAYS = 120

Bar = tuple[int, float, float, float, float]  # open_time_ms, open, high, low, close


@dataclass(frozen=True)
class Outcome:
    result: str  # hold | break | open | untouched
    touch_ms: int | None


def judge(level: float, bars: Sequence[Bar]) -> Outcome:
    """Level über dem Kurs: erste Berührung binnen LOOK_H; danach hält es (Kurs fällt zuerst BACK darunter)
    oder bricht (1h-Schluss zuerst BEYOND darüber) binnen HOLD_H, sonst offen."""
    for i, (t, _o, h, _l, _c) in enumerate(bars[:LOOK_H]):
        if h < level * (1 - TOUCH_TOL):
            continue
        window = bars[i:i + HOLD_H]
        for (_t2, _o2, _h2, l2, c2) in window:
            if c2 >= level * (1 + BEYOND):
                return Outcome("break", t)
            if l2 <= level * (1 - BACK):
                return Outcome("hold", t)
        return Outcome("open" if len(window) >= HOLD_H else "pending", t)
    return Outcome("untouched" if len(bars) >= LOOK_H else "pending", None)


def sample_snapshots(lines: Iterable[str], start: dt.datetime = START) -> list[dict]:
    """Erster Eintrag je SAMPLE_EVERY_H-Stundenblock (UTC) ab ``start``."""
    picked: dict[str, dict] = {}
    for line in lines:
        try:
            r = json.loads(line)
            t = dt.datetime.fromisoformat(r["as_of"])
        except (ValueError, KeyError, TypeError):
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.timezone.utc)
        if t < start or t.hour % SAMPLE_EVERY_H:
            continue
        picked.setdefault(t.strftime("%Y-%m-%dT%H"), {**r, "_t": t})
    return [picked[k] for k in sorted(picked)]


def evaluate(snapshots: Sequence[dict], bars: Sequence[Bar]) -> dict:
    """Ein Ereignis je (Level, Berührungskerze): wiederholte Stände derselben Wand zählen nur einmal."""
    by_time = {b[0]: i for i, b in enumerate(bars)}
    real: dict[tuple, str] = {}
    ctrl: dict[tuple, str] = {}
    skipped = 0
    for s in snapshots:
        wall, spot = s.get("call_wall"), s.get("spot")
        if not wall or not spot:
            skipped += 1
            continue
        d = wall / spot - 1
        if not (MIN_DIST <= d <= MAX_DIST):
            skipped += 1
            continue
        nxt = (s["_t"].replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1))
        i0 = by_time.get(int(nxt.timestamp() * 1000))
        if i0 is None:
            skipped += 1
            continue
        future = bars[i0:]
        o = judge(wall, future)
        if o.touch_ms is not None:
            real.setdefault((round(wall, 2), o.touch_ms), o.result)
        for f in CONTROL_FACTORS:
            lv = spot * (1 + d * f)
            oc = judge(lv, future)
            if oc.touch_ms is not None:
                ctrl.setdefault((round(lv, 2), oc.touch_ms), oc.result)
    return summarize(list(real.values()), list(ctrl.values()), len(snapshots), skipped)


def wilson_low(k: int, n: int, z: float = 1.96) -> float:
    if n == 0:
        return 0.0
    p = k / n
    den = 1 + z * z / n
    return (p + z * z / (2 * n) - z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / den


def summarize(real: list[str], ctrl: list[str], n_snap: int, skipped: int) -> dict:
    rh, rb = real.count("hold"), real.count("break")
    ch, cb = ctrl.count("hold"), ctrl.count("break")
    n = rh + rb
    rate = rh / n if n else 0.0
    crate = ch / (ch + cb) if ch + cb else 0.0
    low = wilson_low(rh, n)
    if n < MIN_EVENTS:
        verdict = "ZU_WENIG_DATEN"
    elif rate - crate >= MIN_EDGE and low > 0.5:
        verdict = "BESTANDEN"
    else:
        verdict = "NICHT_BESTANDEN"
    return {"version": VERSION, "start": START.isoformat(), "snapshots": n_snap, "skipped": skipped,
            "events": n, "hold": rh, "break": rb, "hold_rate": round(rate, 4), "wilson_low": round(low, 4),
            "control_events": ch + cb, "control_hold_rate": round(crate, 4),
            "edge": round(rate - crate, 4), "pending": real.count("pending"), "verdict": verdict}


def fetch_bars(start: dt.datetime, end: dt.datetime) -> list[Bar]:  # pragma: no cover - network
    out: list[Bar] = []
    t = int(start.timestamp() * 1000)
    stop = int(end.timestamp() * 1000)
    while t < stop:
        url = f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1h&startTime={t}&limit=1000"
        with urllib.request.urlopen(url, timeout=30) as r:
            rows = json.load(r)
        if not rows:
            break
        out += [(int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4])) for k in rows]
        t = int(rows[-1][0]) + 3_600_000
    now = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    return [b for b in out if b[0] + 3_600_000 <= now]  # nur geschlossene Kerzen


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - CLI
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--log", default="data/options/gamma_levels.jsonl")
    args = p.parse_args(argv)
    snaps = sample_snapshots(pathlib.Path(args.log).read_text().splitlines())
    now = dt.datetime.now(dt.timezone.utc)
    res = evaluate(snaps, fetch_bars(START, now)) if snaps else summarize([], [], 0, 0)
    res["days"] = (now - START).days
    if res["verdict"] == "ZU_WENIG_DATEN" and res["days"] >= MAX_DAYS:
        res["verdict"] = "NICHT_BESTANDEN_ZEIT"
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
