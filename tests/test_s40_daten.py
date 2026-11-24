"""S40 package 1: loader keeps the holdout lock, bars and gaps are right, report rules match the plan."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import zipfile
from datetime import date

import pytest

from src.research_lab.studies import s40_daten as s

D = date(2021, 3, 4)
T0 = s._day_ms(D)


def _zip(rows: list[str], name: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name.replace(".zip", ".csv"), "\n".join(rows) + "\n")
    return buf.getvalue()


def _fetcher(files: dict[str, bytes]):
    calls = []

    def fetch(url: str) -> bytes:
        calls.append(url)
        return files[url.rsplit("/", 1)[1].split("?")[0]]
    fetch.calls = calls
    return fetch


def test_holdout_days_are_refused_before_any_request():
    f = _fetcher({})
    with pytest.raises(s.HoldoutRefused):
        s.load_binance_day(__import__("pathlib").Path("/nonexistent"), "BTCUSDT", date(2025, 1, 1), f)
    with pytest.raises(s.HoldoutRefused):
        s.deribit_day(date(2025, 6, 1), f)
    with pytest.raises(s.HoldoutRefused):
        s.load_funding_month(__import__("pathlib").Path("/nonexistent"), "BTCUSDT", 2025, 1, f)
    with pytest.raises(s.HoldoutRefused):
        s.main(["laden", "--ziel", "/tmp/x", "--bis", "2025-01-02"])
    assert f.calls == []
    assert s.days(date(2024, 12, 30), date(2026, 1, 1))[-1] == date(2024, 12, 31)


def test_bars_and_gaps():
    trades = [(T0 + 1000, 100.0, 1.0, 1), (T0 + 2000, 101.0, 2.0, -1), (T0 + 400_000, 99.0, 1.0, 1),
              (T0 + 86_400_000 - 1, 100.0, 1.0, 1)]
    bars, st = s.bars_and_gaps(trades, D)
    assert bars[0] == [T0, 100.0, 101.0, 100.0, 101.0, 1.0, 2.0, 2, T0 + 2000]
    assert bars[1][0] == T0 + 300_000 and bars[1][4] == 99.0
    assert st["trades"] == 4 and st["gaps"] == 1  # 400 s gap is below 10 min, the long night gap counts
    assert st["gap_ms"] == (T0 + 86_400_000 - 1) - (T0 + 400_000)


def test_binance_day_verifies_checksum_and_keeps_only_bars(tmp_path):
    name = f"BTCUSDT-aggTrades-{D.isoformat()}.zip"
    rows = ["agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker",
            f"1,100,1,1,1,{T0 + 5}000,true", f"2,101,2,2,2,{(T0 + 60_000) * 1000},false"]  # second stamp in microseconds
    z = _zip(rows, name)
    good = {name: z, name + ".CHECKSUM": f"{hashlib.sha256(z).hexdigest()}  {name}".encode()}
    st = s.load_binance_day(tmp_path, "BTCUSDT", D, _fetcher(good))
    assert st["ok"] and st["trades"] == 2
    text = gzip.decompress((tmp_path / "bars" / "BTCUSDT" / f"{D.isoformat()}.csv.gz").read_bytes()).decode()
    assert text.splitlines()[1].split(",")[5:7] == ["2.0", "1.0"]  # buy 2 (aggressive buyer), sell 1
    assert not list(tmp_path.rglob("*.zip"))
    again = s.load_binance_day(tmp_path, "BTCUSDT", D, _fetcher({}))  # cached, no request
    assert again == st
    bad = {name: z, name + ".CHECKSUM": f"{'0' * 64}  {name}".encode()}
    st2 = s.load_binance_day(tmp_path, "ETHUSDT", D, _fetcher({k.replace("BTC", "ETH"): v for k, v in bad.items()}))
    assert not st2["ok"] and (tmp_path / "status" / "binance" / "ETHUSDT" / f"{D.isoformat()}.failed.json").exists()


def test_deribit_paginates_and_dedupes(tmp_path):
    pages = [
        {"result": {"has_more": True, "trades": [{"trade_id": "1", "timestamp": T0 + 10, "iv": 50},
                                                  {"trade_id": "2", "timestamp": T0 + 20, "iv": None}]}},
        {"result": {"has_more": False, "trades": [{"trade_id": "2", "timestamp": T0 + 20},
                                                   {"trade_id": "3", "timestamp": T0 + 30, "block_trade_id": "B"}]}},
    ]
    it = iter(pages)
    urls = []

    def fetch(url):
        urls.append(url)
        return json.dumps(next(it)).encode()
    st = s.load_deribit_day(tmp_path, D, fetch, pause=0)
    assert st == {**st, "ok": True, "trades": 3, "block_or_combo": 1, "no_iv": 2}
    assert f"start_timestamp={T0 + 20}" in urls[1]
    rows = [json.loads(x) for x in gzip.decompress((tmp_path / "deribit" / f"{D.isoformat()}.jsonl.gz").read_bytes()).splitlines()]
    assert [r["trade_id"] for r in rows] == ["1", "2", "3"] and rows[0]["recv_ms"] == T0 + 10 + 2000


def test_report_rules(tmp_path):
    ok = {"ok": True, "trades": 10, "gap_ms": 0}
    for d in s.days(date(2020, 1, 1), date(2020, 1, 31)):
        p = tmp_path / "status" / "binance" / "BTCUSDT" / f"{d.isoformat()}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({**ok, "day": d.isoformat(), "gap_ms": 3_600_000 if d.day == 1 else 0}))
        q = tmp_path / "status" / "deribit" / f"{d.isoformat()}.json"
        q.parent.mkdir(parents=True, exist_ok=True)
        q.write_text(json.dumps({"ok": True, "day": d.isoformat(), "trades": 49 if d.day == 2 else 60, "block_or_combo": 0}))
    rep = s.report(tmp_path)
    jan = rep["binance"]["BTCUSDT"]["months"]["2020-01"]
    assert jan["valid"] and jan["gap_share"] == pytest.approx(1 / 31 / 24, abs=1e-6)
    assert not rep["binance"]["BTCUSDT"]["months"]["2020-02"]["valid"]
    assert rep["binance"]["BTCUSDT"]["testable"] is False
    assert not rep["deribit"]["months"]["2020-01"]["valid"]  # one day below 50 trades
    assert "2025-01" not in rep["deribit"]["months"]
