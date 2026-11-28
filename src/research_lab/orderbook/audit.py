"""Read-only, streaming integrity audit of the Binance order-book recording (:mod:`.binance`).

``check`` in :mod:`.book` loads whole days into memory; this reads every segment line by line and keeps only
counters, the last update id and the list of irregular intervals. It never writes into the archive.

Two separate questions:

* **Time coverage**: how much of the period has depth events. Every interval between consecutive depth events
  (``recv_ms``) longer than :data:`COVERAGE_GAP_MS` counts as uncovered, whole. Intervals longer than
  ``--pause-seconds`` are listed as pauses, those of at least :data:`OUTAGE_SECONDS` also as outages.
* **Event completeness**: the depth update-id chain (Binance USD-M rule, same as :class:`.book.Book`): after a
  snapshot the first applied event has ``U <= lastUpdateId <= u``, every later one ``pu`` = previous ``u``. A
  miss is a *sequence break*. ``gap`` rows and session starts reset the chain (explained, not a break); a sync
  after a break or gap row is a *resync*.

Segments (``<YYYY-MM-DD>.<session_ms>.jsonl.gz``) are read in order (session id, day). A segment is ``ok``,
``damaged`` (no clean gzip end, bad gzip, half-written or unparsable lines, empty) or ``open``: the newest
segment of the newest session, without clean end and modified less than ``open_grace_seconds`` ago, is the file
the recorder is still writing. A newest segment older than that is ``damaged`` (recorder killed).

* **Book validity**: depth events that arrive while no book is synchronised (before the first snapshot, after
  a break, a gap row or a restart, until the next sync) are *unsynced*. Their stretch counts as uncovered for the
  book coverage, and a stretch longer than :data:`ACCEPT_MAX_PAUSE_SECONDS` ends a clean window. Events without
  a valid book are no proof of integrity: an archive with events but no snapshot fails.

Acceptance "72 h continuous" uses the fixed constants below (set before looking at data, not to be tuned):
a window of ``window_hours`` inside the period that contains no pause > :data:`ACCEPT_MAX_PAUSE_SECONDS`, no
unsynced stretch above that, no sequence break, no damaged segment, no unparsable line and no segment overlap,
and whose book coverage (time with events *and* a synchronised book) is at least :data:`ACCEPT_MIN_COVERAGE`.
The Bauplan P3 criterion (:data:`P3_MIN_VALID_SHARE` valid seconds) is a different gate and reported apart.

Which window is meant is always stated in ``period.scope``: ``current`` (the last ``window_hours`` up to now,
``--current``; the window is the whole period), ``explicit`` (``--start/--end``) or ``historical`` (first to last
event; the best window found is a *historical* window, not the state of the running recorder, and the silence
after the last event is outside the period). All times are UTC (ISO 8601 plus epoch ms); naive
``--start/--end`` are read as UTC.
"""
from __future__ import annotations

import bisect
import gzip
import json
import re
import time
import zlib
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

# -- acceptance thresholds (pre-registered, see docs/research_lab/ORDERBUCH_RECORDER_BAUPLAN.md) ----------------
ACCEPT_WINDOW_HOURS = 72
ACCEPT_MIN_COVERAGE = 0.999          # at most 259 s uncovered in 72 h
ACCEPT_MAX_PAUSE_SECONDS = 60        # any single pause above this ends a continuous window
ACCEPT_MAX_BREAKS = 0                # unexplained sequence breaks allowed in the window
ACCEPT_MAX_DAMAGED = 0               # damaged segments / unparsable lines / overlaps allowed in the window
P3_MIN_VALID_SHARE = 0.995          # Bauplan P3 "99,5 % gültige Sekunden", a separate, weaker gate
COVERAGE_GAP_MS = 1000               # depth@100ms: an event interval above 1 s counts as uncovered
OUTAGE_SECONDS = 600                 # pauses of at least 10 min are also listed as outages
DEFAULT_PAUSE_SECONDS = 10
DEFAULT_OPEN_GRACE_SECONDS = 120     # recorder flushes every 5 s; older unfinished newest segment = damaged
LIST_CAP = 1000                      # listed pauses/breaks/incidents per kind; counts stay exact

SEGMENT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.(\d+)\.jsonl\.gz$")


