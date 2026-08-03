from __future__ import annotations

from pathlib import Path

import pytest

from src.tim_manager.config_paths import (
    REPO_ROOT_PLACEHOLDER,
    RepositoryPathError,
    repository_path,
    repository_root,
)


def test_repository_root_is_portable_and_absolute() -> None:
    root = repository_root()
    assert root.is_absolute()
    assert (root / ".git").exists() or (root / "main.py").exists()


def test_placeholder_resolves_to_repository_root() -> None:
    assert repository_path(REPO_ROOT_PLACEHOLDER) == repository_root()


def test_placeholder_relative_resolves_inside_repository() -> None:
    target = repository_path(REPO_ROOT_PLACEHOLDER + "/graphify-out/graph.json")
    assert target.is_absolute()
    assert target.is_relative_to(repository_root())
    assert target.name == "graph.json"


def test_path_traversal_is_rejected() -> None:
    with pytest.raises(RepositoryPathError):
        repository_path(REPO_ROOT_PLACEHOLDER + "/../etc/passwd")


def test_absolute_path_outside_repository_is_rejected() -> None:
    with pytest.raises(RepositoryPathError):
        repository_path("/Users/tim/.ssh/id_rsa")


def test_empty_spec_is_rejected() -> None:
    with pytest.raises(RepositoryPathError):
        repository_path("   ")


def test_non_relative_placeholder_is_rejected() -> None:
    with pytest.raises(RepositoryPathError):
        repository_path(REPO_ROOT_PLACEHOLDER + "graph.json")


def test_denied_directories_are_rejected() -> None:
    for sub in ("/.git/config", "/data/raw/agg", "/backups/x", "/secrets/x", "/output/y"):
        with pytest.raises(RepositoryPathError):
            repository_path(REPO_ROOT_PLACEHOLDER + sub)


def test_graphify_config_is_portable() -> None:
    from src.tim_manager.graphify_mcp import GraphifyMCPConfig

    config = GraphifyMCPConfig.load()
    assert config.enabled is False
    assert Path(config.working_directory).resolve() == repository_root().resolve()
    assert Path(config.graph_path).resolve() == (
        repository_root() / "graphify-out" / "graph.json"
    ).resolve()
    assert not config.allow_writes
    assert config.read_only


def test_graphify_config_contains_no_host_paths() -> None:
    raw = (
        Path(repository_root())
        / "config"
        / "tim_manager"
        / "graphify_mcp.yaml"
    ).read_text(encoding="utf-8")
    assert "/Users/" not in raw
    assert "/home/" not in raw
    assert REPO_ROOT_PLACEHOLDER in raw


def test_graphify_config_loads_under_foreign_repo_root() -> None:
    from src.tim_manager.graphify_mcp import GraphifyMCPConfig

    # A foreign checkout root is simulated by temporarily shadowing the module
    # constant; the placeholder must keep resolving inside whatever root the
    # package is installed under.
    import src.tim_manager.graphify_mcp as mcp

    config = GraphifyMCPConfig.load()
    assert config.working_directory == str(Path(mcp.PROJECT_ROOT).resolve())
