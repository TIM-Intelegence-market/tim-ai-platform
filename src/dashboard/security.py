from __future__ import annotations

import ipaddress
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
