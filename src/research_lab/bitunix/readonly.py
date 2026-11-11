"""Read-only Bitunix account client (fees, trade and position history). No order path.

The key is read from the macOS login keychain only (generic password, service ``com.tim.bitunix-read``: account =
API key, password = secret key) and never logged, printed or written. The client can only send signed GET requests
to the paths in :data:`READ_PATHS`; anything else raises before a request is built. Whether the key itself is
read-only is decided at Bitunix; :func:`check_key_cannot_trade` is not a substitute for that setting.

Signature (docs ``common/sign``, 11.11.2026): digest = SHA256(nonce + timestamp + api-key + sorted query + body),
sign = SHA256(digest + secret), both hex. Query params sorted by key and concatenated as ``key + value``.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import subprocess
import time
import urllib.parse
import urllib.request
import warnings
from collections.abc import Callable, Mapping
from dataclasses import dataclass

BASE = "https://fapi.bitunix.com"
KEYCHAIN_SERVICE = "com.tim.bitunix-read"
READ_PATHS = frozenset({
    "/api/v1/futures/account",
    "/api/v1/futures/trade/get_history_trades",
    "/api/v1/futures/position/get_history_positions",
    "/api/v1/futures/position/get_pending_positions",
})


@dataclass(frozen=True)
class Credentials:
    api_key: str
    secret: str

    def __repr__(self) -> str:  # never show the secret, not even in a traceback
        return f"Credentials(api_key={self.api_key[:4]}…, secret=***)"


def _run(cmd: list[str]) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=20).stdout


def load_from_keychain(service: str = KEYCHAIN_SERVICE, run: Callable[[list[str]], str] = _run) -> Credentials:
    """API key from the item's account attribute, secret from its password (macOS ``security``)."""
    try:
        attrs = run(["security", "find-generic-password", "-s", service])
        secret = run(["security", "find-generic-password", "-s", service, "-w"]).strip()
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"keychain item {service!r} not readable") from exc
    api_key = ""
    for line in attrs.splitlines():
        line = line.strip()
        if line.startswith('"acct"<blob>='):
            api_key = line.split("=", 1)[1].strip().strip('"')
    if not api_key or not secret:
        raise RuntimeError(f"keychain item {service!r} lacks account (API key) or password (secret)")
    return Credentials(api_key, secret)


def query_string_for_sign(params: Mapping[str, object]) -> str:
    return "".join(f"{k}{params[k]}" for k in sorted(params))


def sign(creds: Credentials, nonce: str, timestamp: str, params: Mapping[str, object], body: str = "") -> str:
    digest = hashlib.sha256((nonce + timestamp + creds.api_key + query_string_for_sign(params) + body).encode()).hexdigest()
    return hashlib.sha256((digest + creds.secret).encode()).hexdigest()


class ReadOnlyClient:
    def __init__(self, creds: Credentials, *, opener: Callable | None = None, clock: Callable[[], float] = time.time):
        self._creds = creds
        self._open = opener or (lambda req: urllib.request.urlopen(req, timeout=20))
        self._clock = clock

    def get(self, path: str, params: Mapping[str, object] | None = None) -> dict:
        if path not in READ_PATHS:
            raise PermissionError(f"{path} is not a read path of this client")
        params = {k: v for k, v in (params or {}).items() if v is not None}
        nonce = secrets.token_hex(16)
        ts = str(int(self._clock() * 1000))
        headers = {
            "api-key": self._creds.api_key,
            "nonce": nonce,
            "timestamp": ts,
            "sign": sign(self._creds, nonce, ts, params),
            "Content-Type": "application/json",
            "language": "en-US",
        }
        url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
        req = urllib.request.Request(url, headers=headers, method="GET")
        with self._open(req) as resp:
            data = json.loads(resp.read())
        if data.get("code") != 0:
            raise RuntimeError(f"bitunix {path}: code {data.get('code')} {data.get('msg')}")
        return data["data"]

    def history_trades(self, *, symbol: str | None = None, start_ms: int | None = None, max_pages: int = 50) -> list[dict]:
        out: list[dict] = []
        for page in range(max_pages):
            data = self.get("/api/v1/futures/trade/get_history_trades",
                            {"symbol": symbol, "startTime": start_ms, "skip": page * 100, "limit": 100})
            batch = data.get("tradeList") or []
            out.extend(batch)
            if len(batch) < 100:
                return out
        _truncated("trade history", max_pages)
        return out


def history_positions(client: ReadOnlyClient, *, start_ms: int | None = None, max_pages: int = 50) -> list[dict]:
    out: list[dict] = []
    for page in range(max_pages):
        data = client.get("/api/v1/futures/position/get_history_positions",
                          {"startTime": start_ms, "skip": page * 100, "limit": 100})
        batch = data.get("positionList") or []
        out.extend(batch)
        if len(batch) < 100:
            return out
    _truncated("position history", max_pages)
    return out


def _truncated(what: str, max_pages: int) -> None:
    """``skip`` is a row offset ("skip order count", docs 11.11.2026); a full last page means more rows exist."""
    warnings.warn(f"{what}: stopped after {max_pages} pages of 100, older entries are missing", stacklevel=3)


def fee_rates(trades: list[dict]) -> dict:
    """Effective fee rate per ``roleType`` from real fills: sum(|fee|) / sum(qty x price).

    On a real account the rates per tag came out the reverse of the published taker / maker fees, and the docs' own
    field description is garbled ("TAKER: maker MAKER: maker"), so the tag is reported as delivered and the rate, not
    the tag, is what counts.
    """
    acc: dict[str, list[float]] = {}
    for t in trades:
        try:
            notional = float(t["qty"]) * float(t["price"])
            fee = abs(float(t["fee"]))
        except (KeyError, TypeError, ValueError):
            continue
        if notional <= 0:
            continue
        role = str(t.get("roleType") or "UNKNOWN").upper()
        a = acc.setdefault(role, [0.0, 0.0, 0])
        a[0] += fee
        a[1] += notional
        a[2] += 1
    return {role: {"fills": int(n), "notional_usdt": round(notional, 2), "fee_usdt": round(fee, 4),
                   "rate": round(fee / notional, 6)} for role, (fee, notional, n) in acc.items()}
