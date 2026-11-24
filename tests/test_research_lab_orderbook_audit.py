"""Read-only streaming audit of the order-book recording (Paket D, Recorder-Integrität). Synthetic archives only."""
from __future__ import annotations

import gzip
import io
import json
import os

import pytest

from src.research_lab.orderbook import audit
from src.research_lab.orderbook.__main__ import main

T0 = 1_794_873_600_000          # 2026-11-17T00:00:00Z
H = 3_600_000
STEP = 1000                     # one depth event per second keeps the files small; 1 s is still "covered"


def _depth(t: int, u: int) -> dict:
    return {"kind": "depth", "recv_ms": t, "msg": {"e": "depthUpdate", "E": t, "s": "BTCUSDT", "U": u, "u": u,
                                                     "pu": u - 1, "b": [], "a": []}}


def _rows(t0: int, t1: int, u0: int = 100, step: int = STEP) -> list[dict]:
    """Snapshot then a clean chain of depth events from t0 to t1 inclusive."""
    rows = [{"kind": "snapshot", "recv_ms": t0, "msg": {"lastUpdateId": u0, "bids": [], "asks": []}}]
    rows += [_depth(t, u0 + i) for i, t in enumerate(range(t0, t1 + 1, step))]
    return rows


def _write(root, session: int, rows: list[dict], *, closed: bool = True, mtime_ms: int | None = None) -> list:
    """Write rows like the recorder: one segment per UTC day; ``closed=False`` leaves the newest without gzip end."""
    by_day: dict[str, list[dict]] = {}
    for r in rows:
        t = r.get("recv_ms", r.get("to_ms"))
        by_day.setdefault(audit.iso(t)[:10], []).append(r)
    folder = root / "BTCUSDT"
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    days = sorted(by_day)
    for day in days:
        buf = io.BytesIO()
        g = gzip.GzipFile(fileobj=buf, mode="wb", mtime=0)
        for r in by_day[day]:
            g.write((json.dumps(r, separators=(",", ":")) + "\n").encode())
        if closed or day != days[-1]:
            g.close()
        else:
            g.flush()               # what a running recorder leaves on disk: data, no end-of-stream marker
        path = folder / f"{day}.{session}.jsonl.gz"
        path.write_bytes(buf.getvalue())
        if mtime_ms is not None:
            os.utime(path, (mtime_ms / 1000, mtime_ms / 1000))
        paths.append(path)
    return paths


def _snapshot_tree(root) -> dict:
    return {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in root.rglob("*")}


def test_clean_73h_run_passes_and_archive_is_untouched(tmp_path):
    _write(tmp_path, T0, _rows(T0, T0 + 73 * H), mtime_ms=T0 + 73 * H)
    before = _snapshot_tree(tmp_path)
    r = audit.audit(tmp_path, "BTCUSDT", now_ms=T0 + 80 * H)
    assert _snapshot_tree(tmp_path) == before
    assert r["acceptance"]["verdict"] == "PASS", r["acceptance"]["reasons"]
    assert r["time_coverage"]["coverage"] == 1.0 and r["time_coverage"]["pauses_count"] == 0
    assert r["completeness"]["breaks"] == 0 and r["completeness"]["resyncs"] == 0
    assert r["segments"]["status"] == {"ok": 4, "open": 0, "damaged": 0}
    assert r["period"]["start"] == {"iso": "2026-11-17T00:00:00.000Z", "ms": T0}
    assert r["period"]["source"]["end"] == "last depth event"
    assert r["acceptance"]["window"]["start"]["ms"] == T0


def test_pause_is_listed_and_fails_72h(tmp_path):
    # 40 h, then 90 s silence, then 40 h: no 72 h window without a pause > 60 s
    rows = _rows(T0, T0 + 40 * H)
    u = rows[-1]["msg"]["u"]
    rows += [_depth(t, u + 1 + i) for i, t in enumerate(range(T0 + 40 * H + 90_000, T0 + 80 * H, STEP))]
    _write(tmp_path, T0, rows)
    r = audit.audit(tmp_path, "BTCUSDT", now_ms=T0 + 90 * H)
    pauses = r["time_coverage"]["pauses"]
    assert len(pauses) == 1 and pauses[0]["seconds"] == 90.0 and not pauses[0]["outage"]
    assert pauses[0]["start"]["iso"] == "2026-11-18T16:00:00.000Z"
    assert r["acceptance"]["verdict"] == "FAIL"
    assert r["acceptance"]["incident_kinds"] == {"pause": 1}
    assert r["acceptance"]["longest_clean_stretch"]["hours"] < 72
    assert r["completeness"]["breaks"] == 0        # time coverage and event completeness stay separate


