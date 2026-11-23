import importlib.util
import plistlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("diary_script", ROOT / "scripts" / "signalgruppe_paper_diary.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cycle_fetches_then_runs_with_workdir_files(tmp_path, monkeypatch):
    module = _load()
    calls = []
    monkeypatch.setattr(module, "cmd_fetch", lambda a: calls.append(("fetch", a.out)) or 0)
    monkeypatch.setattr(module, "cmd_run", lambda a: calls.append(("run", a.snapshot, a.diary, a.report)) or 0)
    assert module.main(["cycle", "--feed-dir", str(tmp_path), "--workdir", str(tmp_path / "w")]) == 0
    assert calls[0] == ("fetch", tmp_path / "w" / "snapshot.json")
    assert calls[1] == ("run", tmp_path / "w" / "snapshot.json", tmp_path / "w" / "diary.json", tmp_path / "w" / "papier-tagebuch.md")


def test_cycle_stops_when_fetch_fails(tmp_path, monkeypatch):
    module = _load()
    ran = []
    monkeypatch.setattr(module, "cmd_fetch", lambda a: 1)
    monkeypatch.setattr(module, "cmd_run", lambda a: ran.append(1) or 0)
    assert module.main(["cycle", "--feed-dir", str(tmp_path), "--workdir", str(tmp_path)]) == 1
    assert not ran


def test_plist_template_is_valid_every_15_minutes():
    text = (ROOT / "launchd" / "com.tim.signalgruppe-diary.plist.template").read_text(encoding="utf-8")
    for key in ("__PYTHON__", "__FEED_DIR__", "__WORKDIR__", "__REPO__", "__LOG_DIR__"):
        text = text.replace(key, "/x")
    value = plistlib.loads(text.encode())
    assert value["StartInterval"] == 900
    assert "cycle" in value["ProgramArguments"]
