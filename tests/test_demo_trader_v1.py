from datetime import datetime, timedelta, timezone
from src.paper.automation import PaperPolicy
from src.paper.demo_trader_v1 import DemoTrader, DemoPortfolio

def _case(closed=True):
    from src.research.case_engine import ResearchCase
    now = datetime.now(timezone.utc)
    c = ResearchCase(case_id="case_test", symbol="BTCUSDT", timeframe="1m", opened_at=now - timedelta(hours=1), updated_at=now - timedelta(minutes=20), status="CLOSED" if closed else "OPEN", outcome="documented" if closed else None, evidence=[{"kind":"BOS_BULLISH","observation_id":"obs1"}])
    # ensure evidence triggers LONG
    c.evidence = [{"kind":"BOS_BULLISH"}]
    return c

def test_demo_trader_long_generates_trade():
    policy = PaperPolicy(policy_id="demo_v1", enabled=True, test_only=True)
    trader = DemoTrader(policy, DemoPortfolio(starting_balance=10000))
    case = _case()
    evaluated_at = case.updated_at + timedelta(minutes=15) + timedelta(seconds=1)
    trade = trader.evaluate(case, evaluated_at, 100.0, 102.0)
    assert trade is not None
    assert trade.side == "LONG"
    assert trade.journal_id.startswith("paper_")
    assert trade.trade_id.startswith("demo_")
    # gross 0.02, fees 0.0012, slippage 0.0004, net ~0.0184
    assert 0.018 < trade.net < 0.019
    assert trader.portfolio.balance > 10000
    exported = trader.export_bilanz()
    assert exported.exists()

def test_demo_trader_flat_no_trade():
    policy = PaperPolicy(policy_id="demo_v1", enabled=True, test_only=True)
    trader = DemoTrader(policy, DemoPortfolio())
    case = _case()
    case.evidence = [{"kind":"REJECTION"}]  # FLAT
    evaluated_at = case.updated_at + timedelta(minutes=16)
    assert trader.evaluate(case, evaluated_at, 100, 101) is None
    assert len(trader.portfolio.trades) == 0

def test_demo_trader_idempotent():
    policy = PaperPolicy(policy_id="demo_v1", enabled=True, test_only=True)
    trader = DemoTrader(policy, DemoPortfolio())
    case = _case()
    evaluated_at = case.updated_at + timedelta(minutes=16)
    t1 = trader.evaluate(case, evaluated_at, 100, 101)
    t2 = trader.evaluate(case, evaluated_at, 100, 101)
    assert t1.trade_id == t2.trade_id
    assert len(trader.portfolio.trades) == 1
