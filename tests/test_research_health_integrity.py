import json
from datetime import datetime,timezone
from pathlib import Path

import pytest

from src.operational.research_health import ResearchHealthChecker
from src.research.module_b.agent import ReportResearchAgent


@pytest.mark.asyncio
async def test_research_health_rejects_tampered_content_provenance_schema_and_version(tmp_path):
    reports=tmp_path/"data/research/module_b_reports"
    metadata=await ReportResearchAgent("audit integrity",reports_dir=reports).generate_report({"evidence":[]},created_at=datetime(2026,7,20,tzinfo=timezone.utc))
    report=tmp_path/metadata["file"] if not metadata["file"].startswith("/") else Path(metadata["file"])
    report.write_text(report.read_text()+"\nMANIPULATED CONTENT\n")
    meta_path=Path(metadata["metadata_file"]);value=json.loads(meta_path.read_text());value["provenance"]="FORGED_DETERMINISTIC";value["schema_version"]="999";meta_path.write_text(json.dumps(value))
    result=ResearchHealthChecker(tmp_path,"http://127.0.0.1:1").check()
    assert result["checks"]["report_integrity"] is False
    assert result["checks"]["report_provenance_deterministic"] is False
    assert result["checks"]["report_version"] is False
    assert result["level"]=="RED"


def test_empty_report_folder_with_module_b_off_does_not_isolate_research(tmp_path, monkeypatch):
    # Mac live setup (23.10.2026): no LLM reports, module B off. The validator
    # used to call that RED and wrote data/research/isolation.json, which stops
    # every research trigger.
    monkeypatch.setenv("TIM_RESEARCH_MODULE_B", "false")
    result=ResearchHealthChecker(tmp_path,"http://127.0.0.1:1").check()
    assert result["checks"]["report_integrity"] is True
    assert "gpt_researcher_import" not in result["critical"]
    assert result["level"]!="RED" and result["isolated"] is False


def test_reports_are_required_when_module_b_is_on(tmp_path, monkeypatch):
    monkeypatch.setenv("TIM_RESEARCH_MODULE_B", "true")
    result=ResearchHealthChecker(tmp_path,"http://127.0.0.1:1").check()
    assert result["checks"]["report_integrity"] is False
    assert result["level"]=="RED"
