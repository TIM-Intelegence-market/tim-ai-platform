"""OpenCode executor health probe tests (Phase 3).

The probe is desktop-aware, read-only and fail-closed: AVAILABLE only
with OPENCODE_CLIENT=desktop plus a project-local .agents/skills/
marker. It reports executor presence for routing and grants nothing.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.agent_infra.health import ToolHealthRegistry, probe_opencode
from src.agent_infra.router import AVAILABLE, UNKNOWN, UNAVAILABLE, ToolRouter
from src.agent_infra.router import ContextRequest, Intent


@pytest.fixture
def clean_env(monkeypatch):
    monkeypatch.delenv("OPENCODE_CLIENT", raising=False)
    return monkeypatch


def test_desktop_available_with_project_marker(clean_env, tmp_path, monkeypatch):
    skills = tmp_path / ".agents" / "skills" / "demo"
    skills.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENCODE_CLIENT", "desktop")
    state, evidence = probe_opencode()
    assert state == AVAILABLE
    assert ".agents/skills/" in evidence


def test_evidence_absent_is_unavailable(clean_env):
    state, _ = probe_opencode()
    assert state == UNAVAILABLE


def test_conflicting_client_is_unknown(clean_env, monkeypatch):
    monkeypatch.setenv("OPENCODE_CLIENT", "web")
    state, _ = probe_opencode()
    assert state == UNKNOWN


def test_desktop_without_marker_is_unknown(clean_env, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENCODE_CLIENT", "desktop")
    state, _ = probe_opencode()
    assert state == UNKNOWN


def test_project_root_override(clean_env, tmp_path, monkeypatch):
    skills = tmp_path / ".agents" / "skills"
    skills.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("OPENCODE_CLIENT", "desktop")
    monkeypatch.setenv("OPENCODE_PROJECT_ROOT", tmp_path.as_posix())
    state, evidence = probe_opencode()
    assert state == AVAILABLE
    assert ".agents/skills/" in evidence


def test_cli_absence_does_not_block_desktop(clean_env, tmp_path, monkeypatch,
                                           ):
    """No shell `opencode` binary is required by the probe."""
    skills = tmp_path / ".agents" / "skills"
    skills.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENCODE_CLIENT", "desktop")
    monkeypatch.setenv("PATH", tmp_path.as_posix())  # no opencode binary
    state, _ = probe_opencode()
    assert state == AVAILABLE


def test_implementation_route_selects_opencode_when_available(
        clean_env, tmp_path, monkeypatch):
    skills = tmp_path / ".agents" / "skills"
    skills.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENCODE_CLIENT", "desktop")
    registry = ToolHealthRegistry(
        probes={"OpenCode": probe_opencode,
                "GLM": lambda: (UNAVAILABLE, "no probe")})
    registry.refresh()
    router = ToolRouter()
    decision = router.route(ContextRequest(intent=Intent.IMPLEMENTATION),
                            registry.availability)
    assert decision.primary_tool.value == "OpenCode"
    assert decision.blocked is False


def test_router_grants_no_write_authority(clean_env):
    """The routing decision carries no write grant by construction."""
    router = ToolRouter()
    decision = router.route(ContextRequest(intent=Intent.IMPLEMENTATION),
                            {"OpenCode": AVAILABLE, "GLM": UNAVAILABLE})
    assert decision.blocked is False
    assert not hasattr(decision, "write_authority")
    assert "write" not in decision.reason.lower()


def test_registry_reports_opencode_with_evidence(clean_env, monkeypatch):
    monkeypatch.setenv("OPENCODE_CLIENT", "desktop")
    registry = ToolHealthRegistry(probes={"OpenCode": probe_opencode})
    statuses = registry.refresh()
    assert statuses["OpenCode"]["state"] in (AVAILABLE, UNKNOWN)
    assert statuses["OpenCode"]["evidence"]
    assert statuses["OpenCode"]["observed_at"]
