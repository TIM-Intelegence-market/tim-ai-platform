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
