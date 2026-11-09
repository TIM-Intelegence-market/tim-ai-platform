"""src/dashboard/own_data.py: every own collector shows how old its newest record is."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.dashboard import own_data

NOW = datetime(2026, 11, 4, 13, 0, tzinfo=timezone.utc)


def _ns(moment: datetime) -> int:
    return int(moment.timestamp() * 1e9)


def _write_all(root: Path, liq: Path, *, age: timedelta = timedelta(0)) -> None:
    at = NOW - age
    perp = root / "perp_flow"
    (perp / "archive").mkdir(parents=True)
    (perp / "archive" / "perp-2026-10-20.json.gz").write_bytes(b"x" * 1000)
    (perp / "perp-2026-11-04.json.gz").write_bytes(b"x" * 1000)
    (perp / "state.json").write_text(json.dumps({
        "updated_at": at.isoformat(), "gaps": [], "checks": [{"hour": "2026-11-04T11:00:00+00:00", "ok": True}]}))
    hours = [{"t": int((at - timedelta(hours=1 + i)).timestamp()), "oi": 1.0, "oi_usd": 2.0} for i in reversed(range(3))]
    (perp / "oi-BTCUSDT-1h.jsonl").write_text("".join(json.dumps(h) + "\n" for h in hours))
    xmr = perp / "XMRUSDT"  # second perp symbol in its own folder (04.11.2026)
    xmr.mkdir()
    (xmr / "perp-2026-11-03.json.gz").write_bytes(b"x" * 500)
    (xmr / "state.json").write_text(json.dumps({"symbol": "XMRUSDT", "updated_at": at.isoformat(), "gaps": [], "checks": []}))
    (xmr / "oi-XMRUSDT-1h.jsonl").write_text("".join(json.dumps(h) + "\n" for h in hours[:2]))
    bybit = root / "bybit_flow"  # second venue of the bubbles (09.11.2026)
    bybit.mkdir()
    (bybit / "bybit-2026-11-04.json.gz").write_bytes(b"x" * 400)
    (bybit / "state.json").write_text(json.dumps({"symbol": "BTCUSDT", "updated_at": at.isoformat(), "sessions": 1, "trades": 5,
                                                   "segments": [[int(at.timestamp() * 1000) - 3_600_000, int(at.timestamp() * 1000)]]}))
    (root / "options").mkdir()
    (root / "options" / "gamma_levels.jsonl").write_text(json.dumps({"as_of": at.isoformat()}) + "\n")
    for venue in own_data.LIQ_VENUES:
        (liq / "raw" / venue).mkdir(parents=True)
        (liq / "raw" / venue / "2026-11-04.jsonl").write_text(json.dumps({"kind": "alive", "receive_ns": _ns(at)}) + "\n")
    (root / "operational").mkdir()
    (root / "operational" / "backup_files.json").write_text(json.dumps({
        "status": "PASS", "completed_at": (NOW - timedelta(hours=10)).isoformat(), "bytes": 2_500_000, "mirror": "/Volumes/x"}))
    (root / "operational" / "gap_filler.json").write_text(json.dumps({
        "state": "IDLE", "checked_at_utc": (at - timedelta(minutes=1)).isoformat(), "open_gaps": 0, "missing_trades": 0,
        "resolved_total": 2}))


def _by_id(tiles) -> dict:
    return {t.id: t for t in tiles}


def test_fresh_collectors_are_green_and_name_their_history(tmp_path: Path) -> None:
    _write_all(tmp_path / "data", tmp_path / "liq")
    tiles = _by_id(own_data.status(tmp_path / "data", tmp_path / "liq", NOW))
    assert {t.state for t in tiles.values()} == {"ok"}, {k: t.reason for k, t in tiles.items()}
    assert tiles["own_perp"].value == "2 Tage seit 2026-10-20"
    assert tiles["own_oi"].value == "3 Stunden" and tiles["own_gamma"].value == "1 Schnappschüsse"
    assert tiles["own_perp_xmr"].value == "1 Tage seit 2026-11-03" and tiles["own_perp_xmr"].label == "Perp-Orderflow XMR"
    assert tiles["own_oi_xmr"].value == "2 Stunden" and tiles["own_oi_xmr"].source == "data/perp_flow/XMRUSDT/oi-XMRUSDT-1h.jsonl"
    assert tiles["own_liq_bybit"].value == "1 Tage seit 2026-11-04"
    assert tiles["own_backup"].value == "2,5 MB"
    assert tiles["own_bybit"].value == "1 Tage seit 2026-11-04" and tiles["own_bybit"].label == "Bybit-Orderflow (Bubbles)"
    summary = own_data.summary_tile(list(tiles.values()), NOW)
    assert summary.state == "ok" and summary.value == "8/8 Sammler frisch"


def test_a_stopped_collector_turns_yellow_with_its_age(tmp_path: Path) -> None:
    _write_all(tmp_path / "data", tmp_path / "liq", age=timedelta(minutes=30))
    tiles = _by_id(own_data.status(tmp_path / "data", tmp_path / "liq", NOW))
    assert tiles["own_perp"].state == "warn" and "Daten veraltet" in tiles["own_perp"].reason
    assert tiles["own_liq_binance"].state == "warn" and tiles["own_gamma"].state == "warn"
    assert tiles["own_oi"].state == "ok"  # hourly data, 3 h limit
    summary = own_data.summary_tile(list(tiles.values()), NOW)
    assert summary.state == "warn" and summary.value == "2/8 Sammler frisch" and "Perp-Orderflow" in summary.reason


def test_gaps_failed_checks_and_disconnects_are_named(tmp_path: Path) -> None:
    data, liq = tmp_path / "data", tmp_path / "liq"
    _write_all(data, liq)
    state = json.loads((data / "perp_flow" / "state.json").read_text())
    state["gaps"] = [{"at": (NOW - timedelta(hours=2)).isoformat(), "reason": "Id-Lücke bei Binance"},
                     {"at": (NOW - timedelta(days=3)).isoformat(), "reason": "alt"}]
    state["checks"].append({"hour": "2026-11-04T12:00:00+00:00", "ok": False})
    (data / "perp_flow" / "state.json").write_text(json.dumps(state))
    with (liq / "raw" / "bybit" / "2026-11-04.jsonl").open("a") as handle:
        handle.write(json.dumps({"kind": "disconnect", "receive_ns": _ns(NOW)}) + "\n")
    tiles = _by_id(own_data.status(data, liq, NOW))
    perp = tiles["own_perp"]
    assert perp.state == "warn" and "1 Lücke(n) in 24 h" in perp.reason and "2026-11-04T12" in perp.reason
    assert perp.extra["gaps_total"] == 2
    assert tiles["own_liq_bybit"].state == "warn" and "disconnect" in tiles["own_liq_bybit"].reason


def test_missing_sources_are_grey_with_reason_and_a_copy_without_mirror_is_yellow(tmp_path: Path) -> None:
    tiles = _by_id(own_data.status(tmp_path / "data", tmp_path / "liq", NOW))
    assert {t.state for t in tiles.values()} == {"unknown"} and all(t.reason for t in tiles.values())
    assert own_data.summary_tile(list(tiles.values()), NOW).state == "unknown"
    _write_all(tmp_path / "data", tmp_path / "liq")
    report = tmp_path / "data" / "operational" / "backup_files.json"
    report.write_text(json.dumps({"status": "PASS", "completed_at": NOW.isoformat(), "bytes": 10, "mirror": False}))
    copy = _by_id(own_data.status(tmp_path / "data", tmp_path / "liq", NOW))["own_backup"]
    assert copy.state == "ok" and "keine zweite Kopie" in copy.reason
    (tmp_path / "data" / "perp_flow" / "state.json").write_text("{broken")
    assert _by_id(own_data.status(tmp_path / "data", tmp_path / "liq", NOW))["own_perp"].state == "fail"


def test_cockpit_shows_the_summary_on_lage_and_every_source_on_betrieb(tmp_path: Path, monkeypatch) -> None:
    from src.dashboard.cockpit.areas import build_betrieb
    from src.dashboard.cockpit.lage import build_lage
    from src.dashboard.cockpit.sources import BudgetedSources
    from tests.test_dashboard_cockpit import _state

    monkeypatch.setenv("TIM_WORKER_STATUS_URL", "http://127.0.0.1:9/api/status")
    monkeypatch.setenv("TIM_S12_DATA_DIR", str(tmp_path / "liq"))
    _write_all(tmp_path / "data", tmp_path / "liq", age=timedelta(hours=1))
    state = _state(tmp_path / "data")  # operational folder: data/operational, so the data root is data/
    lage = build_lage(state, now=NOW, sources=BudgetedSources(cache_seconds=0), budget=5)
    tile = next(t for t in lage["system"] if t["id"] == "own_data")
    assert tile["state"] == "warn" and tile["href"] == "/neu/betrieb" and "Perp-Orderflow" in tile["reason"]
    assert any(t["id"] == "own_data" for t in lage["attention"])
    betrieb = build_betrieb(state, now=NOW, sources=BudgetedSources(cache_seconds=0), budget=5)
    section = next(s for s in betrieb["sections"] if s["id"] == "own_data")
    assert [t["id"] for t in section["tiles"]] == ["own_perp", "own_oi", "own_perp_xmr", "own_oi_xmr", "own_bybit", "own_gamma", "own_liq_binance", "own_liq_bybit", "own_backup", "own_gaps"]


def _gap_report(root: Path, **fields) -> None:
    (root / "operational").mkdir(parents=True, exist_ok=True)
    (root / "operational" / "gap_filler.json").write_text(json.dumps({"checked_at_utc": NOW.isoformat(), **fields}))


def test_gap_filler_tile_green_while_gaps_shrink_yellow_when_stuck(tmp_path: Path) -> None:
    root = tmp_path / "data"
    assert own_data.gap_filler_tile(root / "operational", NOW).state == "unknown"  # no report yet
    _gap_report(root, state="IDLE", open_gaps=0, resolved_total=3)
    tile = own_data.gap_filler_tile(root / "operational", NOW)
    assert tile.state == "ok" and tile.value == "keine Lücke offen"
    _gap_report(root, state="FILLING", open_gaps=2, missing_trades=2_900_000,
                last_progress_at_utc=(NOW - timedelta(minutes=2)).isoformat())
    tile = own_data.gap_filler_tile(root / "operational", NOW)
    assert tile.state == "ok" and tile.value == "2 offen, 2.900.000 Trades"
    _gap_report(root, state="BACKING_OFF", open_gaps=1, missing_trades=10, last_error="public REST source returned no data",
                last_progress_at_utc=(NOW - timedelta(hours=7)).isoformat())
    tile = own_data.gap_filler_tile(root / "operational", NOW)
    assert tile.state == "warn" and "6 h" in tile.reason and "no data" in tile.reason
    _gap_report(root, state="ERROR", open_gaps=1, last_error="OSError: db")
    assert own_data.gap_filler_tile(root / "operational", NOW).state == "fail"
