"""S7 registration from the gate report and the training/validation run (sections 5.1, 5.4, 7)."""
from __future__ import annotations

import importlib.util
import json
import random
import sys
from pathlib import Path

from src.research_lab.data.archive import Dataset
from src.research_lab.data.parse import Kline
from src.research_lab.hypotheses import s7
from src.research_lab.stats.register import HypothesisRegister
from src.research_lab.studies import s7_eval as ev

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "research_lab_s7.py"
spec = importlib.util.spec_from_file_location("research_lab_s7_train", SCRIPT)
script = importlib.util.module_from_spec(spec)
sys.modules["research_lab_s7_train"] = script
spec.loader.exec_module(script)
COUNT_REPORT = ROOT / "docs" / "research_lab" / "reports" / "s7_count_2026-10-26T0938Z.json"


def test_register_only_the_gate_variants(tmp_path: Path) -> None:
    register_path = tmp_path / "REGISTER.jsonl"
    assert script.register_variants(COUNT_REPORT, register_path) == 0
    register = HypothesisRegister(register_path)
    assert sorted(register.variants()) == ["S7-D20-T3", "S7-D20-T4"]
    params = register.variants()["S7-D20-T3"]["params"]
    assert params["channel"] == 20 and params["target_r"] == 3.0 and params["gate_commit"].startswith("2a9d3be")
    # idempotent
    assert script.register_variants(COUNT_REPORT, register_path) == 0
    assert register.m == 2


class FakeStore:
    def __init__(self, bars: dict[str, list[Kline]]) -> None:
        self.bars = bars

    def load_klines(self, refs):
        symbol = refs[0].symbol
        lo, hi = refs[0].start_ms, refs[-1].end_ms
        return [b for b in self.bars[symbol] if lo <= b.open_time < hi]

    def load_funding(self, refs):
        assert refs[0].dataset is Dataset.FUNDING
        return []

    def dataset_hash(self, refs) -> str:
        return "cafebabe"


def _walk(n: int, seed: int, t0: int) -> list[Kline]:
    rng = random.Random(seed)
    price, out = 100.0, []
    for i in range(n):
        o = price
        c = o * (1 + 0.0006 + rng.gauss(0, 0.02))
        h, l = max(o, c) * (1 + abs(rng.gauss(0, 0.006))), min(o, c) * (1 - abs(rng.gauss(0, 0.006)))
        out.append(Kline(t0 + i * s7.INTERVAL_MS, o, h, l, c, 10.0, t0 + (i + 1) * s7.INTERVAL_MS - 1, 5.0))
        price = c
    return out


def test_train_refuses_without_register_entries(tmp_path: Path) -> None:
    assert script.train(FakeStore({}), tmp_path, register_path=tmp_path / "empty.jsonl") == 1
    assert not list(tmp_path.glob("s7_train_*"))


def test_train_writes_report_trades_and_statuses(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ev, "POOL_PER_DECILE", 40)
    monkeypatch.setattr(ev, "MIN_POOL", 80)
    monkeypatch.setattr(ev, "POOL_FACTOR", 2)
    monkeypatch.setattr(script, "_commit", lambda: "testcommit")
    t0 = 1_577_836_800_000  # 2020-01-01
    bars = {s: _walk(5 * 366 * 6, 20 + i, t0) for i, s in enumerate(script.SYMBOLS)}
    register_path = tmp_path / "REGISTER.jsonl"
    script.register_variants(COUNT_REPORT, register_path)
    out = tmp_path / "reports"
    assert script.train(FakeStore(bars), out, runs=25, register_path=register_path, commit_register=True, progress=lambda line: None) == 0
    files = sorted(out.iterdir())
    assert len(files) == 3
    payload = json.loads(next(f for f in files if f.name.endswith("Z.json") and "trades" not in f.name).read_text())
    assert payload["registered"] == ["S7-D20-T3", "S7-D20-T4"] and payload["holm_m"] == 60
    assert set(payload["variants"]) == {v.variant_id for v in s7.S7_VARIANTS}
    for vid, entry in payload["variants"].items():
        assert set(entry["sections"]) == {"train", "validation"}
        tr = entry["sections"]["train"]
        assert tr["summary"]["n"] > 0 and set(tr["baselines"]) == {"A", "A'", "C", "B"}
        assert 0 < tr["baselines"]["A"]["p"] <= 1
        assert "training_verdict" in entry
        if vid.startswith("S7-D55"):
            assert entry["status"] == "nicht registriert (nur Nachbar)"
        else:
            assert entry["status"] in {"failed_train", "failed_validation", "candidate", "not_selected"}
    assert len(payload["candidates"]) <= 2
    trades = json.loads(next(f for f in files if f.name.endswith("trades.json")).read_text())
    assert trades and {"variant", "section", "symbol", "r", "reason", "hit"} <= set(trades[0])
    text = next(f for f in files if f.suffix == ".md").read_text()
    assert "## Urteile" in text and "Walk-Forward" in text and "Kandidaten für den Holdout" in text
    statuses = {v: e["status"] for v, e in HypothesisRegister(register_path).variants().items()}
    assert set(statuses) == {"S7-D20-T3", "S7-D20-T4"}
    assert all(st in {"failed_train", "failed_validation", "candidate", "not_selected"} for st in statuses.values())