def test_update_id_break_is_counted_and_ends_the_window(tmp_path):
    rows = _rows(T0, T0 + 2 * H)
    rows[100]["msg"]["pu"] = 1                     # chain miss in the middle
    rows.append({"kind": "snapshot", "recv_ms": T0 + 2 * H + 500,
                 "msg": {"lastUpdateId": rows[-1]["msg"]["u"] + 1}})
    rows += [_depth(T0 + 2 * H + 1000 + i * STEP, rows[-2]["msg"]["u"] + 1 + i) for i in range(10)]
    _write(tmp_path, T0, rows)
    r = audit.audit(tmp_path, "BTCUSDT", window_hours=1, now_ms=T0 + 5 * H)
    c = r["completeness"]
    assert c["breaks"] == 1 and c["pu_mismatch"] == 1 and c["resyncs"] == 1
    assert c["breaks_list"][0]["at"]["ms"] == rows[100]["recv_ms"]
    assert r["acceptance"]["incident_kinds"] == {"sequence_break": 1, "unsynced": 1}  # no book until the resync


def test_gap_row_resets_chain_without_break(tmp_path):
    rows = _rows(T0, T0 + H)
    rows.append({"kind": "gap", "from_ms": T0 + H, "to_ms": T0 + H + 20_000})
    rows += _rows(T0 + H + 20_000, T0 + 2 * H, u0=10**6)
    _write(tmp_path, T0, rows)
    r = audit.audit(tmp_path, "BTCUSDT", now_ms=T0 + 5 * H)
    assert r["completeness"]["breaks"] == 0 and r["completeness"]["resyncs"] == 1
    assert r["events"]["gap"] == 1 and r["time_coverage"]["pauses"][0]["gap_row"] is True


def test_truncated_older_segment_is_damaged_and_open_newest_is_open(tmp_path):
    now = T0 + 10 * H
    old = _write(tmp_path, T0, _rows(T0, T0 + H), closed=False, mtime_ms=T0 + H)            # killed run
    _write(tmp_path, T0 + 2 * H, _rows(T0 + 2 * H, T0 + 10 * H - 5000, u0=10**6), closed=False, mtime_ms=now - 5000)
    r = audit.audit(tmp_path, "BTCUSDT", now_ms=now)
    segs = {s["name"]: s for s in r["segments"]["list"]}
    assert segs[old[0].name]["status"] == "damaged" and segs[old[0].name]["reasons"] == ["truncated"]
    newest = segs[f"2026-11-17.{T0 + 2 * H}.jsonl.gz"]
    assert newest["status"] == "open" and newest["reasons"] == []
    assert r["segments"]["status"] == {"ok": 0, "open": 1, "damaged": 1}
    assert r["time_coverage"]["pauses"][0]["restart"] is True
    assert r["acceptance"]["incident_kinds"] == {"damaged_segment": 1, "pause": 1}
    # same newest file, but the recorder stopped writing long ago: no longer open
    r2 = audit.audit(tmp_path, "BTCUSDT", now_ms=now + H)
    assert r2["segments"]["status"]["damaged"] == 2


def test_unparsable_line_and_overlap_are_flagged(tmp_path):
    p = _write(tmp_path, T0, _rows(T0, T0 + 600_000))[0]
    with gzip.open(p, "ab") as fh:
        fh.write(b"{not json\n")
    _write(tmp_path, T0 + 1, _rows(T0 + 300_000, T0 + 900_000, u0=10**6))   # second recorder overlapping
    r = audit.audit(tmp_path, "BTCUSDT", now_ms=T0 + 5 * H)
    first = r["segments"]["list"][0]
    assert first["unparsable_lines"] == 1 and first["status"] == "damaged"
    assert len(r["segments"]["overlaps"]) == 1 and r["segments"]["overlaps"][0]["overlap_seconds"] == 300.0


def test_explicit_period_counts_edges_and_outage(tmp_path):
    _write(tmp_path, T0, _rows(T0 + H, T0 + 2 * H))
    r = audit.audit(tmp_path, "BTCUSDT", start_ms=T0, end_ms=T0 + 3 * H, now_ms=T0 + 5 * H)
    tc = r["time_coverage"]
    assert tc["denominator_seconds"] == 3 * 3600 and abs(tc["coverage"] - 1 / 3) < 1e-6
    assert [p["period_edge"] for p in tc["pauses"]] == [True, True] and tc["outages_count"] == 2
    assert r["period"]["source"] == {"start": "--start", "end": "--end"}


