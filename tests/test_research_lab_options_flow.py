"""A1/A2 options-flow recorder and data contract. Fixtures follow the Deribit v2 docs (not a live capture)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.research_lab.bitunix.recorder import StorageError
from src.research_lab.options_flow import contract, recorder

T0 = 1_800_000_000_000


def trade(tid: str, ts: int, **kw) -> dict:
    base = {"trade_id": tid, "timestamp": ts, "instrument_name": "BTC-27MAR26-80000-C", "direction": "buy",
            "price": 0.05, "amount": 2.0, "index_price": 80000.0, "iv": 55.0, "mark_price": 0.049}
    return base | kw


class FakeApi:
    def __init__(self, trades: list[dict], page: int = 1000) -> None:
        self.trades, self.page, self.calls, self.fail = trades, page, [], 0

    def __call__(self, method: str, params):
        self.calls.append((method, dict(params)))
        if self.fail:
            self.fail -= 1
            raise OSError("network down")
        if method == "get_last_trades_by_currency_and_time":
            rows = [t for t in self.trades if params["start_timestamp"] <= t["timestamp"] <= params["end_timestamp"]]
            rows.sort(key=lambda t: (t["timestamp"], t["trade_id"]))
            return {"result": {"trades": rows[: self.page], "has_more": len(rows) > self.page}}
        if method == "get_book_summary_by_currency":
            return {"result": [{"instrument_name": "BTC-27MAR26-80000-C", "open_interest": 10.0, "mark_iv": 55.0}]}
        if method == "get_volatility_index_data":
            return {"result": {"data": [[T0, 50, 51, 49, 50]]}}
        raise AssertionError(method)


class Clock:
    def __init__(self) -> None:
        self.t = T0 / 1000

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s


def run(root: Path, api, seconds: float = 25, clock: Clock | None = None, **kw):
    clock = clock or Clock()
    return recorder.record(root, "BTC", stop_after=seconds, fetch=api, clock=clock, sleep=clock.sleep,
                           min_free_bytes=0, disk_free=lambda _p: 10**12, **kw)


def test_normalize_trade_derives_premium_and_flags():
    n = contract.normalize_trade(trade("a", T0 - 5, block_trade_id="b1"), T0)
    assert n["premium_usd"] == pytest.approx(0.05 * 2.0 * 80000.0)
    assert n["notional_usd"] == 160000.0 and n["is_call"] and n["strike"] == 80000.0
    assert n["side"] == "buy" and n["block"] and not n["liquidation"] and n["latency_ms"] == 5


@pytest.mark.parametrize("patch,reason", [
    ({"direction": "up"}, "bad_direction"), ({"amount": 0}, "bad_amount"), ({"price": -1}, "bad_price"),
    ({"instrument_name": "BTC-PERPETUAL"}, "bad_instrument"), ({"timestamp": "x"}, "bad_timestamp"),
    ({"index_price": float("nan")}, "bad_index_price"), ({"trade_id": ""}, "bad_trade_id"),
])
def test_normalize_trade_rejects(patch, reason):
    with pytest.raises(contract.Rejected) as exc:
        contract.normalize_trade(trade("a", T0) | patch, T0)
    assert exc.value.args[0] == reason


def test_missing_field_rejected():
    raw = trade("a", T0)
    del raw["index_price"]
    with pytest.raises(contract.Rejected, match="missing_index_price"):
        contract.normalize_trade(raw, T0)


def test_record_writes_raw_unchanged_and_audits(tmp_path):
    rows = [trade("a", T0 - 3000), trade("b", T0 - 2000, direction="sell"), trade("bad", T0 - 1000, amount=0)]
    api = FakeApi(rows)
    counts = run(tmp_path, api)
    assert counts["trades"] == 3 and counts["summaries"] >= 1 and counts["dvol"] >= 1
    seg = next((tmp_path / "BTCOPTTRADES").glob("*.jsonl.gz"))
    from src.research_lab.bitunix.recorder import read_segment
    stored, complete = read_segment(seg)
    assert complete and [r["raw"] for r in stored if r["kind"] == "trade"] == rows  # raw byte-for-byte
    audit = contract.audit(tmp_path)
    assert audit["trades"] == 2 and audit["rejected"] == {"bad_amount": 1} and audit["duplicates"] == 0
    assert [t["trade_id"] for t in contract.iter_trades(tmp_path)] == ["a", "b"]


def test_no_duplicates_across_polls_and_pages(tmp_path):
    rows = [trade(f"t{i}", T0 - 5000 + i // 3) for i in range(9)]  # three trades share a millisecond
    api = FakeApi(rows, page=4)
    run(tmp_path, api, seconds=35)
    assert contract.audit(tmp_path)["trades"] == 9
    assert contract.audit(tmp_path)["duplicates"] == 0


def test_more_trades_in_one_millisecond_than_a_page_is_counted_not_silent(tmp_path):
    rows = [trade(f"t{i}", T0 - 5000) for i in range(5)]
    counts = run(tmp_path, FakeApi(rows, page=2), seconds=15)
    assert counts["cursor_skips"] >= 1  # possible loss is visible in status.json, never silent


def test_error_keeps_cursor_and_recovers(tmp_path):
    api = FakeApi([trade("a", T0 - 100)])
    api.fail = 2
    counts = run(tmp_path, api, seconds=120)
    assert counts["errors"] >= 2 and counts["trades"] == 1 and counts["consecutive_errors"] == 0
    st = json.loads((tmp_path / "status.json").read_text())
    assert st["state"] == "stopped" and st["cursor"]["ts_ms"] == T0 - 100 and "OSError" in st["last_error"]


def test_restart_writes_gap_and_resumes_cursor(tmp_path):
    run(tmp_path, FakeApi([trade("a", T0 - 100)]), seconds=15)
    clock = Clock()
    clock.t += 600
    api = FakeApi([trade("a", T0 - 100), trade("b", T0 + 300_000)])
    run(tmp_path, api, seconds=15, clock=clock)
    audit = contract.audit(tmp_path)
    assert audit["trades"] == 2 and audit["duplicates"] == 0 and len(audit["gaps"]) == 1
    first_call = next(c for c in api.calls if c[0] == "get_last_trades_by_currency_and_time")
    assert first_call[1]["start_timestamp"] == T0 - 100  # resumed from the stored cursor, not from "now"


def test_storage_error_is_fatal_and_marked(tmp_path):
    clock = Clock()
    with pytest.raises(StorageError):
        recorder.record(tmp_path, "BTC", stop_after=30, fetch=FakeApi([]), clock=clock, sleep=clock.sleep,
                        min_free_bytes=10**13, disk_free=lambda _p: 1)
    assert json.loads((tmp_path / "status.json").read_text())["state"] == "failed"


def test_currency_allowlist(tmp_path):
    with pytest.raises(ValueError):
        recorder.streams("DOGE")


def test_only_public_read_methods_are_called(tmp_path):
    api = FakeApi([])
    run(tmp_path, api)
    assert {m for m, _ in api.calls} <= {"get_last_trades_by_currency_and_time", "get_book_summary_by_currency",
                                          "get_volatility_index_data"}
