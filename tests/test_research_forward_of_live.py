"""Stage B: the recorder's days equal the archive's, today's closed minutes give the full day's trades so far."""
from __future__ import annotations

import csv
import dataclasses
import io
import json
import random
import zipfile
from datetime import date, datetime, timedelta, timezone

import pytest

from src.research_lab.data.aggtrades import read_rows
from src.research_lab.forward import of_live, of_paper
from src.research_lab.forward.live_recorder import ChainError, TradeRecorder
from src.research_lab.of2 import engine
from src.research_lab.orderflow_ml.bars import DayProfile, reduce_trades_with_profile, ticks_from_rows
from tests.test_research_forward_of_paper import CFG, FIRST, START, FakeStore

DAY1 = date(2026, 11, 20)


def ms(day: date, seconds: float = 0.0) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp() * 1000 + seconds * 1000)


def synthetic_trades(first_day: date, days: int, seed: int = 3) -> list[dict]:
    rng, price, out, t = random.Random(seed), 65_000.0, [], ms(first_day, -40.0)
    agg = 1_000_000
    end = ms(first_day + timedelta(days=days), 40.0)
    while t < end:
        t += rng.randint(1, 45_000)
        price = max(1000.0, price + rng.gauss(0, 15))
        qty = rng.randint(1, 50_000) / 100_000
        out.append({"a": agg, "p": f"{price:.2f}", "q": f"{qty:.5f}", "f": agg * 3, "l": agg * 3 + 2, "T": t,
                    "m": rng.random() < 0.5, "M": True})
        agg += 1
    return out


class FakeBinance:
    def __init__(self, trades: list[dict]) -> None:
        self.trades = trades
        self.visible_until = 0   # ms; trades after it are "not happened yet"
        self.calls = 0

    def __call__(self, url: str):
        self.calls += 1
        q = dict(part.split("=") for part in url.split("?", 1)[1].split("&"))
        live = [t for t in self.trades if t["T"] <= self.visible_until]
        if "fromId" in q:
            first = int(q["fromId"])
            return [t for t in live if t["a"] >= first][: int(q["limit"])]
        start, end = int(q["startTime"]), int(q["endTime"])
        return [t for t in live if start <= t["T"] <= end][:1]


def recorder_at(tmp_path, trades, now_ms):
    api = FakeBinance(trades)
    api.visible_until = now_ms
    clock = [now_ms / 1000]
    rec = TradeRecorder(tmp_path / "trades", fetch=api, clock=lambda: clock[0], sleep=lambda s: None)
    return rec, api, clock


def catch_up(rec: TradeRecorder) -> None:
    while rec.poll() == 1000:
        pass


def archive_bars(trades: list[dict], day: date):
    """What the published archive gives: same rows, time in microseconds (spot archives since 2025)."""
    rows = [[str(t["a"]), t["p"], t["q"], str(t["f"]), str(t["l"]), str(t["T"] * 1000), str(t["m"]), "True"]
            for t in trades if ms(day) <= t["T"] < ms(day + timedelta(days=1))]
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows([["agg_trade_id", "price"]] + rows)
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as z:
        z.writestr(f"BTCUSDT-aggTrades-{day}.csv", buf.getvalue())
    return reduce_trades_with_profile(ticks_from_rows(read_rows(raw.getvalue())), ms(day))


def test_recorded_day_equals_the_archive_day(tmp_path):
    trades = synthetic_trades(DAY1, 3)
    rec, api, clock = recorder_at(tmp_path, trades, ms(DAY1, 10 * 3600))
    catch_up(rec)
    assert rec.day_state(DAY1) == "open" and rec.dir.joinpath(f"{DAY1 - timedelta(days=1)}.csv").exists() is False
    api.visible_until = ms(DAY1 + timedelta(days=2), 3600)
    catch_up(rec)
    for day in (DAY1, DAY1 + timedelta(days=1)):
        assert rec.day_state(day) == "complete"
        bars, quality, profile = rec.reduce(day)
        a_bars, a_quality, a_profile = archive_bars(trades, day)
        assert bars == a_bars and profile == a_profile
        assert quality.id_gaps == 0 and quality.rows == a_quality.rows
    assert rec.day_state(DAY1 + timedelta(days=2)) == "open"


