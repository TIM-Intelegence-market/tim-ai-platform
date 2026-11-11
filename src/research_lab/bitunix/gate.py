"""PROTOTYPE trading authorization gate for a future Bitunix order path (Phase 9). Not wired, not global.

Status: prototype. No Bitunix order path exists in this repository, so nothing calls this yet. The scenario
pipeline has its own governance (``src/orderflow_scenario/governance.py``: modes, kill switch); the Kraken live
trader runs outside the repo with its own STOP file. Before any Bitunix order path is built, one central gate must
be chosen (this one merged into the existing governance, or the reverse); until then
``tests/test_research_lab_bitunix.py::test_no_bitunix_order_path_without_gate`` fails any module that talks to a
private Bitunix trading endpoint without calling :func:`require_authorized`.

Fail-closed: trading is allowed only if the environment says exactly ``TRADING_AUTHORIZED=YES`` AND no kill-switch
file exists. Anything else (unset, ``NO``, ``yes``, ``1``, whitespace, unreadable kill path) means NO. Signal code
may run without the gate; any order path must call :func:`require_authorized` first. No Bitunix order path exists
in this repository.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

ENV_VAR = "TRADING_AUTHORIZED"
KILL_SWITCH_ENV = "TIM_KILL_SWITCH_FILE"
DEFAULT_KILL_SWITCH = Path.home() / ".tim" / "KILL"


class TradingNotAuthorized(RuntimeError):
    pass


def kill_switch_path(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    raw = env.get(KILL_SWITCH_ENV)
    return Path(raw) if raw else DEFAULT_KILL_SWITCH


def authorization_status(env: Mapping[str, str] | None = None) -> tuple[bool, str]:
    env = os.environ if env is None else env
    if env.get(ENV_VAR) != "YES":
        return False, f"{ENV_VAR} is not YES"
    try:
        if kill_switch_path(env).exists():
            return False, "kill switch present"
    except OSError as exc:  # unreadable path: fail closed
        return False, f"kill switch unreadable: {exc}"
    return True, "authorized"


def is_authorized(env: Mapping[str, str] | None = None) -> bool:
    return authorization_status(env)[0]


def require_authorized(env: Mapping[str, str] | None = None) -> None:
    ok, why = authorization_status(env)
    if not ok:
        raise TradingNotAuthorized(why)
