import json
import struct

from src.dashboard import public_en
from src.dashboard.pwa import HEAD_TAGS, assets
from src.dashboard.layout import _content_security_policy


def test_manifest_is_installable():
    body, kind = assets()["/manifest.webmanifest"]
    manifest = json.loads(body)
    assert kind == "application/manifest+json"
    assert manifest["display"] == "standalone" and manifest["start_url"] == "/chart"
    sizes = {icon["sizes"] for icon in manifest["icons"]}
    assert {"192x192", "512x512"} <= sizes
    for icon in manifest["icons"]:
        assert icon["src"] in assets()


def test_icons_are_valid_pngs_of_declared_size():
    for path, expected in (("/icon-192.png", 192), ("/icon-512.png", 512), ("/apple-touch-icon.png", 180)):
        body, kind = assets()[path]
        assert kind == "image/png" and body.startswith(b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", body[16:24])
        assert (width, height) == (expected, expected)


def test_pages_link_manifest_and_csp_allows_it():
    assert "manifest.webmanifest" in HEAD_TAGS
    assert HEAD_TAGS in public_en.shell("Chart", "/chart", "")
    assert "manifest-src 'self'" in _content_security_policy()
    assert "manifest-src 'self'" in public_en.journal_csp()
