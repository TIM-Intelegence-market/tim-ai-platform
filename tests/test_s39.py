"""S39 on synthetic hour candles (no real data, no holdout): moves, types, forward returns, Holm, verdicts."""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

import pytest

from src.research_lab.studies import s39
from src.research_lab.studies.s17 import Candle


def _candles(first: date, days: int, spikes: dict[int, float], buy_heavy: bool = True) -> dict[int, Candle]:
    start = datetime(first.year, first.month, first.day, tzinfo=timezone.utc)
    out, price = {}, 30000.0
    for i in range(days * 24):
        ms = int((start + timedelta(hours=i)).timestamp() * 1000)
        step = spikes.get(i, 0.002 * math.sin(i * 1.7))
        close = price * (1 + step)
        buy, sell = (300, 100) if (i in spikes and buy_heavy == (step > 0)) else (100, 100)
        out[ms] = Candle(ms, True, price, max(price, close), min(price, close), close, 10, buy, sell)
        price = close
    return out


def test_moves_are_typed_by_direction_and_flow() -> None:
    spikes = {24 * 10: 0.05, 24 * 20: -0.05}
    rows = s39.rows_from(_candles(date(2021, 1, 1), 30, spikes))
    found = s39.moves(rows)
    assert [m["type"] for m in found] == ["UP_FLOW", "DOWN_OHNE"]  # takers sold nothing extra in the down hour
    assert found[0]["flow_share"] == 0.5 and found[1]["flow_share"] == 0.0


def test_continuation_after_up_moves_is_found_against_random_hours() -> None:
    days = 4 * 365
    spikes, i = {}, 24 * 10
    while i < days * 24 - 48:
        spikes[i] = 0.05
        for k in range(1, 25):
            spikes[i + k] = 0.002  # 24 hours of drift in the move's direction afterwards
        i += 24 * 15
    rows = s39.rows_from(_candles(date(2020, 1, 1), days, spikes))
    train = s39.evaluate(rows, *s39.TRAIN, draws=200)
    up = train["types"]["UP_FLOW"]
    assert up["n"] >= s39.MIN_TRAIN and up["excess"] > s39.MIN_EFFECT and up["holm_p"] <= s39.ALPHA
    assert set(up["leave_one_year_out"]) == {"2020", "2021", "2022", "2023"}
    verdicts = s39.verdict(train)
    assert verdicts["UP_FLOW"] == "Training bestanden: Fortsetzung"
    assert verdicts["DOWN_FLOW"] == "nicht prüfbar"
    assert "Validierung noch nicht gelesen" in s39.report(train, None, verdicts)


def test_forward_needs_both_hours() -> None:
    t = datetime(2021, 1, 1, tzinfo=timezone.utc)
    closes = {t: 100.0, t + timedelta(hours=24): 103.0}
    assert s39.forward(closes, t, 24) == pytest.approx(0.03)
    assert s39.forward(closes, t, 4) is None


def test_holdout_hours_are_refused() -> None:
    rows = s39.rows_from(_candles(date(2024, 12, 25), 10, {}))
    with pytest.raises(PermissionError):
        s39.evaluate(rows, *s39.VALID)


def test_measurement_starts_when_the_move_is_known_to_be_over() -> None:
    rows = s39.rows_from(_candles(date(2021, 1, 1), 30, {24 * 10: 0.05}))
    move = s39.moves(rows)[0]
    assert move["known"] == move["end"] + s39.QUIET  # no flag may follow within 4 h, so only then is the end known


def test_one_year_is_never_enough() -> None:
    block = {"n": 30, "holm_p": 0.001, "excess": 0.02, "years": 1, "leave_one_year_out": {}}
    assert s39.verdict({"types": {"UP_FLOW": block}})["UP_FLOW"] == "nicht belegt"
    small = {"types": {"UP_FLOW": {"n": 2, "excess": 0.01}}}
    passed = {**block, "years": 2, "leave_one_year_out": {"2020": 0.01, "2021": 0.02}}
    assert s39.verdict({"types": {"UP_FLOW": passed}}, small)["UP_FLOW"] == "nicht prüfbar (Validierung zu klein)"


def test_validation_needs_the_frozen_training_run(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        s39.main(["--root", str(tmp_path), "--out", str(tmp_path), "--phase", "valid"])
    (tmp_path / "s39_train.json").write_text("{}")
    with pytest.raises(FileExistsError):
        s39.main(["--root", str(tmp_path), "--out", str(tmp_path), "--phase", "train"])
