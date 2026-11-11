"""XMR plan journals (Bauplan XMR, Paket 2): same TIM rule on the XMR perp, own files, BTC untouched."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.dashboard import perp_journal
from src.dashboard import plan_journal as pj
from src.dashboard.chart_live import KlineCache
from tests.test_chart_live import fake_fetch
from tests.test_perp_journal import NOW, _perp_cache


def _xmr_store(start, hours: int) -> dict:
    rows = [[int(start.timestamp()) + i * 300, 340.0, 1.0, 1.2] for i in range(hours * 12)]
    return {"symbol": "XMRUSDT", "market": "perp", "tick": 0.1, "bucket_seconds": 300,
            "days": {start.date().isoformat(): rows}, "complete": {}, "bubbles": {}}


def _xmr_cache(calls: list | None = None) -> KlineCache:
    return KlineCache(fake_fetch(calls))


def test_xmr_journals_write_their_own_files_with_xmr_plans(tmp_path: Path) -> None:
    calls: list = []
    paths = {"15m": tmp_path / "xmr_15m.json", "1h": tmp_path / "xmr_1h.json"}
    status = perp_journal.update(_xmr_cache(calls), _xmr_store(NOW - timedelta(days=6), 24 * 6), NOW, paths, symbol="XMRUSDT")
    assert not status["errors"] and set(status["journals"]) == {"15m", "1h"}
    assert {symbol for symbol, *_ in calls} == {"XMRUSDT"}
    entries = []
    for path in paths.values():
        view = json.loads(path.read_text(encoding="utf-8"))
        assert view["source"] == perp_journal.XMR_SOURCE and view["last_plan_candle"]
        entries += view["entries"]
    for entry in entries:
        _assert_xmr_entry(entry)


def _assert_xmr_entry(entry: dict) -> None:
    assert entry["symbol"] == "XMRUSDT" and entry["market_type"] == "USDM"
    assert entry["entry"] < 1_000  # XMR prices, never BTC
    assert entry["instrument"]["tick_size"] == 0.01 and entry["instrument"]["short_executable"] is True
    assert entry["evidence_status"] == pj.INSUFFICIENT_EVIDENCE
    assert entry["evidence_ref"]["reason"] == pj.SYMBOL_NOT_RESEARCHED
    assert "short_not_executable_on_spot" not in entry["journal_decision_reasons"]
    assert "instrument_unknown" not in entry["journal_decision_reasons"]
    assert entry["journal_decision"] == pj.NO_TRADE  # paper research only, as for BTC


def _xmr_series(start: datetime) -> dict:
    from tests.test_plan_journal import _series

    scale = 340.0 / 100_000.0
    out = {}
    for timeframe, rows in _series(start).items():
        out[timeframe] = [{**r, "symbol": "XMRUSDT", **{k: r[k] * scale for k in ("open", "high", "low", "close")}} for r in rows]
    return out


def test_plan_journal_records_xmr_plans_as_usdm(tmp_path: Path) -> None:
    start = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
    journal = pj.update(tmp_path / "x.json", _xmr_series(start), start + timedelta(minutes=30 * 90), market_type="USDM")
    assert journal["entries"], "the scaled test series gives plans as it does for BTC"
    for entry in journal["entries"]:
        _assert_xmr_entry(entry)
    # without market_type the plan keeps the chart model's SPOT label (BTC journals unchanged)
    btc = pj.update(tmp_path / "b.json", _series_btc(start), start + timedelta(minutes=30 * 90))
    assert btc["entries"] and all(e["market_type"] == "SPOT" for e in btc["entries"])


def _series_btc(start: datetime) -> dict:
    from tests.test_plan_journal import _series

    return _series(start)


def test_default_xmr_paths_are_separate_from_btc() -> None:
    assert set(perp_journal.XMR_PATHS.values()).isdisjoint(perp_journal.PATHS.values())
    assert all("xmr" in p.name for p in perp_journal.XMR_PATHS.values())


def test_xmr_refuses_btc_files_and_unknown_symbols(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="BTC perp journal"):
        perp_journal.update(_xmr_cache(), None, NOW, {"15m": perp_journal.PATHS["15m"]}, symbol="XMRUSDT")
    with pytest.raises(ValueError, match="no perp journal"):
        perp_journal.update(_xmr_cache(), None, NOW, {"15m": tmp_path / "eth.json"}, symbol="ETHUSDT")


def test_btc_perp_journal_is_unchanged_next_to_xmr(tmp_path: Path) -> None:
    from tests.test_perp_flow import _store

    btc_paths = {"15m": tmp_path / "perp_short.json", "1h": tmp_path / "perp_mid.json"}
    xmr_paths = {"15m": tmp_path / "xmr_15m.json", "1h": tmp_path / "xmr_1h.json"}
    perp_journal.update(_perp_cache(), {**_store("perp", -2.0, NOW - timedelta(days=6), 24 * 6), "tick": 5.0}, NOW, btc_paths)
    before = {k: p.read_bytes() for k, p in btc_paths.items()}
    perp_journal.update(_xmr_cache(), _xmr_store(NOW - timedelta(days=6), 24 * 6), NOW, xmr_paths, symbol="XMRUSDT")
    assert {k: p.read_bytes() for k, p in btc_paths.items()} == before
    for path in btc_paths.values():
        view = json.loads(path.read_text(encoding="utf-8"))
        assert view["source"] == perp_journal.SOURCE
        for entry in view["entries"]:
            assert entry["symbol"] == "BTCUSDT" and entry["market_type"] == "SPOT"  # BTC as before


def test_offline_xmr_writes_nothing(tmp_path: Path) -> None:
    def offline(symbol: str, interval: str, limit: int) -> list[dict]:
        raise OSError("no route")

    status = perp_journal.update(KlineCache(offline), None, NOW, {"15m": tmp_path / "x.json"}, symbol="XMRUSDT")
    assert status["journals"]["15m"] == {"skipped": "keine Perp-Kerzen"} and not (tmp_path / "x.json").exists()


def test_with_evidence_never_lends_btc_evidence_to_xmr(tmp_path: Path) -> None:
    plans = [{"scenario_type": "RANGE_EDGE_FADE", "symbol": "XMRUSDT"}, {"scenario_type": "RANGE_EDGE_FADE", "symbol": "BTCUSDT"}]
    xmr, btc = pj.with_evidence(plans, "15m")
    assert xmr["evidence_ref"]["reason"] == pj.SYMBOL_NOT_RESEARCHED and xmr["execution_status"] == pj.RESEARCH_ONLY
    assert btc["evidence_ref"].get("reason") != pj.SYMBOL_NOT_RESEARCHED


def test_perp_journal_passes_source_and_market_type_per_symbol(tmp_path: Path, monkeypatch) -> None:
    """The fake perp candles give no plans, so the plumbing is checked at the call into plan_journal.update."""
    seen: list[dict] = []

    def capture(path, series, now, **kwargs):
        seen.append({"path": path, "symbols": {r.get("symbol") for r in series["1m"]}, **kwargs})
        return {"entries": [], "last_plan_candle": None}

    monkeypatch.setattr(pj, "update", capture)
    perp_journal.update(_perp_cache(), None, NOW, {"15m": tmp_path / "b.json"})
    perp_journal.update(_xmr_cache(), None, NOW, {"15m": tmp_path / "x.json"}, symbol="XMRUSDT")
    btc, xmr = seen
    assert btc["market_type"] is None and btc["source"] == perp_journal.SOURCE and btc["symbols"] == {"BTCUSDT"}
    assert xmr["market_type"] == "USDM" and xmr["source"] == perp_journal.XMR_SOURCE and xmr["symbols"] == {"XMRUSDT"}
    assert xmr["path"] == tmp_path / "x.json"


def test_xmr_journal_pages_render_read_only(tmp_path: Path) -> None:
    from src.dashboard.pages.plan_journal import journal_page_for
    from src.dashboard.state import DashboardState

    state = DashboardState()
    state.plan_journal_xmr_15m_path = tmp_path / "xmr_15m.json"
    state.plan_journal_xmr_1h_path = tmp_path / "xmr_1h.json"
    start = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
    journal = pj.update(state.plan_journal_xmr_15m_path, _xmr_series(start), start + timedelta(minutes=30 * 90), market_type="USDM")
    assert journal["entries"]
    page = journal_page_for(state, state.snapshot(), "Plan Journal XMR 15m", token="tok")
    assert "Monero" in page and "XMRUSDT" in page
    assert "Noch keine Pläne" not in page  # the table shows the recorded XMR plans
    assert "/journal/note" not in page  # no note forms: notes are keyed to the BTC journals
    other = journal_page_for(state, state.snapshot(), "Plan Journal XMR 1h", token="tok")
    assert "1h" in other and "Monero" in other
