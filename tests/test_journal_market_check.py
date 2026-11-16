import json
from pathlib import Path

from src.dashboard.journal_market_check import check


def _write(path: Path, market: str) -> None:
    path.write_text(json.dumps({"entries": [{"id": "a", "market_type": market, "created_at": "2026-11-17T00:00:00+00:00"}]}), encoding="utf-8")


def test_check_flags_a_perp_journal_with_the_spot_label(tmp_path: Path) -> None:
    _write(tmp_path / "tim_plan_journal_perp_short.json", "SPOT")
    _write(tmp_path / "tim_plan_journal_short.json", "SPOT")
    assert len(check(tmp_path)) == 1
    _write(tmp_path / "tim_plan_journal_perp_short.json", "USDM")
    assert check(tmp_path) == []
    assert check(tmp_path, since="2026-12-01") == []
