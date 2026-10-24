import json
from datetime import datetime, timedelta, timezone

from src.research.config import ResearchConfig
from src.research.module_a.agent import LocalResearchAgent, cache_record
from src.research_ops.audit import digest
from src.v2_completion.provenance_inventory import build_inventory

T0 = datetime(2026, 10, 23, 18, 0, tzinfo=timezone.utc)
LEGACY = {"research_id": "a", "created_at": "2026-10-01T00:00:00+00:00", "mode": "OBSERVE", "provenance": "TIM_DETERMINISTIC", "input_hash": "1" * 64}


def _write(root, rows):
    path = root / "data/research/module_a_cache.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join((r if isinstance(r, str) else json.dumps(r)) + "\n" for r in rows))
    return path


def _new_row(agent, question, at):
    return cache_record(agent.analyze(question, [{"summary": question}], created_at=at))


def test_cache_rows_carry_v2_provenance_fields(tmp_path):
    agent = LocalResearchAgent(ResearchConfig(cache_path=tmp_path / "cache.jsonl", report_root=tmp_path / "r"))
    agent.analyze("q", [{"summary": "x"}], created_at=T0)
    row = json.loads((tmp_path / "cache.jsonl").read_text().splitlines()[0])
    assert row["schema_version"] == "1.0.0" and row["generator_version"] == "1.0.0"
    assert row["artifact_hash"] == digest({k: v for k, v in row.items() if k != "artifact_hash"})


def test_inventory_classifies_legacy_prospective_and_conflicts(tmp_path):
    agent = LocalResearchAgent(ResearchConfig(cache_path=tmp_path / "x.jsonl", report_root=tmp_path / "r"))
    good = _new_row(agent, "neu", T0)
    tampered = dict(_new_row(agent, "neu2", T0 + timedelta(minutes=1)), summary="geändert")
    late_gap = dict(LEGACY, research_id="b", created_at=(T0 + timedelta(minutes=2)).isoformat())
    broken = {"research_id": "c", "mode": "OBSERVE"}
    path = _write(tmp_path, [LEGACY, good, tampered, late_gap, broken, "{kaputt"])
    before = path.read_bytes()
    inv = build_inventory(tmp_path, cutoff=T0 + timedelta(hours=1))
    cache = inv["module_a_cache"]
    assert inv["v2_boundary"] == T0.isoformat()
    assert cache["classes"] == {"COMPLETE_PROSPECTIVE": 1, "PARTIAL_LEGACY": 1, "NON_RECONSTRUCTABLE": 2, "CONFLICTING": 2}
    assert cache["prospective_records"] == 3
    assert cache["prospective_complete_percent"] == 33.333
    assert inv["bytes_unchanged"] is True and path.read_bytes() == before


def test_inventory_without_new_records_has_no_boundary(tmp_path):
    _write(tmp_path, [LEGACY])
    inv = build_inventory(tmp_path, cutoff=T0)
    assert inv["v2_boundary"] is None
    assert inv["module_a_cache"]["classes"]["PARTIAL_LEGACY"] == 1
    assert inv["module_a_cache"]["prospective_complete_percent"] is None


def test_inventory_respects_cutoff_and_given_boundary(tmp_path):
    agent = LocalResearchAgent(ResearchConfig(cache_path=tmp_path / "x.jsonl", report_root=tmp_path / "r"))
    _write(tmp_path, [LEGACY, _new_row(agent, "neu", T0), _new_row(agent, "später", T0 + timedelta(days=2))])
    inv = build_inventory(tmp_path, cutoff=T0 + timedelta(hours=1), boundary=T0 - timedelta(days=30))
    cache = inv["module_a_cache"]
    assert cache["records"] == 2
    assert inv["v2_boundary_source"] == "given"
    # the legacy row lies after the given boundary and lacks V2 fields
    assert cache["classes"]["CONFLICTING"] == 1 and cache["classes"]["COMPLETE_PROSPECTIVE"] == 1


def test_inventory_lists_checklist_fields_of_json_artifacts(tmp_path):
    _write(tmp_path, [LEGACY])
    status = tmp_path / "data/research/status/x.json"
    status.parent.mkdir(parents=True)
    status.write_text(json.dumps({"schema_version": "1.0.0", "generated_at": "2026-10-01T00:00:00Z", "provenance": "P_DETERMINISTIC"}))
    audit = tmp_path / "data/research/audit/latest.json"
    audit.parent.mkdir(parents=True)
    audit.write_text("{}")
    inv = build_inventory(tmp_path, cutoff=T0)
    assert [a["path"] for a in inv["artifacts"]] == ["data/research/status/x.json"]
    assert "generator_version" in inv["artifacts"][0]["missing"]
    assert "provenance" in inv["artifacts"][0]["present"]
