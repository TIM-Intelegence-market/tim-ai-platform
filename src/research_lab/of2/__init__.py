"""OF2: TIM's orderflow engine as a research study (paper only, no orders).

Rules: docs/research_lab/studien/OF2_ORDERFLOW_ENGINE_PRAEREGISTRIERUNG_ENTWURF.md.
Input: S8 minute bars and day profiles (src.research_lab.orderflow_ml), BTCUSDT spot 2020–2024.
The holdout from 2025-01-01 is never loaded (store.guard).

Chain of thought (Bootcamp p. 95, confirmed by every library source):
HTF location -> regime -> liquidity event -> orderflow confirmation -> entry on the reaction
-> stop at the invalidation -> target at the next level. Every parameter lives in ``Config``
and is frozen by its hash before the first data access.
"""
from src.research_lab.of2.config import DEFAULT_CONFIG, VERSION, Config

__all__ = ["DEFAULT_CONFIG", "VERSION", "Config"]
