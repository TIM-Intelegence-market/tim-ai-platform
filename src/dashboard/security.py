from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

def _require_loopback_host(host: str) -> str:
    """Reject dashboard binds that could expose the research UI off-host."""
    normalized = host.strip().lower()
    if normalized == "localhost":
        return host
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError as exc:
        raise ValueError("dashboard host must be an explicit loopback address") from exc
    if not address.is_loopback:
        raise ValueError("dashboard host must be loopback-only")
    return host


def _is_loopback_request_host(value: str | None) -> bool:
    """Reject DNS-rebinding style Host headers before serving local evidence."""
    if not value or any(character.isspace() for character in value) or any(character in value for character in "@/?#\\"):
        return False
    try:
        hostname = urlparse(f"//{value}").hostname
        return bool(hostname and _require_loopback_host(hostname))
    except (ValueError, TypeError):
        return False


# Read-only view from the owner's own Tailscale network (Uzi, 04.11.2026: Control Center am Handy).
# Off unless the owner writes this file on the Mac. Only ``*.ts.net`` names count, so a typo can never
# open the dashboard to a public domain; ``tailscale serve`` (never Funnel) is the only way in.
REMOTE_VIEW_FILE_ENV = "TIM_DASHBOARD_REMOTE_VIEW_FILE"
REMOTE_VIEW_FILE = Path.home() / "Library/Application Support/TIM/dashboard-remote-view.json"
_remote_view_cache: dict[str, Any] = {"key": None, "config": {"hosts": frozenset(), "users": frozenset()}}


def _remote_view_file() -> Path:
    return Path(os.environ.get(REMOTE_VIEW_FILE_ENV) or REMOTE_VIEW_FILE)


def remote_view_config() -> dict[str, frozenset[str]]:
    """Allowed tailnet host names and (optional) Tailscale logins; empty when off or unreadable."""
    path = _remote_view_file()
    try:
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size)
    except OSError:
        return {"hosts": frozenset(), "users": frozenset()}
    if _remote_view_cache["key"] == key:
        return _remote_view_cache["config"]
    config: dict[str, frozenset[str]] = {"hosts": frozenset(), "users": frozenset()}
    try:
        raw = json.loads(path.read_text(encoding="utf-8")) if stat.st_size <= 4096 else {}
        hosts = raw.get("hosts", []) if isinstance(raw, dict) else []
        users = raw.get("users", []) if isinstance(raw, dict) else []
        config = {
            "hosts": frozenset(h.strip().lower().rstrip(".") for h in hosts
                               if isinstance(h, str) and h.strip().lower().rstrip(".").endswith(".ts.net")),
            "users": frozenset(u.strip().lower() for u in users if isinstance(u, str) and u.strip()),
        }
    except (OSError, ValueError, AttributeError):
        pass
    _remote_view_cache.update(key=key, config=config)
    return config


def _is_remote_view_request(host_value: str | None, tailscale_login: str | None) -> bool:
    """True for a GET that came in through ``tailscale serve`` under an allowed tailnet name."""
    if not host_value or any(character.isspace() for character in host_value) or any(character in host_value for character in "@/?#\\"):
        return False
    config = remote_view_config()
    if not config["hosts"]:
        return False
    try:
        hostname = (urlparse(f"//{host_value}").hostname or "").rstrip(".")
    except ValueError:
        return False
    if hostname not in config["hosts"]:
        return False
    if config["users"]:
        return bool(tailscale_login) and tailscale_login.strip().lower() in config["users"]
    return True
