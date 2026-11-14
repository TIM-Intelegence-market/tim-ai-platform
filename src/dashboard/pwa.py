"""Installable-app support (PWA): manifest, icons and head tags for the TIM web pages.

No service worker on purpose: the chart is live data, an offline cache would only show stale prices.
Icons are drawn here (a dark square with the green TIM mark), so there is no binary file in the repo.
"""
from __future__ import annotations

import json
import struct
import zlib
from functools import lru_cache

THEME = "#070a0f"
MARK = (0x35, 0xD3, 0x9A)
START_URL = "/chart"

HEAD_TAGS = (
    "<link rel='manifest' href='/manifest.webmanifest'>"
    "<link rel='apple-touch-icon' href='/apple-touch-icon.png'>"
    f"<meta name='theme-color' content='{THEME}'>"
    "<meta name='mobile-web-app-capable' content='yes'><meta name='apple-mobile-web-app-capable' content='yes'>"
    "<meta name='apple-mobile-web-app-title' content='TIM'>"
    "<meta name='apple-mobile-web-app-status-bar-style' content='black-translucent'>"
)


def _png(size: int, mark_ratio: float) -> bytes:
    """Solid dark square with a centred green square (mark_ratio = its share of the side)."""
    mark = int(size * mark_ratio)
    lo, hi = (size - mark) // 2, (size - mark) // 2 + mark
    bg = bytes((0x07, 0x0A, 0x0F))
    fg = bytes(MARK)
    plain = b"\x00" + bg * size
    row = b"\x00" + bg * lo + fg * (hi - lo) + bg * (size - hi)
    raw = b"".join(row if lo <= y < hi else plain for y in range(size))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


@lru_cache(maxsize=1)
def assets() -> dict[str, tuple[bytes, str]]:
    manifest = {
        "name": "TIM Trading Intelligence Machine", "short_name": "TIM",
        "description": "TIM live chart and journal (read-only)",
        "start_url": START_URL, "scope": "/", "display": "standalone",
        "background_color": THEME, "theme_color": THEME,
        "icons": [
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }
    return {
        "/manifest.webmanifest": (json.dumps(manifest).encode(), "application/manifest+json"),
        "/icon-192.png": (_png(192, 0.5), "image/png"),
        "/icon-512.png": (_png(512, 0.5), "image/png"),
        "/icon-maskable-512.png": (_png(512, 0.36), "image/png"),
        "/apple-touch-icon.png": (_png(180, 0.5), "image/png"),
    }
