"""S7 feasibility count script: archives, projection from the weakest year, report files."""
from __future__ import annotations

import importlib.util
import json
import random
import sys
from pathlib import Path

from src.research_lab.data.archive import Dataset
from src.research_lab.data.parse import Kline
from src.research_lab.hypotheses import s7

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "research_lab_s7.py"
spec = importlib.util.spec_from_file_location("research_lab_s7", SCRIPT)
script = importlib.util.module_from_spec(spec)
sys.modules["research_lab_s7"] = script
spec.loader.exec_module(script)


def test_archives_cover_warmup_and_stop_before_holdout() -> None:
    refs = script.all_refs()
    assert len(refs) == 2 * (60 + 60 + 52)
    assert all(not r.touches_holdout for r in refs)
    klines = [r for r in refs if r.dataset is Dataset.KLINES]
    assert {r.interval for r in klines} == {"4h"}
    assert min(r.year * 100 + r.month for r in klines if r.symbol == "SOLUSDT") == 202009
    assert script.coin_months_by_year() == {2020: 27, 2021: 36, 2022: 36, 2023: 36, 2024: 36}
    assert script.HOLDOUT_COIN_MONTHS == 63 and script.HOLDOUT_MONTHS == 21


def test_projection_uses_the_weakest_year_for_each_figure() -> None:
    signals = {2020: 54, 2021: 72, 2022: 36, 2023: 90, 2024: 72}  # per coin-month: 2.0, 2.0, 1.0, 2.5, 2.0
    weeks = {2020: 20, 2021: 36, 2022: 30, 2023: 40, 2024: 36}  # per month: 1.67, 3, 2.5, 3.33, 3
    projected, projected_weeks, weak_signal, weak_week = script.project(signals, weeks)
    assert weak_signal == 2022 and abs(projected - 63.0) < 1e-9
    assert weak_week == 2020 and abs(projected_weeks - 20 / 12 * 21) < 1e-9
    # a missing year counts as zero
    assert script.project({2021: 10}, {2021: 10})[0] == 0.0


class FakeStore:
    def __init__(self, bars: dict[str, list[Kline]]) -> None:
        self.bars = bars

    def load_klines(self, refs):
        symbol = refs[0].symbol
        lo, hi = refs[0].start_ms, refs[-1].end_ms
        return [b for b in self.bars[symbol] if lo <= b.open_time < hi]

    def dataset_hash(self, refs) -> str:
        return "deadbeef"


def _walk(n: int, seed: int, t0: int) -> list[Kline]:
    rng = random.Random(seed)
    price, out = 100.0, []
    for i in range(n):
        o = price
        c = o * (1 + 0.001 + rng.gauss(0, 0.02))
        h, l = max(o, c) * 1.005, min(o, c) * 0.995
        out.append(Kline(t0 + i * s7.INTERVAL_MS, o, h, l, c, 10.0, t0 + (i + 1) * s7.INTERVAL_MS - 1, 5.0))
        price = c
    return out


def test_count_writes_json_and_markdown_without_outcomes(tmp_path: Path, monkeypatch) -> None:
    t0 = 1_577_836_800_000  # 2020-01-01
    bars = {s: _walk(6 * 365 * 6, i, t0) for i, s in enumerate(script.SYMBOLS)}
    monkeypatch.setattr(script, "_commit", lambda: "testcommit")
    assert script.count(FakeStore(bars), tmp_path) == 0
    files = sorted(tmp_path.iterdir())
    assert [f.suffix for f in files] == [".json", ".md"]
    payload = json.loads(files[0].read_text())
    assert payload["outcome_blind"] is True and payload["commit"] == "testcommit"
    assert set(payload["variants"]) == {v.variant_id for v in s7.S7_VARIANTS}
    for v in payload["variants"].values():
        assert set(v["counts"]) == {f"{s}/{sec}" for s in script.SYMBOLS for sec in script.SECTIONS}
        assert v["totals"]["train"]["lower"] <= v["totals"]["train"]["upper"]
        assert isinstance(v["passes_gate"], bool)
        assert set(v["by_year"]) == {"2020", "2021", "2022", "2023", "2024"}
    text = files[1].read_text()
    assert "ergebnisblind" in text and "Trefferquote" in text
    for forbidden in ("E[R]", "Erwartungswert", "hit_rate", "profit"):
        assert forbidden not in text
