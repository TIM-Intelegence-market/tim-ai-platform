"""Influence research CLI (descriptive, BTC up to 2024 only).

    python -m src.research_lab.influence fetch [--folder data/research/influence]
        FRED history 2016-06-01..2024-12-31 for every catalog series, stored raw with SHA-256.
    python -m src.research_lab.influence dominanz [--folder ...]
        BTC/USDT dominance substitute 2019-06-22..2024-12-31 from Coin Metrics Community (no key), raw with SHA-256.
    python -m src.research_lab.influence run [--folder ...] [--btc-root data/research_lab]
        Weekly states, per-driver and joint description; writes einfluss_<date>.json/.md.
    python -m src.research_lab.influence zuordnung --report FILE [--calendar data/macro/calendar.json] [--folder ...]
        Today's driver states (as published now) next to the historical BTC behaviour and the coming dates.

BTC comes from the verified Binance spot archive (1d) through ArchiveStore, which refuses the holdout.
The FRED key comes from FredSecretResolver (TIM_FRED_SECRET_PROVIDER) and is never printed or stored.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from datetime import date, datetime, timezone
from pathlib import Path

from src.research_lab.forward.macro_filters import (
    MacroDataError,
    Series,
    fetch_series,
    parse_observations,
    scale_to_billions,
)
from src.research_lab.influence import dominance
from src.research_lab.influence import report as report_mod
from src.research_lab.influence import zuordnung
from src.research_lab.influence.catalog import all_series

FOLDER = Path("data/research/influence")
HISTORY_START = "2016-06-01"
HISTORY_END = "2024-12-31"


def _key_and_fetcher():
    from src.research_lab.external.fred_secret import FredSecretResolver
    from src.research_lab.external.live import http_fetcher

    return FredSecretResolver().api_key().reveal(), http_fetcher()


def fetch_history(folder: Path, fetch, api_key: str, series_ids: Sequence[str] = ()) -> dict[str, str]:
    from src.research_lab.external.alfred import url_for

    raw_dir = folder / "roh"
    raw_dir.mkdir(parents=True, exist_ok=True)
    meta = {}
    for sid in series_ids or all_series():
        try:
            units = json.loads(fetch(url_for({"path": "series", "series_id": sid}, api_key)))["seriess"][0]["units"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise MacroDataError(f"{sid}: series metadata missing") from exc
        payload = fetch(url_for({"path": "series/observations", "series_id": sid, "observation_start": HISTORY_START,
                                 "observation_end": HISTORY_END}, api_key))
        (raw_dir / f"{sid}.json").write_bytes(payload)
        meta[sid] = {"units": units, "sha256": hashlib.sha256(payload).hexdigest()}
    (folder / "roh" / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    return {sid: m["sha256"] for sid, m in meta.items()}


def load_history(folder: Path) -> tuple[dict[str, Series], dict[str, str]]:
    meta = json.loads((folder / "roh" / "meta.json").read_text())
    data, hashes = {}, {}
    for sid, m in meta.items():
        payload = (folder / "roh" / f"{sid}.json").read_bytes()
        if hashlib.sha256(payload).hexdigest() != m["sha256"]:
            raise MacroDataError(f"{sid}: stored answer changed since it was fetched")
        data[sid] = [(d, v) for d, v in parse_observations(payload, scale_to_billions(sid, m["units"]))
                     if d <= date(2024, 12, 31)]
        hashes[sid] = m["sha256"]
    return data, hashes


def load_btc_daily(root: Path) -> tuple[dict[date, float], str]:
    from src.research_lab.data.archive import ArchiveRef, Dataset, Market
    from src.research_lab.data.store import ArchiveStore, months

    store = ArchiveStore(root)
    refs = [ArchiveRef(Market.SPOT, Dataset.KLINES, y, m, "1d") for y, m in months((2017, 8), (2024, 12))]
    for ref in refs:
        store.fetch(ref)
    closes = {datetime.fromtimestamp(k.open_time / 1000, timezone.utc).date(): k.close for k in store.load_klines(refs)}
    return closes, store.dataset_hash(refs)


def main(argv: Sequence[str] | None = None, *, now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(description="Influence research (descriptive, BTC up to 2024)")
    parser.add_argument("command", choices=("fetch", "dominanz", "run", "zuordnung"))
    parser.add_argument("--folder", type=Path, default=FOLDER)
    parser.add_argument("--btc-root", type=Path, default=Path("data/research_lab"))
    parser.add_argument("--report", type=Path)
    parser.add_argument("--calendar", type=Path, default=Path("data/macro/calendar.json"))
    args = parser.parse_args(argv)
    moment = now or datetime.now(timezone.utc)
    if args.command == "fetch":
        key, fetch = _key_and_fetcher()
        hashes = fetch_history(args.folder, fetch, key)
        print(f"{len(hashes)} Reihen gespeichert in {args.folder / 'roh'}")
        return 0
    if args.command == "dominanz":
        hashes = dominance.fetch_history(args.folder, dominance.http_fetcher())
        print(f"{len(hashes)} Dateien gespeichert in {args.folder / 'roh' / 'dominanz'}")
        return 0
    if args.command == "run":
        from src.research_lab.influence.states import btc_weekly_returns, weeks

        data, hashes = load_history(args.folder)
        dom, dom_hashes = dominance.load_history(args.folder)
        if not dom:
            print("Hinweis: keine Dominanz-Historie (erst 'dominanz' ausführen), BTCD/USDTD bleiben leer")
        data, hashes = {**data, **dom}, {**hashes, **dom_hashes}
        closes, btc_hash = load_btc_daily(args.btc_root)
        btc = btc_weekly_returns(closes, weeks())
        result = report_mod.build(data, btc, now=moment, inputs={**hashes, "btc_1d": btc_hash})
        js, md = report_mod.write(result, args.folder / "berichte")
        print(f"geschrieben: {js}, {md}")
        return 0
    if args.report is None:
        parser.error("zuordnung braucht --report")
    from src.dashboard.macro_calendar import load_calendar

    key, fetch = _key_and_fetcher()
    data, _ = fetch_series(all_series(), moment.date(), fetch, key)
    try:
        data.update(dominance.recent(dominance.http_fetcher(), moment.date()))
    except MacroDataError as exc:
        print(f"Hinweis: Dominanz heute nicht abrufbar ({exc}), BTCD/USDTD ohne Zustand")
    result = zuordnung.build(data, json.loads(args.report.read_text()), load_calendar(args.calendar), moment.date())
    out = args.folder / "zuordnung" / f"zuordnung_{moment.date().isoformat()}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(zuordnung.markdown(result))
    print(f"geschrieben: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
