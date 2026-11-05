"""Read-only Control Center view over the owner's tailnet (tailscale serve, never public)."""
from __future__ import annotations

import http.client
import json
from pathlib import Path

import pytest

from src.dashboard.app import DashboardServer, DashboardState
from src.dashboard.security import REMOTE_VIEW_FILE_ENV, _is_remote_view_request

TAILNET = "zeyirs-mac-mini.tailce31c7.ts.net"


def _request(port: int, method: str, path: str, headers: dict[str, str], body: str | None = None) -> int:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    response.read()
    return response.status


@pytest.fixture
def remote_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "dashboard-remote-view.json"
    monkeypatch.setenv(REMOTE_VIEW_FILE_ENV, str(path))
    return path


def test_off_without_config_file(remote_file: Path) -> None:
    assert not _is_remote_view_request(TAILNET, "uzi@github")


def test_only_ts_net_names_are_accepted(remote_file: Path) -> None:
    remote_file.write_text(json.dumps({"hosts": ["tim-online.online", "evil.example", TAILNET]}))
    assert _is_remote_view_request(TAILNET, None)
    assert _is_remote_view_request(f"{TAILNET}:8765", None)
    assert _is_remote_view_request(TAILNET.upper(), None)
    assert not _is_remote_view_request("tim-online.online", None)
    assert not _is_remote_view_request("evil.example", None)
    assert not _is_remote_view_request(f"x@{TAILNET}", None)
    assert not _is_remote_view_request(f"{TAILNET} ", None)


def test_user_list_restricts_tailnet_members(remote_file: Path) -> None:
    remote_file.write_text(json.dumps({"hosts": [TAILNET], "users": ["Uzi@GitHub"]}))
    assert _is_remote_view_request(TAILNET, "uzi@github")
    assert not _is_remote_view_request(TAILNET, "chris@github")
    assert not _is_remote_view_request(TAILNET, None)


@pytest.mark.parametrize("content", ["not json", "[]", '{"hosts": "x.ts.net"}', '{"hosts": [1, null]}'])
def test_broken_config_stays_closed(remote_file: Path, content: str) -> None:
    remote_file.write_text(content)
    assert not _is_remote_view_request(TAILNET, None)


def test_server_serves_get_but_refuses_post_from_tailnet(remote_file: Path) -> None:
    server = DashboardServer(DashboardState(), port=0)
    server.start()
    try:
        port = server.server.server_address[1]
        tailnet = {"Host": TAILNET, "Tailscale-User-Login": "uzi@github"}
        assert _request(port, "GET", "/", tailnet) == 421  # off until the file exists
        remote_file.write_text(json.dumps({"hosts": [TAILNET], "users": ["uzi@github"]}))
        assert _request(port, "GET", "/", tailnet) == 200
        assert _request(port, "GET", "/system", tailnet) == 200
        assert _request(port, "GET", "/", {"Host": TAILNET, "Tailscale-User-Login": "chris@github"}) == 421
        assert _request(port, "GET", "/", {"Host": "example.com"}) == 421
        post = {**tailnet, "Content-Type": "application/x-www-form-urlencoded"}
        assert _request(port, "POST", "/journal/note", post, body="a=b") == 403
        assert _request(port, "POST", "/api/research/quick", {**tailnet, "Content-Type": "application/json"}, body='{"query":"x"}') == 403
        assert _request(port, "GET", "/", {"Host": f"127.0.0.1:{port}"}) == 200
    finally:
        server.stop()
