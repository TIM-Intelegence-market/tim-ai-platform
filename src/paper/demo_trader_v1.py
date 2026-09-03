from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from src.paper.automation import PaperPolicy, PaperJournalEntry
from src.research.case_engine import ResearchCase

# DEMO TRADER — TEST_ONLY, verknüpft mit Trading-Logik, nie mit Trading-Konto
# Quelle: Hausarbeit 2, CHECKLISTE D1-D6, TIM_CONSTITUTION Band 3, VISION_2030.md
# Jede Zeile: OBSERVE, Provenance=TEST_ONLY, trading_actions=0

DemoSide = Literal["LONG", "SHORT", "FLAT"]


@dataclass(frozen=True, slots=True)
class DemoTrade:
    trade_id: str  # demo_<sha256>
    journal_id: str  # paper_<sha256>
    case_id: str
    side: DemoSide
    entry_price: float
    exit_price: float
    gross: float
    fees: float
    slippage: float
    net: float
    opened_at: datetime
    evaluated_at: datetime
    provenance: str = "TEST_ONLY_DEMO_TRADER_V1"
    limitation: str = "Papier-Bilanz, kein Order, kein Fill, kein Konto."


@dataclass(slots=True)
class DemoPortfolio:
    starting_balance: float = 10000.0
    balance: float = 10000.0
    equity_curve: list[dict] = None  # [{evaluated_at, balance}]
    trades: list[DemoTrade] = None

    def __post_init__(self):
        if self.equity_curve is None:
            self.equity_curve = [{"evaluated_at": datetime.now(timezone.utc).isoformat(), "balance": self.balance, "event": "START"}]
        if self.trades is None:
            self.trades = []

    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        wins = sum(1 for t in self.trades if t.net > 0)
        return wins / len(self.trades)

    def profit_factor(self) -> float:
        gains = sum(t.net for t in self.trades if t.net > 0)
        losses = -sum(t.net for t in self.trades if t.net < 0)
        if losses == 0:
            return float("inf") if gains > 0 else 0.0
        return gains / losses

    def max_drawdown(self) -> float:
        peak = self.starting_balance
        max_dd = 0.0
        for point in self.equity_curve:
            bal = point["balance"]
            if bal > peak:
                peak = bal
            dd = (peak - bal) / peak if peak else 0.0
            if dd > max_dd:
                max_dd = dd
        return max_dd

    def to_dict(self) -> dict:
        return {
            "starting_balance": self.starting_balance,
            "current_balance": round(self.balance, 2),
            "trades": len(self.trades),
            "win_rate": round(self.win_rate(), 4),
            "profit_factor": round(self.profit_factor(), 4) if self.profit_factor() != float("inf") else "inf",
            "max_drawdown": round(self.max_drawdown(), 4),
            "equity_curve": self.equity_curve[-100:],
            "provenance": "TEST_ONLY_DEMO_TRADER_V1",
        }


class DemoTrader:
    """Demo-Trader für Bilanz — Papier, verknüpft mit Research-Cases, nie ausführend.

    Verknüpfung: ResearchCase (CLOSED) → PaperJournalEntry → DemoTrade → DemoPortfolio
    Kein Binance-Order, kein Wallet-Key, kein private Endpoint (grep-Beweis).
    """

    def __init__(self, policy: PaperPolicy, portfolio: DemoPortfolio | None = None, journal_path: Path | None = None) -> None:
        if not policy.test_only:
            raise ValueError("DemoTrader V1 ist TEST_ONLY")
        if not policy.enabled:
            raise PermissionError("PaperPolicy muss enabled=True für Demo")
        self.policy = policy
        self.portfolio = portfolio or DemoPortfolio()
        self.journal_path = journal_path or Path("data/paper/demo_journal.jsonl")
        self._journal_cache: dict[str, PaperJournalEntry] = {}

    def _side_for_case(self, case: ResearchCase) -> DemoSide:
        # Deterministisch aus Evidence: BOS_BULLISH → LONG, BOS_BEARISH → SHORT, sonst FLAT
        kinds = {e.get("kind") if isinstance(e, dict) else getattr(e, "kind", "") for e in case.evidence}
        # evidence in ResearchCase ist List[dict] mit observation kind
        has_bull = any("BOS_BULLISH" in str(k) for k in kinds)
        has_bear = any("BOS_BEARISH" in str(k) for k in kinds)
        if has_bull and not has_bear:
            return "LONG"
        if has_bear and not has_bull:
            return "SHORT"
        return "FLAT"

    def evaluate(self, case: ResearchCase, evaluated_at: datetime, start_price: float, end_price: float) -> DemoTrade | None:
        """Erzeuge Demo-Trade für geschlossenen Case — gibt None bei FLAT zurück (kein Trade)."""
        if case.status != "CLOSED" or case.outcome is None:
            raise ValueError("Case muss CLOSED mit outcome sein")
        if evaluated_at < case.updated_at + self.policy.evaluation_delay:
            raise ValueError("evaluation_delay 15m nicht erreicht")
        if start_price <= 0 or end_price <= 0:
            raise ValueError("Preise >0 nötig")

        side = self._side_for_case(case)
        if side == "FLAT":
            return None

        # Paper-Journal als Basis (gleiche Formel wie paper/automation.py:63-66)
        identity = f"{case.case_id}|{self.policy.policy_id}|{evaluated_at.isoformat()}"
        journal_id = "paper_" + hashlib.sha256(identity.encode()).hexdigest()[:20]
        trade_id = "demo_" + hashlib.sha256((journal_id + side).encode()).hexdigest()[:20]

        # Idempotenz: schon gebucht?
        for t in self.portfolio.trades:
            if t.trade_id == trade_id:
                return t

        gross = end_price / start_price - 1
        if side == "SHORT":
            gross = -gross
        fees = self.policy.fee_bps * 2 / 10_000
        slippage = self.policy.slippage_bps * 2 / 10_000
        net = gross - fees - slippage

        # Bilanz: net auf Portfolio
        self.portfolio.balance *= (1 + net)
        self.portfolio.equity_curve.append({"evaluated_at": evaluated_at.isoformat(), "balance": round(self.portfolio.balance, 2), "case_id": case.case_id, "side": side, "net": round(net, 6)})

        trade = DemoTrade(
            trade_id=trade_id,
            journal_id=journal_id,
            case_id=case.case_id,
            side=side,
            entry_price=start_price,
            exit_price=end_price,
            gross=round(gross, 6),
            fees=round(fees, 6),
            slippage=round(slippage, 6),
            net=round(net, 6),
            opened_at=case.opened_at,
            evaluated_at=evaluated_at,
        )
        self.portfolio.trades.append(trade)
        self._persist(trade)
        return trade

    def _persist(self, trade: DemoTrade) -> None:
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        # 0600 via umask, atomic append
        with self.journal_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(trade), default=str, sort_keys=True) + "\n")

    def export_bilanz(self, path: Path | None = None) -> Path:
        out = path or Path(f"data/paper/demo_bilanz_{datetime.now(timezone.utc).date().isoformat()}.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "policy": asdict(self.policy),
            "portfolio": self.portfolio.to_dict(),
            "trades": [asdict(t) for t in self.portfolio.trades[-200:]],
            "provenance": "TEST_ONLY_DEMO_TRADER_V1",
            "limitation": "Papier-Bilanz, verknüpft mit Trading-Logik, nie ausgeführt.",
        }
        out.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
        return out
