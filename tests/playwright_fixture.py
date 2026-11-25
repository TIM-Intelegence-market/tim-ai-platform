"""Provision the browser revision selected by the installed Node Playwright."""
import os
from pathlib import Path
import subprocess

import pytest


@pytest.fixture(scope="session")
def chromium_env():
    env = os.environ.copy()
    cloud = bool(env.get("CODEX_ENVIRONMENT_ID"))
    if cloud:
        env.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/workspace/scratch/tim-onboarding/playwright")
    try:
        cli = subprocess.check_output(
            ["node", "-p", "require('path').join(require('path').dirname(require.resolve('playwright/package.json')), 'cli.js')"], env=env, text=True,
            stderr=subprocess.PIPE, timeout=30,
        ).strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        if not cloud:
            pytest.skip("Node Playwright is not installed on this non-Cloud runner")
        raise
    # Playwright serializes installation in the shared cache across xdist workers.
    subprocess.run(
        ["node", cli, "install", "chromium", "--only-shell"],
        env=env, check=True, timeout=300,
    )
    return env