def iso(ms: int | None) -> str | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def stamp(ms: int | None) -> dict:
    return {"iso": iso(ms), "ms": ms}


def parse_time(text: str | None) -> int | None:
    """ISO 8601 to epoch ms; without offset the time is taken as UTC (never local time)."""
    if text is None:
        return None
    dt = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _iter_rows(path: Path, seg: dict) -> Iterator[dict]:
    """Rows of one segment, one line at a time; damage is recorded in ``seg``, never raised."""
    try:
        with gzip.open(path, "rb") as fh:
            for line in fh:
                if not line.endswith(b"\n"):
                    seg["partial_tail"] = True
                    break
                try:
                    row = json.loads(line)
                except ValueError:
                    seg["unparsable_lines"] += 1
                    continue
                if not isinstance(row, dict):
                    seg["unparsable_lines"] += 1
                    continue
                yield row
    except EOFError:
        seg["error"] = "truncated"          # no gzip end-of-stream: hard kill, power loss or still being written
    except gzip.BadGzipFile:
        seg["error"] = "bad_gzip"
    except zlib.error:
        seg["error"] = "corrupt"
    except OSError as exc:
        seg["error"] = f"os_error: {type(exc).__name__}"


class _Audit:
    def __init__(self, start_ms: int | None, end_ms: int | None, pause_ms: int) -> None:
        self.start_ms, self.end_ms, self.pause_ms = start_ms, end_ms, pause_ms
        self.first_ms: int | None = None
        self.last_ms: int | None = None       # latest depth time seen in range
        self.rows = {"depth": 0, "snapshot": 0, "gap": 0, "other": 0}
        self.gap_row_ms = 0
        self.gaps: list[tuple[int, int]] = []         # uncovered intervals (> COVERAGE_GAP_MS)
        self.pauses: list[dict] = []
        self.n_pauses = 0
        self.incidents: list[tuple[int, int, str]] = []
        self.chain = {"applied": 0, "old": 0, "nobook": 0, "breaks": 0, "pu_mismatch": 0, "sync_miss": 0,
                      "resyncs": 0, "session_resets": 0, "gap_resets": 0, "malformed": 0}
        self.breaks: list[dict] = []
        self.unsynced: list[tuple[int, int]] = []     # stretches of depth events without a synchronised book
        self._unsynced_from: int | None = None
        self.time_regressions = 0
        self._hint = {"gap_row": False, "restart": False, "after_damaged_segment": False}
        self._reset_chain(loss=False)

    # -- chain -------------------------------------------------------------------------------------------
    def _reset_chain(self, loss: bool) -> None:
        self.state, self.last_u, self.after_loss = "nobook", None, loss

    def new_session(self) -> None:
        self._reset_chain(loss=False)
        self.chain["session_resets"] += 1
        self._hint["restart"] = True

    def in_range(self, t: int | None) -> bool:
        return t is not None and (self.start_ms is None or t >= self.start_ms) and (self.end_ms is None or t <= self.end_ms)

    def row(self, row: dict, seg: dict) -> None:
        kind = row.get("kind")
        t = row.get("recv_ms") if kind != "gap" else row.get("to_ms")
        if not isinstance(t, int):
            seg["unparsable_lines"] += 1
            self.chain["malformed"] += 1
            return
        seg["first_ms"] = t if seg["first_ms"] is None else seg["first_ms"]
        if seg["last_ms"] is not None and t < seg["last_ms"]:
            seg["time_regressions"] += 1
        seg["last_ms"] = t if seg["last_ms"] is None else max(seg["last_ms"], t)
        counted = self.in_range(t)
        if kind == "gap":
            self._reset_chain(loss=True)
            self.chain["gap_resets"] += 1
            self._hint["gap_row"] = True
            if counted:
                self.rows["gap"] += 1
                f = row.get("from_ms")
                self.gap_row_ms += max(0, t - f) if isinstance(f, int) else 0
        elif kind == "snapshot":
            msg = row.get("msg")
            if not isinstance(msg, dict) or "lastUpdateId" not in msg:
                seg["unparsable_lines"] += 1
                self.chain["malformed"] += 1
                return
            if self.state != "synced":
                self.state, self.last_u = "pending", int(msg["lastUpdateId"])
            if counted:
                self.rows["snapshot"] += 1
        elif kind == "depth":
            msg = row.get("msg")
            try:
                u, first, prev = int(msg["u"]), int(msg["U"]), msg.get("pu")
            except (TypeError, KeyError, ValueError):
                seg["unparsable_lines"] += 1
                self.chain["malformed"] += 1
                return
            res = self._depth(u, first, prev)
            if counted:
                self.rows["depth"] += 1
                self._time(t)
                self._validity(t, res == "applied")
                if res in ("pu_mismatch", "sync_miss"):
                    self.chain["breaks"] += 1
                    self.chain[res] += 1
                    if len(self.breaks) < LIST_CAP:
                        self.breaks.append({"at": stamp(t), "kind": res, "segment": seg["name"], "U": first, "u": u, "pu": prev})
                    self.incidents.append((t, t, "sequence_break"))
                else:
                    self.chain[res] += 1
        elif counted:
            self.rows["other"] += 1

    def _depth(self, u: int, first: int, prev) -> str:
        if self.state == "nobook":
            return "nobook"
        if self.state == "pending":
            if u < self.last_u:
                return "old"
            if not first <= self.last_u <= u:
                self._reset_chain(loss=True)
                return "sync_miss"
            self.state = "synced"
            if self.after_loss:
                self.chain["resyncs"] += 1
                self.after_loss = False
        elif prev is None or int(prev) != self.last_u:
            self._reset_chain(loss=True)
            return "pu_mismatch"
        self.last_u = u
        return "applied"

    def _validity(self, t: int, synced: bool) -> None:
        if not synced:
            if self._unsynced_from is None:
                self._unsynced_from = t
            return
        if self._unsynced_from is not None:
            self._close_unsynced(t)

    def _close_unsynced(self, t: int) -> None:
        a, self._unsynced_from = self._unsynced_from, None
        if a is None or t <= a:
            if a is not None:
                self.unsynced.append((a, a))
            return
        self.unsynced.append((a, t))
        if t - a > ACCEPT_MAX_PAUSE_SECONDS * 1000:
            self.incidents.append((a, t, "unsynced"))

    # -- time ----------------------------------------------------------------------------------------------
    def _interval(self, a: int, b: int, edge: bool = False) -> None:
        d = b - a
        if d > COVERAGE_GAP_MS:
            self.gaps.append((a, b))
        if d > ACCEPT_MAX_PAUSE_SECONDS * 1000:
            self.incidents.append((a, b, "pause"))
        if d > self.pause_ms:
            self.n_pauses += 1
            if len(self.pauses) < LIST_CAP:
                p = {"start": stamp(a), "end": stamp(b), "seconds": round(d / 1000, 3),
                     "outage": d >= OUTAGE_SECONDS * 1000}
                p.update({k: v for k, v in self._hint.items() if v})
                if edge:
                    p["period_edge"] = True
                self.pauses.append(p)

    def _time(self, t: int) -> None:
        if self.last_ms is None:
            self.first_ms = t
            if self.start_ms is not None and t > self.start_ms:
                self._interval(self.start_ms, t, edge=True)
            self.last_ms = t
        elif t > self.last_ms:
            self._interval(self.last_ms, t)
            self.last_ms = t
        elif t < self.last_ms:
            self.time_regressions += 1
        self._hint = {k: False for k in self._hint}

    def damaged(self) -> None:
        self._hint["after_damaged_segment"] = True

    def finish(self) -> None:
        if self._unsynced_from is not None:
            self._close_unsynced(max(self.last_ms or self._unsynced_from, self.end_ms or 0))
        if self.end_ms is not None and self.last_ms is not None and self.end_ms > self.last_ms:
            self._interval(self.last_ms, self.end_ms, edge=True)


