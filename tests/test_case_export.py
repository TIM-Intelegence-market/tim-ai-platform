import base64
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.research.case_engine import ResearchCase
from src.research.case_export import DISCLAIMER, build_case_export, to_html, to_json, verify_case_export
from src.research_ops.audit import digest

ROOT = Path(__file__).resolve().parents[1]
AT = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)


def sample_case() -> ResearchCase:
    return ResearchCase(
        case_id="case_0123456789abcdef", symbol="BTCUSDT", timeframe="5m",
        opened_at=datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc), updated_at=datetime(2026, 9, 28, 10, 25, tzinfo=timezone.utc),
        observation_ids=["obs-1"],
        evidence=[{"observation_id": "obs-1", "kind": "BOS_BULLISH", "observed_at": "2026-09-28T10:25:00+00:00", "input_hash": "a" * 64, "provenance": {"source": "binance", "note": "</script><b>x</b>"}}],
        missing_evidence=["level_reaction_context"], rule_versions={"bos": "1.2.0"},
    )


def test_export_hash_is_stable_and_verifiable() -> None:
    first = build_case_export(sample_case(), exported_at=AT)
    second = build_case_export(sample_case().to_dict(), exported_at=AT)
    assert first["output_hash"] == second["output_hash"]
    assert verify_case_export(first)
    assert verify_case_export(json.loads(to_json(first)))


def test_tampering_is_detected() -> None:
    export = json.loads(to_json(build_case_export(sample_case(), exported_at=AT)))
    export["case"]["status"] = "CONFIRMED"
    assert not verify_case_export(export)
    export = build_case_export(sample_case(), exported_at=AT)
    export["output_hash"] = "0" * 64
    assert not verify_case_export(export)
    assert not verify_case_export({"case": {}})


def test_naive_timestamp_and_missing_id_are_rejected() -> None:
    with pytest.raises(ValueError):
        build_case_export(sample_case(), exported_at=datetime(2026, 9, 28))
    with pytest.raises(ValueError):
        build_case_export({"symbol": "BTCUSDT"}, exported_at=AT)


def test_html_embeds_exact_hashed_bytes_and_escapes_content() -> None:
    export = build_case_export(sample_case(), exported_at=AT)
    page = to_html(export)
    assert DISCLAIMER in page and export["output_hash"] in page
    assert "</script><b>" not in page
    embedded = page.split("id='tim-case'>", 1)[1].split("</script>", 1)[0]
    body = dict(export)
    body.pop("output_hash")
    raw = base64.b64decode(embedded)
    assert json.loads(raw) == body
    assert digest(raw) == export["output_hash"]


def test_verify_script_accepts_original_and_rejects_changed_file(tmp_path: Path) -> None:
    source = tmp_path / "case.json"
    source.write_text(json.dumps(sample_case().to_dict()), encoding="utf-8")
    out = tmp_path / "out"
    subprocess.run([sys.executable, str(ROOT / "scripts/export_case.py"), "--file", str(source), "--out", str(out)], check=True, capture_output=True)
    exported = out / "case_0123456789abcdef.json"
    assert (out / "case_0123456789abcdef.html").exists()
    ok = subprocess.run([sys.executable, str(ROOT / "scripts/verify_case.py"), str(exported)], capture_output=True, text=True)
    assert ok.returncode == 0 and ok.stdout.startswith("OK")
    exported.write_text(exported.read_text(encoding="utf-8").replace("BTCUSDT", "ETHUSDT"), encoding="utf-8")
    bad = subprocess.run([sys.executable, str(ROOT / "scripts/verify_case.py"), str(exported)], capture_output=True, text=True)
    assert bad.returncode == 1 and bad.stdout.startswith("FEHLER")


def test_export_script_refuses_path_like_case_id(tmp_path: Path) -> None:
    source = tmp_path / "case.json"
    source.write_text(json.dumps({**sample_case().to_dict(), "case_id": "../escape"}), encoding="utf-8")
    result = subprocess.run([sys.executable, str(ROOT / "scripts/export_case.py"), "--file", str(source), "--out", str(tmp_path / "out")], capture_output=True, text=True)
    assert result.returncode != 0
    assert not (tmp_path / "escape.json").exists()
