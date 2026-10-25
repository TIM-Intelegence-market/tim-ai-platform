"""Configurable symbol list; disabled by default (one symbol stays the default)."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass

SYMBOL_PATTERN = re.compile(r"[A-Z0-9]{3,20}")
# Upper bound for the prototype: three test symbols plus headroom. A larger
# list needs a fresh load measurement first (deepcopy, outbox, sockets).
MAX_SYMBOLS = 5
DEFAULT_SYMBOL = "BTCUSDT"


@dataclass(frozen=True, slots=True)
class MultiSymbolConfig:
    enabled: bool
    symbols: tuple[str, ...]

    @property
    def primary(self) -> str:
        return self.symbols[0]


def _flag(value: str | None) -> bool:
    if value is None or value.strip() == "":
        return False
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError("TIM_MULTI_SYMBOL_ENABLED must be true or false")


def _symbol(raw: str) -> str:
    symbol = raw.strip().upper()
    if not SYMBOL_PATTERN.fullmatch(symbol):
        raise ValueError(f"invalid symbol: {raw!r}")
    return symbol


def resolve_symbols(env: Mapping[str, str] | None = None) -> MultiSymbolConfig:
    """Resolve the symbol list fail-closed.

    Disabled (default): exactly ``(TIM_SYMBOL,)``; ``TIM_SYMBOLS`` is ignored.
    Enabled: ``TIM_SYMBOLS`` (comma list). The primary ``TIM_SYMBOL`` must be in
    the list and is always placed first, so single-symbol consumers keep
    reading the same symbol. Duplicates, invalid names and more than
    ``MAX_SYMBOLS`` entries raise instead of being silently dropped.
    """
    source = os.environ if env is None else env
    primary = _symbol(source.get("TIM_SYMBOL", DEFAULT_SYMBOL) or DEFAULT_SYMBOL)
    enabled = _flag(source.get("TIM_MULTI_SYMBOL_ENABLED"))
    if not enabled:
        return MultiSymbolConfig(False, (primary,))
    raw = source.get("TIM_SYMBOLS", "")
    items = [_symbol(item) for item in raw.split(",") if item.strip()]
    if not items:
        raise ValueError("TIM_SYMBOLS must list at least one symbol when multi-symbol is enabled")
    if len(set(items)) != len(items):
        raise ValueError("TIM_SYMBOLS contains duplicates")
    if primary not in items:
        raise ValueError("TIM_SYMBOL must be part of TIM_SYMBOLS")
    if len(items) > MAX_SYMBOLS:
        raise ValueError(f"at most {MAX_SYMBOLS} symbols are allowed in the prototype")
    ordered = (primary, *(item for item in items if item != primary))
    return MultiSymbolConfig(True, ordered)