def _uncovered(gaps: list[tuple[int, int]], starts: list[int], a: int, b: int) -> int:
    """Sum of the parts of ``gaps`` (sorted, non-overlapping) that lie in [a, b]."""
    total = 0
    i = max(0, bisect.bisect_right(starts, a) - 1)
    while i < len(gaps) and gaps[i][0] < b:
        lo, hi = max(gaps[i][0], a), min(gaps[i][1], b)
        if hi > lo:
            total += hi - lo
        i += 1
    return total


def _merge(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for a, b in sorted(i for i in intervals if i[1] > i[0]):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _acceptance(au: _Audit, p0: int, p1: int, window_ms: int, scope: str) -> dict:
    # clean stretches: the period minus every incident (pause > limit as interval, other incidents as points)
    stretches: list[tuple[int, int]] = []
    cursor = p0
    for a, b, _ in sorted(au.incidents):
        if a > cursor:
            stretches.append((cursor, min(a, p1)))
        cursor = max(cursor, b)
        if cursor >= p1:
            break
    if cursor < p1:
        stretches.append((cursor, p1))
    gaps = _merge(au.gaps + au.unsynced)          # uncovered = no events or no synchronised book
    starts = [g[0] for g in gaps]
    longest = max(stretches, key=lambda s: (s[1] - s[0], -s[0]), default=None)
    best = None
    for s0, s1 in stretches:
        if s1 - s0 < window_ms:
            continue
        if scope == "current" and (s0, s1) != (p0, p1):
            continue                               # the current window is the whole period, nothing to pick
        lo = bisect.bisect_left(starts, s0)
        candidates = [s0] + [g[1] for g in gaps[lo:] if g[1] <= s1 - window_ms]
        for c in candidates:
            unc = _uncovered(gaps, starts, c, c + window_ms)
            if best is None or unc < best[1]:
                best = (c, unc)
    out = {
        "thresholds": {"window_hours": window_ms / 3_600_000, "standard_window_hours": ACCEPT_WINDOW_HOURS,
                       "min_coverage": ACCEPT_MIN_COVERAGE, "max_pause_seconds": ACCEPT_MAX_PAUSE_SECONDS,
                       "max_sequence_breaks": ACCEPT_MAX_BREAKS, "max_damaged": ACCEPT_MAX_DAMAGED,
                       "coverage_gap_ms": COVERAGE_GAP_MS, "coverage_counts": "events and synchronised book"},
        "scope": scope,
        "scope_note": {"current": "the last window up to now (state of the running recorder)",
                       "explicit": "best window inside the given --start/--end",
                       "historical": "best historical window between first and last event; not the current state"}[scope],
        "incidents": len(au.incidents),
        "incident_kinds": {k: sum(1 for i in au.incidents if i[2] == k) for k in sorted({i[2] for i in au.incidents})},
        "longest_clean_stretch": None, "window": None, "reasons": [],
    }
    if longest is not None:
        ln = longest[1] - longest[0]
        out["longest_clean_stretch"] = {"start": stamp(longest[0]), "end": stamp(longest[1]),
                                        "hours": round(ln / 3_600_000, 3),
                                        "coverage": round(1 - _uncovered(gaps, starts, *longest) / ln, 6) if ln else None}
    if best is None:
        hours = out["longest_clean_stretch"]["hours"] if longest else 0
        out["reasons"].append(f"no clean stretch of {window_ms / 3_600_000:g} h (longest {hours} h)")
    else:
        cov = 1 - best[1] / window_ms
        out["window"] = {"start": stamp(best[0]), "end": stamp(best[0] + window_ms),
                         "coverage": round(cov, 6), "uncovered_seconds": round(best[1] / 1000, 3)}
        if cov < ACCEPT_MIN_COVERAGE:
            out["reasons"].append(f"best window coverage {cov:.6f} < {ACCEPT_MIN_COVERAGE}")
    if not au.chain["applied"]:
        out["reasons"].append("no depth event applied to a synchronised book")
    if window_ms != ACCEPT_WINDOW_HOURS * 3_600_000:
        out["reasons"].append(f"window {window_ms / 3_600_000:g} h is not the standard {ACCEPT_WINDOW_HOURS} h")
    out["verdict"] = "PASS" if not out["reasons"] else "FAIL"
    # Bauplan P3 is a separate gate: share of valid seconds in the accepted window (else the whole period)
    w0, w1 = (best[0], best[0] + window_ms) if best is not None else (p0, p1)
    valid = 1 - _uncovered(gaps, starts, w0, w1) / (w1 - w0)
    out["p3_valid_seconds"] = {"min_share": P3_MIN_VALID_SHARE, "share": round(valid, 6),
                               "measured_on": "acceptance window" if best is not None else "whole period",
                               "verdict": "PASS" if best is not None and valid >= P3_MIN_VALID_SHARE else "FAIL",
                               "note": "different gate from the 72 h acceptance; reported apart, never merged"}
    return out


def audit(root: Path, symbol: str, *, start_ms: int | None = None, end_ms: int | None = None,
          window_hours: float = ACCEPT_WINDOW_HOURS, pause_seconds: float = DEFAULT_PAUSE_SECONDS,
          open_grace_seconds: float = DEFAULT_OPEN_GRACE_SECONDS, now_ms: int | None = None,
          current: bool = False) -> dict:
    """Audit ``root/symbol`` without writing anything. Returns the JSON-serialisable report.

    ``current=True`` audits exactly the last ``window_hours`` up to ``now_ms`` (no --start/--end allowed)."""
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    if current:
        if start_ms is not None or end_ms is not None:
            raise ValueError("current=True takes no start/end")
        end_ms = now_ms
        start_ms = now_ms - int(window_hours * 3_600_000)
        scope = "current"
    else:
        scope = "explicit" if start_ms is not None or end_ms is not None else "historical"
    folder = root / symbol
    segs, unknown = [], []
    for path in sorted(folder.glob("*")) if folder.is_dir() else []:
        m = SEGMENT_RE.match(path.name)
        if not m:
            if path.is_file():
                unknown.append(path.name)
            continue
        segs.append((int(m.group(2)), m.group(1), path))
    segs.sort()
    newest = segs[-1][2] if segs else None
    day0 = iso(start_ms)[:10] if start_ms is not None else None
    day1 = iso(end_ms)[:10] if end_ms is not None else None
    au = _Audit(start_ms, end_ms, int(pause_seconds * 1000))
    seg_out, overlaps = [], []
    prev_session, prev_last, prev_name = None, None, None
    pending_damage: list[list] = []   # [start, end, end still open until the next segment's first event]
    for session, day, path in segs:
        if (day0 and day < day0) or (day1 and day > day1):
            continue
        st = path.stat()
        seg = {"name": path.name, "session_ms": session, "day": day, "bytes": st.st_size,
               "mtime": stamp(int(st.st_mtime * 1000)), "rows": 0, "unparsable_lines": 0, "partial_tail": False,
               "error": None, "first_ms": None, "last_ms": None, "time_regressions": 0}
        if session != prev_session:
            au.new_session()
        for row in _iter_rows(path, seg):
            seg["rows"] += 1
            au.row(row, seg)
        clean = seg["error"] is None and not seg["partial_tail"]
        fresh = now_ms - st.st_mtime * 1000 <= open_grace_seconds * 1000
        reasons = []
        if not clean:
            reasons.append(seg["error"] or "partial_tail")
        if seg["unparsable_lines"]:
            reasons.append("unparsable_lines")
        if seg["rows"] == 0 and clean:
            reasons.append("empty")
        if path == newest and not clean and fresh:
            seg["status"] = "open"
            reasons = [r for r in reasons if r not in ("truncated", "partial_tail")]
        else:
            seg["status"] = "damaged" if reasons else "ok"
        seg["reasons"] = reasons
        if seg["first_ms"] is not None:            # the first event after a cut stream ends its unknown stretch
            for item in pending_damage:
                if item[2]:
                    item[1], item[2] = max(item[1], seg["first_ms"]), False
        if reasons:
            # Fail closed (Mission 07, Codex #372): where in the segment the damage lies is unknown, so the whole span
            # it may touch is an incident: from its first readable event (else the session start) to its last one,
            # and for a cut or broken stream on to the next segment's first event (what came after is lost).
            lo = seg["first_ms"] if seg["first_ms"] is not None else session
            hi = seg["last_ms"] if seg["last_ms"] is not None else lo
            pending_damage.append([lo, hi, not clean or seg["rows"] == 0])
            au.damaged()
        if seg["first_ms"] is not None and prev_last is not None and seg["first_ms"] < prev_last:
            overlaps.append({"segment": path.name, "previous": prev_name, "first": stamp(seg["first_ms"]),
                             "previous_last": stamp(prev_last), "overlap_seconds": round((prev_last - seg["first_ms"]) / 1000, 3)})
            if au.in_range(seg["first_ms"]):
                au.incidents.append((seg["first_ms"], seg["first_ms"], "segment_overlap"))
        if seg["last_ms"] is not None:
            prev_last = seg["last_ms"] if prev_last is None else max(prev_last, seg["last_ms"])
            prev_name = path.name
        prev_session = session
        seg["first"], seg["last"] = stamp(seg.pop("first_ms")), stamp(seg.pop("last_ms"))
        seg_out.append(seg)
    au.finish()

    p0 = start_ms if start_ms is not None else au.first_ms
    p1 = end_ms if end_ms is not None else au.last_ms
    for lo, hi, still_open in pending_damage:
        if still_open:                             # nothing readable came after it: the loss runs to the period end
            hi = max(hi, p1 if p1 is not None else hi, au.last_ms or hi)
        if (end_ms is None or lo <= end_ms) and (start_ms is None or hi >= start_ms):   # touches the period
            au.incidents.append((lo, max(lo, hi), "damaged_segment"))
    report: dict = {
        "audit": "orderbook-recorder-integrity", "read_only": True, "symbol": symbol,
        "generated": stamp(now_ms),
        "period": {"scope": scope, "start": stamp(p0), "end": stamp(p1),
                   "source": {"start": "--start" if start_ms is not None else "first depth event",
                              "end": "--end" if end_ms is not None else "last depth event"},
                   "hours": round((p1 - p0) / 3_600_000, 3) if p0 is not None and p1 is not None else None,
                   # without --end the silence after the last event is outside the period; shown here instead
                   "seconds_since_last_event": round((now_ms - au.last_ms) / 1000, 3) if au.last_ms is not None else None},
        "segments": {"count": len(seg_out),
                     "status": {s: sum(1 for x in seg_out if x["status"] == s) for s in ("ok", "open", "damaged")},
                     "sessions": len({x["session_ms"] for x in seg_out}), "bytes": sum(x["bytes"] for x in seg_out),
                     "overlaps": overlaps, "unrecognized_files": unknown, "list": seg_out},
        "events": dict(au.rows, gap_row_seconds=round(au.gap_row_ms / 1000, 3),
                       time_regressions=au.time_regressions),
    }
    if p0 is None or p1 is None or p1 <= p0:
        report["time_coverage"] = None
        report["acceptance"] = {"verdict": "FAIL", "scope": scope, "reasons": ["no depth events in the period"]}
        report["completeness"] = dict(au.chain, breaks_list=au.breaks)
        return report
    gaps = sorted(au.gaps)
    uncovered = _uncovered(gaps, [g[0] for g in gaps], p0, p1)
    outages = [p for p in au.pauses if p["outage"]]
    report["time_coverage"] = {
        "coverage": round(1 - uncovered / (p1 - p0), 6), "uncovered_seconds": round(uncovered / 1000, 3),
        "denominator_seconds": round((p1 - p0) / 1000, 3), "pause_threshold_seconds": pause_seconds,
        "pauses_count": au.n_pauses, "pauses_listed": len(au.pauses), "pauses": au.pauses,
        "outages_count": len(outages), "longest_pause_seconds": max((p["seconds"] for p in au.pauses), default=0.0),
    }
    depth = au.rows["depth"]
    book_gaps = _merge(au.gaps + au.unsynced)
    unsynced = _uncovered(_merge(au.unsynced), [g[0] for g in _merge(au.unsynced)], p0, p1)
    book_uncovered = _uncovered(book_gaps, [g[0] for g in book_gaps], p0, p1)
    report["book_coverage"] = {"coverage": round(1 - book_uncovered / (p1 - p0), 6),
                               "uncovered_seconds": round(book_uncovered / 1000, 3),
                               "unsynced_seconds": round(unsynced / 1000, 3), "unsynced_stretches": len(au.unsynced)}
    report["completeness"] = dict(au.chain, synced_share=round(au.chain["applied"] / depth, 6) if depth else 0.0,
                                  breaks_listed=len(au.breaks), breaks_list=au.breaks)
    report["acceptance"] = _acceptance(au, p0, p1, int(window_hours * 3_600_000), scope)
    return report
