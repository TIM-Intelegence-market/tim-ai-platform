"""V2.8 paper trading: isolated fake execution adapter, kill switch, reconciliation, isolation proof.

Paper only. No module in this package may import network, process or database code or any TIM module outside
this package; ``isolation.scan()`` checks that on every replay and in the tests.
"""
from .adapter import AdapterConfig, FakeExecutionAdapter
from .kill_switch import KillLimits, KillSwitch
from .models import Bar, CostModel, OrderRequest, OrderStatus, OrderType, Side
from .reconcile import reconcile

__all__ = [
    "AdapterConfig", "Bar", "CostModel", "FakeExecutionAdapter", "KillLimits", "KillSwitch", "OrderRequest",
    "OrderStatus", "OrderType", "Side", "reconcile",
]
