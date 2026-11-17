"""P4: the Mac copies the PS5 live journal read-only and compares it with stage A; the card shows both."""
from __future__ import annotations

import json
import subprocess

from src.research_lab.forward import of_live_mirror
from src.research_lab.forward.of_paper import FOLDER as STAGE_A

DAY = 86_400_000
T0 = 1_794_960_000_000  # 2026-11-18 00:00 UTC


def trade(signal_ms, net_r=1.0, exit_ms=None):
    return {"signal_ms": signal_ms, "model": "M1", "direction": 1, "fill_ms": signal_ms + 60_000,
            "exit_ms": exit_ms or signal_ms + 3_600_000, "reason": "TARGET", "net_r": net_r}


def journal(first_day, last_day, trades):
    return {"status": {"first_day": first_day, "last_day": last_day}, "trades": trades}


def test_compare_only_looks_at_days_both_have_finished():
    a = journal("2026-11-11", "2026-11-19", [trade(T0 - DAY), trade(T0 + 1000), trade(T0 + DAY + 5000)])
    live = journal("2026-11-18", "2026-11-20", [trade(T0 + 1000), trade(T0 + DAY + 5000), trade(T0 + 2 * DAY + 10)])
    out = of_live_mirror.compare(live, a)
    assert out["ok"] is True and out["gleich"] == 2 and out["bis"] == "2026-11-19"
    live["trades"][0]["net_r"] = 0.5
    out = of_live_mirror.compare(live, a)
    assert out["ok"] is False and len(out["nur_live"]) == 1 and len(out["nur_archiv"]) == 1


def test_compare_waits_for_a_common_day():
    out = of_live_mirror.compare(journal("2026-11-18", None, []), journal("2026-11-11", "2026-11-17", []))
    assert out["ok"] is None and out["grund"] == "noch kein gemeinsamer Tag"
    assert of_live_mirror.compare(None, None)["ok"] is None


def test_scp_command_keeps_the_warpgate_user_out_of_the_host():
    argv = of_live_mirror.scp_argv({"ssh": "uzi:ps5-research@gate.example", "port": 2222, "identity": "~/.ssh/k",
                                    "remote_folder": "~/tim-research/of-live/journal"}, "status.json", "/tmp/x")
    assert argv[:3] == ["scp", "-o", "BatchMode=yes"] and "User=uzi:ps5-research" in argv
    assert argv[-2] == "gate.example:tim-research/of-live/journal/status.json" and "-P" in argv


def test_pull_copies_compares_and_keeps_the_old_copy_on_failure(tmp_path):
    folder = tmp_path / of_live_mirror.FOLDER
    folder.mkdir(parents=True)
    assert of_live_mirror.pull(tmp_path) == {"pulled": False, "reason": "kein pull.json"}
    (folder / "pull.json").write_text(json.dumps({"ssh": "u@h", "remote_folder": "~/j"}))
    (tmp_path / STAGE_A).mkdir(parents=True)
    (tmp_path / STAGE_A / "journal.json").write_text(json.dumps(journal("2026-11-11", "2026-11-18", [trade(T0 + 9)])))
    remote = {"status.json": {"first_day": "2026-11-18"}, "journal.json": journal("2026-11-18", "2026-11-18", [trade(T0 + 9)])}
    calls = []

    def ok(argv):
        calls.append(argv)
        name = argv[-2].rsplit("/", 1)[1]
        open(argv[-1], "w").write(json.dumps(remote[name]))
        return subprocess.CompletedProcess(argv, 0, "", "")

    out = of_live_mirror.pull(tmp_path, run=ok)
    assert out["pulled"] and out["abgleich"]["ok"] is True and out["last_ok"] == out["pulled_at"]
    assert all(a[0] == "scp" for a in calls)   # read only: copies from the PS5, never writes there

    def fail(argv):
        return subprocess.CompletedProcess(argv, 1, "", "Connection refused")

    out = of_live_mirror.pull(tmp_path, run=fail)
    assert out["pulled"] is False and out["errors"] and out["last_ok"] is not None
    assert json.loads((folder / "status.json").read_text()) == {"first_day": "2026-11-18"}   # old copy kept


def test_card_shows_age_and_comparison():
    from src.dashboard.screens import _of_live_card

    assert "Noch keine Daten von der PS5" in _of_live_card(None)
    html = _of_live_card({"first_day": "2026-11-18", "live_until": "2026-11-18T10:24:00Z",
                          "recorder_stand": "2026-11-18T10:25:00Z", "trades": 1, "min_trades": 100, "net_r": 1.0,
                          "mean_r": 1.0, "open": [], "mirror": {"last_ok": "2026-11-18T10:30:00Z", "errors": [],
                          "abgleich": {"ok": False, "ab": "2026-11-18", "bis": "2026-11-18", "nur_live": [1],
                                       "nur_archiv": []}}})
    assert "Abweichung" in html and "1 von 100 Trades" in html and "Recorder" in html


def test_workshop_overview_reads_the_copy(tmp_path):
    from src.research_lab.workshop.overview import overview

    folder = tmp_path / of_live_mirror.FOLDER
    folder.mkdir(parents=True)
    (folder / "status.json").write_text(json.dumps({"first_day": "2026-11-18", "trades": 0}))
    (folder / "mirror.json").write_text(json.dumps({"last_ok": "x", "abgleich": {"ok": None}}))
    data = overview(tmp_path)
    assert data["of_live"]["first_day"] == "2026-11-18" and data["of_live"]["mirror"]["last_ok"] == "x"
