"""The three paper shadows of TIM's 15m/1h plans, for Monero (Bauplan XMR, Paket 3; Barti 11.11./24.11.2026).

For BTC, every 15m/1h plan is also read by three shadows that never change a plan:

- Orderflow-Schatten (``orderflow_shadow``): the wave at plan and fill, and when the orderflow would have left,
- Chart-Urteil (``chart_verdict``): the whole chart weighed for the plan (levels, structure, trend lines, orderflow),
- Zweitmeinung (``plan_opinion``): DeepSeek via Hermes writes for / against / verdict.

This module runs the same three functions on the XMR journals (``perp_journal.XMR_PATHS``) with the XMR perp
candles, the XMR perp trades and the XMR Live-Orderflow-Lage (``src.orderflow.xmr_live``). Own files (``PATHS``),
so a BTC shadow file is never read or written here. A Lage of another symbol is dropped (``xmr_live.for_symbol``):
an XMR plan never gets BTC's wave. Paper only: nothing here filters, changes a plan or trades.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.orderflow.xmr_live import SYMBOL, for_symbol

PATHS = {
    "orderflow": Path("data/journal/tim_orderflow_shadow_xmr.json"),
    "verdict": Path("data/journal/tim_chart_verdict_xmr.json"),
    "opinion": Path("data/journal/tim_plan_opinion_xmr.json"),
}


def _journals(journal_paths: Mapping[str, Path] | None) -> tuple[Path, ...]:
    from src.dashboard.perp_journal import PATHS as BTC_PERP_PATHS, XMR_PATHS

    paths = tuple(Path(p) for p in (journal_paths or XMR_PATHS).values())
    if set(paths) & set(BTC_PERP_PATHS.values()):
        raise ValueError("an XMR shadow must not read the BTC perp journals")
    return paths


def _own(paths: Mapping[str, Path] | None) -> dict[str, Path]:
    from src.dashboard.chart_verdict import DEFAULT_PATH as BTC_VERDICT
    from src.dashboard.orderflow_shadow import DEFAULT_PATH as BTC_SHADOW
    from src.dashboard.plan_opinion import DEFAULT_PATH as BTC_OPINION

    own = {**PATHS, **{k: Path(v) for k, v in (paths or {}).items()}}
    if set(own.values()) & {BTC_VERDICT, BTC_SHADOW, BTC_OPINION}:
        raise ValueError("an XMR shadow must not write a BTC shadow file")
    return own


def update(series: Mapping[str, Sequence[Mapping[str, Any]]], lage: Mapping[str, Any] | None, store: Mapping[str, Any] | None,
           now: datetime | None = None, journal_paths: Mapping[str, Path] | None = None,
           paths: Mapping[str, Path] | None = None) -> dict[str, Any]:
    """Orderflow-Schatten and Chart-Urteil for the XMR plans. Each runs on its own: one failing leaves the other."""
    from src.dashboard import chart_verdict, orderflow_shadow

    journals, own, xmr_lage = _journals(journal_paths), _own(paths), for_symbol(lage)
    status: dict[str, Any] = {"lage": bool(xmr_lage)}
    for name, step in (("orderflow", lambda: orderflow_shadow.update(own["orderflow"], journals, xmr_lage, now, series=series)),
                       ("verdict", lambda: chart_verdict.update(own["verdict"], journals, series, xmr_lage, now, trades=store or None))):
        try:
            result = step()
            status[name] = {"plans": len(result.get("plans") or {})}
        except Exception as error:  # noqa: BLE001 - a shadow must not stop the other one or the runtime
            status[name] = {"error": type(error).__name__}
    return status


def update_opinion(lage: Mapping[str, Any] | None, now: datetime | None = None, ask: Any = None,
                   journal_paths: Mapping[str, Path] | None = None, paths: Mapping[str, Path] | None = None) -> dict[str, Any]:
    """Zweitmeinung for new XMR plans (at most one Hermes call per step, as for BTC), symbol XMRUSDT in the prompt."""
    from src.dashboard import plan_opinion

    return plan_opinion.update(_own(paths)["opinion"], _journals(journal_paths), for_symbol(lage), now, ask=ask, symbol=SYMBOL)


def counts(paths: Mapping[str, Path] | None = None) -> dict[str, int | None]:
    """Plans per shadow file for the XMR journal page; None when the shadow has not written yet."""
    import json

    out: dict[str, int | None] = {}
    for name, path in _own(paths).items():
        try:
            out[name] = len((json.loads(Path(path).read_text(encoding="utf-8")) or {}).get("plans") or {})
        except (OSError, ValueError, AttributeError):
            out[name] = None
    return out
