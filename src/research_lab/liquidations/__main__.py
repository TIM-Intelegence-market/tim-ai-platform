"""S12 command line (lab only; read-only towards the exchanges, no account, no orders).

    python -m src.research_lab.liquidations run [--data-dir DIR]          # both feeds + 4 states a day
    python -m src.research_lab.liquidations snapshot --at 2026-11-01T06:00:00Z
    python -m src.research_lab.liquidations verify [--day 2026-11-01]
    python -m src.research_lab.liquidations manifest --day 2026-11-01
    python -m src.research_lab.liquidations sides [--limit 20]            # side check before version 1.0
    python -m src.research_lab.liquidations gate --start 2026-11-02

``--data-dir`` defaults to ``$TIM_S12_DATA_DIR`` or
``~/Library/Application Support/TIM/research-lab/liquidations``.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import collector, events, gate, snapshots, store

log = logging.getLogger("s12")


def _utc(value: str) -> datetime:
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        raise argparse.ArgumentTypeError("time needs a zone, e.g. 2026-11-01T06:00:00Z")
    return moment.astimezone(timezone.utc)


async def _sleep_until(when: datetime, stop: asyncio.Event, step: float = 30.0) -> bool:
    """Wait for wall-clock time ``when`` in short steps (the monotonic clock may stop while the
    Mac sleeps). Returns False when stopped."""
    while not stop.is_set():
        left = (when - datetime.now(timezone.utc)).total_seconds()
        if left <= 0:
            return True
        try:
            await asyncio.wait_for(stop.wait(), timeout=min(step, left))
        except asyncio.TimeoutError:
            pass
    return False


async def _snapshot_loop(root: Path, stop: asyncio.Event) -> None:
    """Take each state at t + 120 s; retry every 60 s until t + 15 min, then give up for that t."""
    while not stop.is_set():
        now = datetime.now(timezone.utc)
        t = snapshots.window_start(now)
        if now > t + snapshots.MAX_FETCH_DELAY or snapshots.snapshot_path(root, t).exists():
            t = snapshots.next_window_start(now + timedelta(seconds=1))
        if not await _sleep_until(t + snapshots.FETCH_DELAY, stop):
            return
        while datetime.now(timezone.utc) <= t + snapshots.MAX_FETCH_DELAY and not stop.is_set():
            try:
                path = await asyncio.to_thread(snapshots.take, root, t)
                log.info("state %s stored: %s", t.isoformat(), path)
                break
            except Exception as exc:  # noqa: BLE001 - logged, retried, never fatal
                log.warning("state %s failed: %s", t.isoformat(), exc)
                if not await _sleep_until(datetime.now(timezone.utc) + timedelta(seconds=60), stop):
                    return
        else:
            if not stop.is_set():
                log.warning("state %s missed (no answer until t + 15 min)", t.isoformat())


async def _manifest_loop(root: Path, stop: asyncio.Event) -> None:
    """Write the manifests of the previous UTC day shortly after midnight."""
    while not stop.is_set():
        for venue in collector.VENUES:
            for back in (1, 2):
                day = datetime.now(timezone.utc).date() - timedelta(days=back)
                try:
                    if store.raw_path(root, venue, day).exists():
                        store.write_manifest(root, venue, day)
                except Exception as exc:  # noqa: BLE001 - a bad day must not stop later manifests
                    log.error("manifest %s %s failed: %s", venue, day, exc)
        now = datetime.now(timezone.utc)
        target = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), timezone.utc) + timedelta(minutes=10)
        if not await _sleep_until(target, stop, step=300.0):
            return


def _lock(root: Path):
    """One ``run`` per data folder: a second one exits instead of writing into the same files."""
    import fcntl

    root.mkdir(parents=True, exist_ok=True)
    handle = open(root / "run.lock", "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise SystemExit(f"another S12 collector already runs on {root}") from None
    return handle


async def _run(root: Path) -> None:
    lock = _lock(root)  # noqa: F841 - held for the lifetime of the process
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # pragma: no cover - not on macOS/Linux
            pass
    tasks = [asyncio.create_task(collector.run_venue(v, root, stop=stop)) for v in collector.VENUES.values()]
    tasks += [asyncio.create_task(_snapshot_loop(root, stop)), asyncio.create_task(_manifest_loop(root, stop))]
    await stop.wait()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def _sides(root: Path, limit: int) -> list[dict[str, object]]:
    now_ns = int(datetime.now(timezone.utc).timestamp() * store.NS_PER_S)
    rows = []
    for venue in collector.VENUES:
        found = []
        for record in store.records_between(root, venue, now_ns - 7 * 86_400 * store.NS_PER_S, now_ns + 1):
            if record["kind"] == "message":
                try:
                    found.extend(events.PARSERS[venue](json.loads(record["payload"])))
                except (ValueError, events.EventFormatError):
                    continue
        for event in found[-limit:]:
            rows.append({"venue": venue, "symbol": event.symbol, "raw_side": event.raw_side, "side": event.side,
                         "price": str(event.price), "quantity": str(event.quantity), "status": event.status,
                         "time": datetime.fromtimestamp(event.time_ms / 1000, timezone.utc).isoformat()})
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.research_lab.liquidations")
    parser.add_argument("--data-dir", default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run")
    snap = sub.add_parser("snapshot")
    snap.add_argument("--at", type=_utc, required=True)
    ver = sub.add_parser("verify")
    ver.add_argument("--day", type=date.fromisoformat)
    man = sub.add_parser("manifest")
    man.add_argument("--day", type=date.fromisoformat, required=True)
    sid = sub.add_parser("sides")
    sid.add_argument("--limit", type=int, default=20)
    gat = sub.add_parser("gate")
    gat.add_argument("--start", type=date.fromisoformat, required=True)
    args = parser.parse_args(argv)
    root = store.data_root(args.data_dir)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    if args.command == "run":
        asyncio.run(_run(root))
        return 0
    if args.command == "snapshot":
        print(snapshots.take(root, args.at))
        return 0
    if args.command == "verify":
        base = root / "snapshots"
        paths = sorted((base / args.day.isoformat()).glob("*.json.gz")) if args.day else sorted(base.glob("*/*.json.gz"))
        bad = 0
        for path in paths:
            problems = snapshots.verify(path)
            bad += bool(problems)
            print(f"{path.relative_to(root)}: {'OK' if not problems else '; '.join(problems)}")
        print(f"{len(paths)} states, {bad} with problems")
        return 1 if bad else 0
    if args.command == "manifest":
        for venue in collector.VENUES:
            print(json.dumps(store.manifest(root, venue, args.day), indent=2, sort_keys=True))
        return 0
    if args.command == "sides":
        print(json.dumps(_sides(root, args.limit), indent=2))
        return 0
    if args.command == "gate":
        start = datetime.combine(args.start, datetime.min.time(), timezone.utc)
        result = gate.run(root, start)
        result.pop("windows")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
