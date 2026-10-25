"""Isolated multi-symbol prototype (OBSERVE only, default OFF).

Nothing in the live runtime imports this package. With the default
configuration it resolves to exactly the one symbol of ``TIM_SYMBOL``, so the
current single-symbol behaviour stays unchanged. See
``docs/MULTI_SYMBOL_ARCHITEKTUR.md`` for the design and the open decisions.
No module here places orders or changes risk parameters of a live system.
"""

from src.multi_symbol.config import MultiSymbolConfig, resolve_symbols

__all__ = ["MultiSymbolConfig", "resolve_symbols"]
