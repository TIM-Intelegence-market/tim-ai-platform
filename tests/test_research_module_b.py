import subprocess
from pathlib import Path

import pytest

from src.research.module_b.agent import run_deep_research


@pytest.mark.asyncio
async def test_module_b_local_report_and_isolated_gpt_researcher(tmp_path:Path)->None:
    result=await run_deep_research("review",{"evidence":[{"source":"TIM","provenance":"PUBLIC_MARKET_DATA_DETERMINISTIC","summary":"documented evidence"}]},reports_dir=tmp_path)
    assert result["module"]=="B" and result["mode"]=="OBSERVE"
    root=Path(__file__).resolve().parents[1]
    probe=subprocess.run([str(root/".venv-research/bin/python"),"-c","import gpt_researcher; print('ok')"],capture_output=True,text=True,timeout=30)
    assert probe.returncode==0 and "ok" in probe.stdout
