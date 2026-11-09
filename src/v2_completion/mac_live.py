"""Evidence helpers for running TIM and the V2 qualification on the Mac mini (launchd).

The repository's launchd templates in ops/launchd name the historical checkout
/Users/tim/Documents/TIM/tim. A live installation renders them for its own checkout
(for example ~/TIM-live) and installs them into ~/Library/LaunchAgents. The start gate
"configuration_and_commit_frozen" compares the installed files with a fresh rendering, so
any hand edit or stale path counts as drift. Nothing here starts, stops or changes TIM.
"""
from __future__ import annotations

import ipaddress
import re
import socket
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

TEMPLATE_ROOT = "/Users/tim/Documents/TIM/tim"
TEMPLATE_HOME = "/Users/tim"
TEMPLATE_USER = "tim-user"
LIVE_AGENTS = ("com.tim.runtime", "com.tim.watchdog", "com.tim.server-health", "com.tim.history-recovery",
               "com.tim.qualification-daily")
JSONL_BOUND = 2 * 10 * 1024 * 1024
LOG_BOUND = 512 * 1024 * 1024


def render_plist(template: bytes, root: Path, home: Path) -> bytes:
    """Point a repository launchd template at ``root`` (checkout) and ``home``."""
    text = template.decode("utf-8").replace(TEMPLATE_ROOT, str(root))
    text = text.replace(f"<key>UserName</key><string>{TEMPLATE_USER}</string>",
                        f"<key>UserName</key><string>{home.name}</string>")
    return text.replace(TEMPLATE_HOME + "/", str(home) + "/").replace(
        f"<string>{TEMPLATE_HOME}</string>", f"<string>{home}</string>").encode("utf-8")


def launchd_drift(root: Path, agents_dir: Path, home: Path, labels: tuple[str, ...] = LIVE_AGENTS) -> list[str] | None:
    """Labels whose installed plist is missing or differs from the rendered template."""
    try:
        drift = []
        for label in labels:
            expected = render_plist((root / f"ops/launchd/{label}.plist").read_bytes(), root, home)
            installed = agents_dir / f"{label}.plist"
            if not installed.exists() or installed.read_bytes() != expected:
                drift.append(label)
        return drift
    except OSError:
        return None


def launchctl_state(print_output: str | None) -> str | None:
    """Map ``launchctl print gui/<uid>/<label>`` to the systemd-style word the gates expect."""
    if print_output is None:
        return None
    match = re.search(r"^\s*state = (\S+)", print_output, re.MULTILINE)
    if match is None:
        return None
    return "active" if match.group(1) == "running" else match.group(1)


def interface_addresses(ifconfig_output: str) -> list[str]:
    """Non-loopback, non-link-local IPv4/IPv6 addresses from ``ifconfig`` output."""
    hosts = []
    for line in ifconfig_output.splitlines():
        parts = line.split()
        if len(parts) < 2 or parts[0] not in {"inet", "inet6"}:
            continue
        host = parts[1].split("%", 1)[0]
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            continue
        if not (address.is_loopback or address.is_link_local):
            hosts.append(host)
    return sorted(set(hosts))


def reachable(host: str, port: int, timeout: float = 2.0) -> bool:
    """True when a TCP connection to host:port is accepted."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def reachable_hosts(hosts: Sequence[str], port: int, timeout: float = 1.0) -> list[str]:
    """The hosts (in input order) that accept a TCP connection on ``port``, probed in parallel.

    A Mac with IPv6 privacy addresses has twenty or more interface addresses; probing them one
    after another costs ``timeout`` seconds per unreachable address, which made ``timctl status``
    take over 20 seconds and the watchdog (10-second budget) read the runtime as missing
    (restart loop of 08./09.11.2026). All probes now run at once, so the wall time is one timeout.
    """
    if not hosts:
        return []
    with ThreadPoolExecutor(max_workers=min(32, len(hosts))) as pool:
        results = list(pool.map(lambda host: reachable(host, port, timeout=timeout), hosts))
    return [host for host, ok in zip(hosts, results) if ok]


def log_rotation_evidence(operational: Path) -> tuple[dict[str, datetime], list[str]]:
    """Rotated archives with their write time, and log files that outgrew their bound."""
    archives = {path.name: datetime.fromtimestamp(path.stat().st_mtime, UTC) for path in operational.glob("*.gz")}
    oversized = sorted(
        path.name for path in operational.iterdir()
        if path.is_file() and ((path.suffix == ".jsonl" and path.stat().st_size > JSONL_BOUND)
                               or (path.suffix == ".log" and path.stat().st_size > LOG_BOUND)))
    return archives, oversized