def test_cli_audit_refuses_out_inside_archive_and_writes_outside(tmp_path, capsys):
    arch = tmp_path / "arch"
    _write(arch, T0, _rows(T0, T0 + 60_000))
    assert main(["audit", "--root", str(arch), "--out", str(arch / "r.json")]) == 2
    assert not (arch / "r.json").exists()
    capsys.readouterr()
    out = tmp_path / "report.json"
    assert main(["audit", "--root", str(arch), "--start", "2026-11-17T00:00:00", "--out", str(out)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed == json.loads(out.read_text()) and printed["period"]["start"]["ms"] == T0
    assert printed["acceptance"]["verdict"] == "FAIL"      # one minute is not 72 h


def test_events_without_any_snapshot_fail_72h(tmp_path):
    """Codex #379: 72 h of well-formed depth events but no snapshot is no valid book and must not PASS."""
    rows = [_depth(t, 100 + i) for i, t in enumerate(range(T0, T0 + 72 * H + 1, STEP))]
    _write(tmp_path, T0, rows)
    r = audit.audit(tmp_path, "BTCUSDT", start_ms=T0, end_ms=T0 + 72 * H, now_ms=T0 + 80 * H)
    assert r["time_coverage"]["coverage"] == 1.0                      # events everywhere ...
    assert r["completeness"]["synced_share"] == 0.0 and r["book_coverage"]["coverage"] == 0.0  # ... but no book
    acc = r["acceptance"]
    assert acc["verdict"] == "FAIL" and acc["incident_kinds"] == {"unsynced": 1}
    assert "no depth event applied to a synchronised book" in acc["reasons"]
    assert acc["p3_valid_seconds"]["verdict"] == "FAIL"


def test_mostly_unsynced_fails_and_short_resync_after_restart_does_not(tmp_path):
    rows = [_depth(T0 + i * STEP, 50 + i) for i in range(600)]       # 10 min before the first snapshot
    rows += _rows(T0 + 600 * STEP, T0 + 73 * H, u0=1000)
    _write(tmp_path, T0, rows)
    r = audit.audit(tmp_path, "BTCUSDT", now_ms=T0 + 80 * H)
    assert r["acceptance"]["incident_kinds"] == {"unsynced": 1}
    assert r["acceptance"]["verdict"] == "PASS"                       # the clean 72 h after the sync still count
    assert r["acceptance"]["window"]["start"]["ms"] >= T0 + 600 * STEP
    tmp2 = tmp_path / "b"
    _write(tmp2, T0, [_depth(T0 + i * STEP, 50 + i) for i in range(5)] + _rows(T0 + 5 * STEP, T0 + 73 * H, u0=1000))
    r2 = audit.audit(tmp2, "BTCUSDT", now_ms=T0 + 80 * H)
    assert r2["acceptance"]["incident_kinds"] == {} and r2["acceptance"]["verdict"] == "PASS"
    assert r2["book_coverage"]["unsynced_seconds"] == 5.0


def test_current_window_includes_the_running_outage_and_is_labelled(tmp_path):
    _write(tmp_path, T0, _rows(T0, T0 + 73 * H))                      # clean, then silence until now
    hist = audit.audit(tmp_path, "BTCUSDT", now_ms=T0 + 80 * H)
    assert hist["period"]["scope"] == "historical" and hist["acceptance"]["verdict"] == "PASS"
    assert hist["acceptance"]["scope"] == "historical" and hist["period"]["seconds_since_last_event"] == 7 * 3600
    cur = audit.audit(tmp_path, "BTCUSDT", now_ms=T0 + 80 * H, current=True)
    assert cur["period"]["scope"] == "current" and cur["period"]["end"]["ms"] == T0 + 80 * H
    assert cur["period"]["start"]["ms"] == T0 + 8 * H and cur["acceptance"]["verdict"] == "FAIL"
    assert cur["acceptance"]["window"] is None
    ok = audit.audit(tmp_path, "BTCUSDT", now_ms=T0 + 73 * H, current=True)
    assert ok["acceptance"]["verdict"] == "PASS" and ok["acceptance"]["window"]["start"]["ms"] == T0 + H
    with pytest.raises(ValueError):
        audit.audit(tmp_path, "BTCUSDT", start_ms=T0, current=True)


def test_period_edges_unrecognized_files_and_cli_current(tmp_path, capsys):
    _write(tmp_path, T0, _rows(T0 + 30_000, T0 + 2 * H))
    (tmp_path / "BTCUSDT" / "notes.txt").write_text("x")
    r = audit.audit(tmp_path, "BTCUSDT", start_ms=T0, end_ms=T0 + 2 * H + 30_000, window_hours=1, now_ms=T0 + 5 * H)
    assert r["period"]["scope"] == "explicit" and r["segments"]["unrecognized_files"] == ["notes.txt"]
    edges = [p for p in r["time_coverage"]["pauses"] if p.get("period_edge")]
    assert [p["seconds"] for p in edges] == [30.0, 30.0]
    assert main(["audit", "--root", str(tmp_path), "--current", "--start", "2026-11-17T00:00:00"]) == 2
    assert "refused" in capsys.readouterr().out


def _write_one(root, session: int, name_day: str, rows: list[dict], *, bad_at: int | None = None, cut: bool = False) -> None:
    """One segment file; ``bad_at`` inserts an unparsable line after that many rows, ``cut`` drops the gzip end."""
    buf = io.BytesIO()
    g = gzip.GzipFile(fileobj=buf, mode="wb", mtime=0)
    for i, r in enumerate(rows):
        if bad_at is not None and i == bad_at:
            g.write(b"NOT JSON\n")
        g.write((json.dumps(r, separators=(",", ":")) + "\n").encode())
    g.flush() if cut else g.close()
    folder = root / "BTCUSDT"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name_day}.{session}.jsonl.gz"
    path.write_bytes(buf.getvalue()[:-4] if cut else buf.getvalue())
    os.utime(path, (T0 / 1000, T0 / 1000))          # old mtime: never "open"


# Codex Mission 06/07: damage in a segment that runs past the window end must not give PASS.
def test_damage_in_a_segment_spanning_the_window_end_fails_closed(tmp_path):
    end = T0 + 72 * H
    rows = _rows(T0, end + 49_000)
    bad = next(i for i, r in enumerate(rows) if r.get("recv_ms", 0) >= end - 40_000)
    _write_one(tmp_path, T0, "2026-11-17", rows, bad_at=bad)
    r = audit.audit(tmp_path, "BTCUSDT", start_ms=T0, end_ms=end, now_ms=end + 10 * H)
    assert r["segments"]["status"]["damaged"] == 1
    assert r["acceptance"]["incident_kinds"].get("damaged_segment") == 1 and r["acceptance"]["verdict"] == "FAIL"


@pytest.mark.parametrize("where", ["before", "inside", "after"])
def test_damage_before_inside_after_the_window(tmp_path, where):
    """Three segments (sessions) around a 72 h window; only damage in a segment touching the window fails it."""
    start, end = T0 + 2 * H, T0 + 74 * H
    parts = {"before": (T0, T0 + H), "inside": (start, end), "after": (end + H, end + 2 * H)}
    for key, (a, b) in parts.items():
        rows = _rows(a, b, u0=100 + a // 1000)
        _write_one(tmp_path, a, audit.iso(a)[:10], rows, bad_at=5 if key == where else None)
    r = audit.audit(tmp_path, "BTCUSDT", start_ms=start, end_ms=end, now_ms=end + 10 * H)
    kinds = r["acceptance"]["incident_kinds"]
    if where == "inside":
        assert kinds.get("damaged_segment") == 1 and r["acceptance"]["verdict"] == "FAIL"
    else:
        assert "damaged_segment" not in kinds, where


def test_truncated_gzip_marks_the_loss_up_to_the_next_segment(tmp_path):
    """A cut stream loses whatever came after its last readable row: up to the next segment's first event."""
    start, end = T0, T0 + 72 * H
    first = _rows(T0, T0 + 10 * H)
    _write_one(tmp_path, T0, "2026-11-17", first, cut=True)
    second_start = T0 + 10 * H + 30_000
    _write_one(tmp_path, second_start, "2026-11-17", _rows(second_start, end + H, u0=10_000_000))
    r = audit.audit(tmp_path, "BTCUSDT", start_ms=start, end_ms=end, now_ms=end + 10 * H)
    assert r["segments"]["status"]["damaged"] == 1 and r["acceptance"]["verdict"] == "FAIL"
    assert r["acceptance"]["incident_kinds"].get("damaged_segment") == 1


def test_damaged_segment_without_any_readable_row_counts_from_its_session(tmp_path):
    start, end = T0, T0 + 72 * H
    _write_one(tmp_path, T0, "2026-11-17", _rows(T0, end + H))
    folder = tmp_path / "BTCUSDT"
    broken = folder / f"2026-11-18.{T0 + 30 * H}.jsonl.gz"
    broken.write_bytes(b"\x1f\x8b not really gzip")
    os.utime(broken, (T0 / 1000, T0 / 1000))
    r = audit.audit(tmp_path, "BTCUSDT", start_ms=start, end_ms=end, now_ms=end + 10 * H)
    assert r["acceptance"]["incident_kinds"].get("damaged_segment") == 1 and r["acceptance"]["verdict"] == "FAIL"
