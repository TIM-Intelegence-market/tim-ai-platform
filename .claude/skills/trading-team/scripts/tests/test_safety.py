"""Statische Wache: der Skill bleibt reines Papier und liest nur öffentliche Daten."""

import re
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
FORBIDDEN = [
    r"/api/v3/order", r"/fapi/v1/order", r"/sapi/", r"X-MBX-APIKEY", r"signature=", r"hmac",
    r"api_secret", r"API_KEY", r"testnet", r"subprocess", r"os\.system", r"shutil\.rmtree",
]


def test_no_order_or_key_code():
    for path in SCRIPTS.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for pat in FORBIDDEN:
            assert not re.search(pat, text, re.IGNORECASE), f"{path.name}: {pat}"


def test_only_https_public_hosts():
    allowed = {"api.binance.com", "api.coingecko.com", "www.coindesk.com", "cointelegraph.com", "decrypt.co"}
    for path in SCRIPTS.glob("*.py"):
        for host in re.findall(r"https://([a-z0-9.-]+)", path.read_text(encoding="utf-8")):
            assert host in allowed, f"{path.name}: {host}"