def test_closed_minutes_are_the_full_day_cut_at_that_minute(tmp_path):
    trades = synthetic_trades(DAY1, 2)
    rec, api, _ = recorder_at(tmp_path, trades, ms(DAY1, 13.5 * 3600))
    catch_up(rec)
    until = rec.closed_until_ms(DAY1)
    assert until is not None and until <= ms(DAY1, 13.5 * 3600) and until % 60_000 == 0
    bars, _, profile = rec.reduce(DAY1, until)
    full_bars, _, full_profile = archive_bars(trades, DAY1)
    k = (until - ms(DAY1)) // 60_000
    assert len(bars) == k and bars == full_bars[:k]
    assert profile == DayProfile(full_profile.day_start_ms, full_profile.width_e8,
                                 tuple(e for e in full_profile.entries if e[0] < k))


def test_restart_resumes_the_chain_without_a_hole(tmp_path):
    trades = synthetic_trades(DAY1, 2)
    rec, api, clock = recorder_at(tmp_path, trades, ms(DAY1, 6 * 3600))
    catch_up(rec)
    state = rec.state()
    rec.poll()   # nothing new: an empty answer changes nothing
    assert rec.state() == state
    # the recorder was off for 20 hours; the next start fetches from the stored id on
    api.visible_until = ms(DAY1 + timedelta(days=1), 2 * 3600)
    again = TradeRecorder(tmp_path / "trades", fetch=api, clock=lambda: clock[0], sleep=lambda s: None)
    catch_up(again)
    assert again.day_state(DAY1) == "complete"
    assert again.reduce(DAY1)[0] == archive_bars(trades, DAY1)[0]


def test_crash_between_rows_and_state_only_repeats_rows(tmp_path):
    trades = synthetic_trades(DAY1, 2)
    rec, api, _ = recorder_at(tmp_path, trades, ms(DAY1, 3 * 3600))
    catch_up(rec)
    state = rec.state()
    api.visible_until = ms(DAY1, 5 * 3600)
    rec.poll()
    (rec.dir / "state.json").write_text(json.dumps(state))   # as if the state write never happened
    api.visible_until = ms(DAY1 + timedelta(days=1), 600)
    catch_up(rec)
    with rec.day_path(DAY1).open() as handle:
        assert len(handle.readlines()) > len([t for t in trades if t["T"] < ms(DAY1 + timedelta(days=1))])
    bars, quality, _ = rec.reduce(DAY1)
    assert quality.id_gaps == 0
    assert bars == archive_bars(trades, DAY1)[0]


def test_a_skipped_id_stores_nothing(tmp_path):
    trades = synthetic_trades(DAY1, 1)
    del trades[50]
    rec, api, _ = recorder_at(tmp_path, trades, ms(DAY1, 2 * 3600))
    state = rec._start()
    with pytest.raises(ChainError):
        rec.poll()
    assert rec.state() == state and not rec.day_path(DAY1).exists()


def test_trade_back_across_midnight_blocks_both_days(tmp_path):
    trades = synthetic_trades(DAY1, 2)
    later = next(i for i, t in enumerate(trades) if t["T"] >= ms(DAY1 + timedelta(days=1), 60))
    trades[later + 1]["T"] = ms(DAY1 + timedelta(days=1), -1)
    rec, api, _ = recorder_at(tmp_path, trades, ms(DAY1 + timedelta(days=1), 3600))
    catch_up(rec)
    assert rec.day_state(DAY1) == "blocked" and rec.day_state(DAY1 + timedelta(days=1)) == "blocked"


