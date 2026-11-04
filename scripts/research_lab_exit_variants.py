"""Exit variants of the plan journal (fixed TP3 vs. runner vs. orderflow runner), paper only.

Reads the horizon journals, TIM's 1m candles and the perp-flow day files, and writes a JSON and a
Markdown report. Nothing is written to the journals or the database. See src/research_lab/exit_variants.py.

    python scripts/research_lab_exit_variants.py \\
        --journal data/journal/tim_plan_journal_short.json --journal data/journal/tim_plan_journal_mid.json \\
        --candles 1m.csv --perp-dir data/perp_flow --out report-dir

Candles: CSV with a header (open_time, open, high, low, close; open_time as ISO or epoch ms) or JSON
(a list of objects, or one object per line). Spot delta (optional): a footprint store JSON
(``{"bucket_seconds": 300, "days": {day: [[bucket, level, bid, ask], ...]}}``).
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.research_lab import exit_variants as ev  # noqa: E402


def _moment(value: Any) -> datetime:
    text = str(value).strip()
    if text.lstrip("-").isdigit():
        number = int(text)
        return datetime.fromtimestamp(number / 1000 if number > 10**11 else number, tz=timezone.utc)
    return ev._time(text)


def load_candles(path: Path) -> list[dict[str, Any]]:
    text = path.read_bytes()
    if path.suffix == ".gz":
        text = gzip.decompress(text)
    raw = text.decode()
    if path.suffix in {".csv", ".gz"} and not raw.lstrip().startswith(("[", "{")):
        rows = list(csv.DictReader(raw.splitlines()))
    elif raw.lstrip().startswith("["):
        rows = json.loads(raw)
    else:
        rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    by_open: dict[datetime, dict[str, Any]] = {}
    for row in rows:
        opened = _moment(row["open_time"])
        values = [float(row[key] if key in row else row[key[0]]) for key in ("open", "high", "low", "close")]
        if min(values) <= 0 or values[2] > min(values[0], values[3]) or values[1] < max(values[0], values[3]):
            continue
        volume = row.get("volume") or row.get("v") or 0.0
        by_open[opened] = {"open_time": opened, "close_time": opened + timedelta(minutes=1),
                           "open": values[0], "high": values[1], "low": values[2], "close": values[3], "volume": float(volume)}
    return [by_open[key] for key in sorted(by_open)]


def load_store(paths: list[Path]) -> dict[str, list[list[float]]]:
    """Day rows [bucket, level, bid, ask] from perp day files (perp-*.json.gz, archive included)."""
    days: dict[str, list[list[float]]] = {}
    for path in paths:
        payload = json.loads(gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_text())
        if "days" in payload:
            days.update(payload["days"])
        else:
            days[payload["day"]] = payload["rows"]
    return days


def taker_deltas(path: Path, volumes: dict[datetime, float]) -> dict[str, list[list[float]]]:
    """Spot delta per minute from a taker-buy CSV (open_time, taker_buy_volume...) and the candle volume:
    delta = 2 * taker_buy - volume, as rows [minute, 0, bid, ask] of one pseudo day."""
    rows = []
    for row in csv.DictReader(path.read_text().splitlines()):
        opened = _moment(row["open_time"])
        buy = float(next(value for key, value in row.items() if key.startswith("taker_buy")))
        if opened in volumes:
            rows.append([int(opened.timestamp()), 0.0, volumes[opened] - buy, buy])
    return {"spot": rows}


def deltas_by_bar(days: dict[str, list[list[float]]], bar_seconds: int) -> dict[int, float]:
    result: dict[int, float] = {}
    for rows in days.values():
        for bucket, _, bid, ask in rows:
            bar = int(bucket) // bar_seconds * bar_seconds
            result[bar] = result.get(bar, 0.0) + float(ask) - float(bid)
    return result


def _local(value: Any) -> str:
    if not value:
        return "-"
    from zoneinfo import ZoneInfo

    return ev._time(value).astimezone(ZoneInfo("Europe/Berlin")).strftime("%d.%m. %H:%M")


def markdown(report: dict[str, Any]) -> str:
    lines = ["# Ausstiegs-Varianten im Plan-Journal (Papier)", "",
             f"Erstellt {_local(report['created_at'])} (deutsche Zeit). Kosten: {report['costs']}. "
             f"1m-Kerzen {_local(report['candles']['first'])} bis {_local(report['candles']['last'])}. "
             f"Perp-Delta ab {_local(report['perp']['first'])}, Spot-Delta ab {_local(report['spot']['first'])}.", ""]
    for name, block in report["journals"].items():
        summary = block["summary"]
        lines += [f"## {name}", "", f"Abgeschlossen {summary['trades']} Trades, davon {summary['reached_tp2']} mit TP2; "
                  f"{summary['open']} noch offen.", "", "| Variante | Summe netto R | Schnitt R | im Plus |", "|---|---:|---:|---:|"]
        for variant in ev.VARIANTS:
            item = summary[variant]
            lines.append(f"| {variant} | {item['sum_r']:+.2f} | {item['mean_r'] if item['mean_r'] is None else format(item['mean_r'], '+.3f')} | {item['wins']} |")
        tp2 = [row for row in block["rows"] if row["tp_hits"] >= 2]
        if tp2:
            lines += ["", "Trades mit TP2 (nur hier unterscheiden sich die Varianten):", "",
                      "| Gefüllt | Richtung | TP3 | Journal | " + " | ".join(ev.VARIANTS) + " | OF-Urteil |",
                      "|---|---|---:|---|" + "---|" * len(ev.VARIANTS) + "---|"]
            for row in tp2:
                cells = []
                for variant in ev.VARIANTS:
                    item = row["variants"][variant]
                    cells.append(f"{item.get('exit_reason')} {item.get('exit_price') or '-'} ({item.get('net_r', '-')})")
                verdict = row["variants"]["OF_LAEUFER"].get("of_verdict")
                lines.append(f"| {_local(row['filled_at'])} | {row['direction']} | {row['targets'][2]} | "
                             f"{row['journal_exit']} {row['journal_net_r']} | " + " | ".join(cells) + f" | {verdict} |")
        lines.append("")
    lines += ["Hinweis: kleine Stichprobe, nur beschreibend; kein Test, kein Edge-Nachweis. "
              "Entscheidungen nutzen nur Kerzen und Delta, die vor der jeweiligen Minute geschlossen waren.", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--journal", action="append", type=Path, required=True)
    parser.add_argument("--candles", type=Path, required=True)
    parser.add_argument("--perp-dir", type=Path)
    parser.add_argument("--spot-store", type=Path)
    parser.add_argument("--spot-taker", type=Path, help="CSV open_time,taker_buy_volume per 1m (spot delta)")
    parser.add_argument("--of-source", choices=["perp", "spot"], default="perp")
    parser.add_argument("--costs", choices=["kraken", "protocol"], default="kraken")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    costs = ev.KRAKEN if args.costs == "kraken" else ev.PROTOCOL
    minutes = load_candles(args.candles)
    perp_days = load_store(sorted(args.perp_dir.glob("**/perp-*.json*"))) if args.perp_dir else {}
    spot_days = load_store([args.spot_store]) if args.spot_store else {}
    if args.spot_taker:
        spot_days = taker_deltas(args.spot_taker, {c["open_time"]: c["volume"] for c in minutes})
    first_bucket = lambda days: min((int(r[0]) for rows in days.values() for r in rows[:1]), default=None)  # noqa: E731
    report: dict[str, Any] = {
        "created_at": ev._iso(datetime.now(timezone.utc)), "costs": costs.name, "of_source": args.of_source, "variants": list(ev.VARIANTS),
        "candles": {"count": len(minutes), "first": ev._iso(minutes[0]["open_time"]) if minutes else None,
                    "last": ev._iso(minutes[-1]["close_time"]) if minutes else None},
        "perp": {"days": sorted(perp_days), "first": ev._iso(datetime.fromtimestamp(first_bucket(perp_days), tz=timezone.utc)) if perp_days else None},
        "spot": {"days": sorted(spot_days), "first": ev._iso(datetime.fromtimestamp(first_bucket(spot_days), tz=timezone.utc)) if spot_days else None},
        "journals": {},
    }
    plans = {}
    for path in args.journal:
        journal = json.loads(path.read_text())
        rows = []
        for entry in journal.get("entries") or []:
            if entry.get("excluded") or not entry.get("filled_at"):
                continue
            timeframe = str(entry.get("timeframe") or "30m")
            if timeframe not in plans:
                plans[timeframe] = (ev.aggregate(minutes, timeframe), ev.aggregate(minutes, ev.HIGHER.get(timeframe, timeframe)))
            plan, higher = plans[timeframe]
            bar_seconds = ev.TIMEFRAME_MINUTES[timeframe] * 60
            deltas = deltas_by_bar(perp_days if args.of_source == "perp" else spot_days, bar_seconds)
            row = ev.evaluate_entry(entry, minutes, plan, higher, deltas, costs)
            if row:
                rows.append(row)
        report["journals"][path.stem] = {"summary": ev.summarize(rows), "rows": rows}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "ausstieg_varianten.json").write_text(json.dumps(report, indent=1, default=str))
    (args.out / "ausstieg_varianten.md").write_text(markdown(report))
    print(markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
