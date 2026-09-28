"""Explicit fixtures for configuration-state contracts, never runtime toggles."""
import copy
import pytest


@pytest.fixture
def graphify_disabled_config(monkeypatch):
    import src.tim_manager.graphify_mcp as graphify
    original = graphify.load_config
    def fixture_config(name):
        value = copy.deepcopy(original(name))
        if name == 'graphify_mcp.yaml':
            value['enabled'] = False
        return value
    monkeypatch.setattr(graphify, 'load_config', fixture_config)