def test_live_store_prefers_the_archive_and_falls_back_to_a_complete_recorder_day(tmp_path):
    trades = synthetic_trades(DAY1, 2)
    rec, api, _ = recorder_at(tmp_path, trades, ms(DAY1, 3600))
    catch_up(rec)
    api.visible_until = ms(DAY1 + timedelta(days=1), 3600)
    catch_up(rec)

    class NoArchive:
        def cached(self, day):
            return None

        def fetch(self, day):
            raise FileNotFoundError("404")

    now = [datetime.fromtimestamp(ms(DAY1 + timedelta(days=1), 3600) / 1000, tz=timezone.utc)]
    store = of_live.LiveStore(NoArchive(), rec, clock=lambda: now[0])  # type: ignore[arg-type]
    store.fetch(DAY1)
    assert store.sources[DAY1] == "recorder" and store.load(DAY1) == archive_bars(trades, DAY1)[0]
    assert store.cached(DAY1) == {"source": "recorder"}
    now[0] += timedelta(hours=2)
    assert store.cached(DAY1) is None   # the archive is asked again after an hour
    with pytest.raises(FileNotFoundError):
        store.fetch(DAY1 - timedelta(days=1))   # recorder never saw it
    part = store.partial(DAY1 + timedelta(days=1))
    assert part is not None and 55 <= len(part[0]) <= 60   # up to the minute of the newest trade


class FakeLive(FakeStore):
    """Stage A's synthetic days; today's closed minutes are the full day cut at ``until``."""

    def __init__(self) -> None:
        super().__init__()
        self.until: int | None = None

    def partial(self, day):
        if self.until is None:
            return None
        bars, profile = self.days[day]
        k = (self.until - engine._ms(day)) // 60_000
        return bars[:k], DayProfile(profile.day_start_ms, profile.width_e8,
                                    tuple(e for e in profile.entries if e[0] < k)), self.until


def test_live_journal_gives_the_full_days_trades_minute_by_minute(tmp_path):
    days = 12
    full = of_paper.PaperJournal(tmp_path / "a", cfg=CFG, store=FakeStore(),
                                 clock=lambda: START + timedelta(days=days + 1))
    full.folder.mkdir(parents=True)
    (full.folder / "start.json").write_text(json.dumps({"started_at": "2026-11-10T12:00:00Z", "first_day": "2026-11-11",
                                                        "config_digest": CFG.digest(), "config": CFG.as_dict()}))
    full.step()
    reference = json.loads((full.folder / "journal.json").read_text())["trades"]
    assert reference, "synthetic days must give trades for this test to mean anything"
    today = (START + timedelta(days=days)).date()

    store, now = FakeLive(), [START]
    live = of_live.LiveJournal(tmp_path / "b", trades_root=tmp_path, cfg=CFG, store=store,  # type: ignore[arg-type]
                               clock=lambda: now[0])
    live.start()
    for hour in range(1, 24):
        now[0] = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=hour, seconds=30)
        store.until = engine._ms(today) + hour * 3_600_000
        status = live.step()
        assert status["live_until"]
        got = json.loads((live.folder / "journal.json").read_text())["trades"]
        expected = [t for t in reference if t["exit_ms"] < store.until]
        assert got == expected
    events = [json.loads(x) for x in (live.folder / "events.jsonl").read_text().splitlines()]
    assert len(events) == len(expected)   # every trade logged once, as it closed


def test_live_journal_keeps_the_frozen_digest(tmp_path):
    store = FakeLive()
    live = of_live.LiveJournal(tmp_path, trades_root=tmp_path, cfg=CFG, store=store, clock=lambda: START)  # type: ignore[arg-type]
    live.start()
    with pytest.raises(of_paper.PaperError):
        of_live.LiveJournal(tmp_path, trades_root=tmp_path, cfg=dataclasses.replace(CFG, min_rr=9.0), store=store).start()


