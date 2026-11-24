"""Read-only streaming audit of the order-book recording (Paket D, Recorder-Integrität). Synthetic archives only."""
from __future__ import annotations

import gzip
import io
import json
import os

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
    assert r["acceptance"]["incident_kinds"] == {"sequence_break": 1}


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
