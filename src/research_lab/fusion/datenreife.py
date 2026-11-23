"""P0: data-maturity report for one recorded stream (plan section 3 and gate G-A). Reads only; changes nothing.

Rules shared by the whole study family (one rule for S33 and S40): a gap is more than ``GAP_MS`` (10 min) without a
row; a duplicate is a repeated id; data age of open interest is ``recv_ms - snapshot ts``. Gate G-A needs at least
``MIN_DAYS`` days and gaps below ``MAX_GAP_SHARE`` of the covered time.

CLI (lists files, prints JSON, writes nothing):
    python -m src.research_lab.fusion.datenreife PATH [--ts-key ts_ms] [--id-key trade_id] [--recv-key recv_ms]
PATH is a JSONL file or a folder of ``*.jsonl``/``*.jsonl.gz`` files.
"""
from __future__ import annotations

import argparse
import gzip
import itertools
import json
import statistics
import sys
from collections.abc import Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

GAP_MS = 10 * 60_000
MIN_DAYS = 60
MAX_GAP_SHARE = 0.02
DAY_MS = 86_400_000


def report(rows: Iterable[Mapping[str, Any]], *, ts_key: str = "ts_ms", id_key: str | None = "trade_id",
           recv_key: str | None = "recv_ms", gap_ms: int = GAP_MS) -> dict[str, Any]:
    ts: list[int] = []
    seen: set[Any] = set()
    dup = bad = 0
    delays: list[int] = []
    for r in rows:
        t = r.get(ts_key)
        if isinstance(t, bool) or not isinstance(t, int) or t <= 0:
            bad += 1
            continue
        if id_key is not None and r.get(id_key) is not None:
            k = r[id_key]
            if k in seen:
                dup += 1
                continue
            seen.add(k)
        ts.append(t)
        rv = r.get(recv_key) if recv_key else None
        if isinstance(rv, int) and not isinstance(rv, bool):
            delays.append(rv - t)
    ts.sort()
    gaps = [(a, b) for a, b in itertools.pairwise(ts) if b - a > gap_ms]
    span = (ts[-1] - ts[0]) if len(ts) > 1 else 0
    gap_time = sum(b - a for a, b in gaps)
    days = span / DAY_MS
    share = (gap_time / span) if span else None
    return {
        "rows": len(ts), "duplicates": dup, "bad_rows": bad,
        "first_ms": ts[0] if ts else None, "last_ms": ts[-1] if ts else None, "days": round(days, 3),
        "gaps": len(gaps), "gap_share": share,
        "longest_gap_min": round(max((b - a for a, b in gaps), default=0) / 60_000, 1),
        "delay_median_ms": statistics.median(delays) if delays else None,
        "delay_p99_ms": sorted(delays)[int(0.99 * (len(delays) - 1))] if delays else None,
        "negative_delay": sum(1 for d in delays if d < 0),
        "gate_g_a": bool(ts) and days >= MIN_DAYS and share is not None and share < MAX_GAP_SHARE,
    }


def oi_age(snapshots: Sequence[Mapping[str, Any]], *, ts_key: str = "ts_ms", recv_key: str = "recv_ms",
           stale_ms: int = 15 * 60_000) -> dict[str, Any]:
    """Age of open-interest snapshots when TIM received them; ``stale`` counts those older than ``stale_ms``."""
    ages = [int(s[recv_key]) - int(s[ts_key]) for s in snapshots if recv_key in s and ts_key in s]
    if not ages:
        return {"n": 0, "median_ms": None, "max_ms": None, "stale": 0}
    return {"n": len(ages), "median_ms": statistics.median(ages), "max_ms": max(ages),
            "stale": sum(1 for a in ages if a > stale_ms)}


def _read(path: Path) -> Iterator[dict]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as fh:  # type: ignore[operator]
        for line in fh:
            line = line.strip()
            if line:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    yield {}
                    continue
                yield obj if isinstance(obj, dict) else {}


def _files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted([*path.glob("*.jsonl"), *path.glob("*.jsonl.gz")])


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path")
    ap.add_argument("--ts-key", default="ts_ms")
    ap.add_argument("--id-key", default="trade_id")
    ap.add_argument("--recv-key", default="recv_ms")
    a = ap.parse_args(argv)
    files = _files(Path(a.path))
    if not files:
        print(json.dumps({"error": "no files"}))
        return 2
    rows = (r for f in files for r in _read(f))
    out = report(rows, ts_key=a.ts_key, id_key=a.id_key or None, recv_key=a.recv_key or None)
    out["files"] = len(files)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