def test_no_today_while_a_day_is_missing(tmp_path):
    store, now = FakeLive(), [START + timedelta(days=5, hours=3)]
    store.published = date(2026, 11, 12)
    store.until = engine._ms(now[0].date()) + 3 * 3_600_000
    live = of_live.LiveJournal(tmp_path, trades_root=tmp_path, cfg=CFG, store=store, clock=lambda: now[0])  # type: ignore[arg-type]
    live.start()
    status = live.step()
    assert status["last_day"] == "2026-11-12" and "live_until" not in status


def test_stage_a_keeps_its_once_a_day_run():
    assert of_paper.PaperJournal.recompute_each_step is False and of_live.LiveJournal.recompute_each_step is True
    assert FIRST == date(2026, 11, 11)


def _live_store(rec, now_ms):
    class NoArchive:
        def cached(self, day):
            return None

        def fetch(self, day):
            raise FileNotFoundError("404")

    now = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc)
    return of_live.LiveStore(NoArchive(), rec, clock=lambda: now)  # type: ignore[arg-type]


def test_partial_from_the_recorder_equals_the_archive_cut(tmp_path):
    trades = synthetic_trades(DAY1, 1)
    now = ms(DAY1, 7 * 3600 + 20)
    rec, api, _ = recorder_at(tmp_path, trades, now)
    catch_up(rec)
    bars, profile, until = _live_store(rec, now).partial(DAY1)
    full_bars, _, full_profile = archive_bars(trades, DAY1)
    assert bars == full_bars[: len(bars)] and until == ms(DAY1) + len(bars) * 60_000
    assert profile.entries == tuple(e for e in full_profile.entries if e[0] < len(bars))


def test_a_time_regression_today_stops_the_partial_run(tmp_path):
    trades = synthetic_trades(DAY1, 1)
    i = next(i for i, t in enumerate(trades) if t["T"] > ms(DAY1, 3 * 3600))
    trades[i + 1]["T"] = trades[i]["T"] - 120_000
    now = ms(DAY1, 5 * 3600)
    rec, api, _ = recorder_at(tmp_path, trades, now)
    catch_up(rec)
    assert _live_store(rec, now).partial(DAY1) is None


def test_recorder_days_keep_the_paper_window(tmp_path):
    from src.research_lab.data.store import HoldoutLocked
    from src.research_lab.orderflow_ml.store import PAPER_FIRST_DAY

    early = PAPER_FIRST_DAY - timedelta(days=2)
    trades = synthetic_trades(early, 3)
    rec, api, _ = recorder_at(tmp_path, trades, ms(early, 3600))
    catch_up(rec)
    api.visible_until = ms(early + timedelta(days=2), 3600)
    catch_up(rec)
    store = _live_store(rec, ms(early + timedelta(days=2), 3600))
    assert rec.day_state(early) == "complete"
    with pytest.raises(HoldoutLocked):
        store.fetch(early)


def test_a_cached_recorder_day_that_gets_blocked_is_dropped(tmp_path):
    trades = synthetic_trades(DAY1, 2)
    rec, api, _ = recorder_at(tmp_path, trades, ms(DAY1, 3600))
    catch_up(rec)
    api.visible_until = ms(DAY1 + timedelta(days=1), 3600)
    catch_up(rec)
    store = _live_store(rec, ms(DAY1 + timedelta(days=1), 3600))
    store.fetch(DAY1)
    rec._block(DAY1)
    assert store.cached(DAY1) is None and DAY1 not in store._recorded


def test_only_one_recorder_per_folder(tmp_path):
    import fcntl

    trades = synthetic_trades(DAY1, 1)
    rec, api, _ = recorder_at(tmp_path, trades, ms(DAY1, 3600))
    rec.dir.mkdir(parents=True)
    held = (rec.dir / "record.lock").open("w")
    fcntl.flock(held, fcntl.LOCK_EX)
    with pytest.raises(ChainError):
        rec.run(stop_after=0)
