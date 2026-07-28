from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.orderflow.metrics import OrderflowMetric
from src.research.case_engine import ResearchCase


RULE_VERSION = "1.0.0"
PROVENANCE = "BINANCE_SPOT_AGGTRADE_DETERMINISTIC"


@dataclass(frozen=True, slots=True)
class OrderflowObservation:
    observation_id: str
    kind: str
    symbol: str
    timeframe: str
    observed_at: datetime
    summary: str
    evidence: tuple[dict[str, Any], ...]
    rule_version: str
    input_hash: str
    provenance: str = PROVENANCE
    mode: str = "OBSERVE"

    def to_dict(self) -> dict[str, Any]:
        return {"observation_id":self.observation_id,"kind":self.kind,"symbol":self.symbol,"timeframe":self.timeframe,"observed_at":self.observed_at.isoformat(),"summary":self.summary,"evidence":[dict(item) for item in self.evidence],"rule_version":self.rule_version,"input_hash":self.input_hash,"provenance":self.provenance,"mode":self.mode}


class OrderflowObservationEngine:
    """Describes fixed threshold combinations. It never scores or forecasts."""

    @staticmethod
    def _ratio_at_least(value: Decimal, baseline: Decimal, multiplier: Decimal) -> bool:
        return baseline > 0 and value >= baseline * multiplier

    def evaluate(self, previous: OrderflowMetric, current: OrderflowMetric) -> list[OrderflowObservation]:
        if previous.symbol != current.symbol or previous.window_end != current.window_start:
            raise ValueError("Orderflow observations require adjacent windows for one symbol")
        conditions: list[tuple[str, str, list[tuple[str, bool, Any]], str]] = [
            ("STRONG_BUYER_ACTIVITY", "Aggressive buyer activity increased across the adjacent metric windows.", [("buy_volume_at_least_2x_previous",self._ratio_at_least(current.aggressive_buy_volume,previous.aggressive_buy_volume,Decimal("2")),str(current.aggressive_buy_volume)),("buy_count_at_least_1_5x_previous",self._ratio_at_least(Decimal(current.buy_count),Decimal(previous.buy_count),Decimal("1.5")),current.buy_count)], "buyer_activity"),
            ("STRONG_SELLER_ACTIVITY", "Aggressive seller activity increased across the adjacent metric windows.", [("sell_volume_at_least_2x_previous",self._ratio_at_least(current.aggressive_sell_volume,previous.aggressive_sell_volume,Decimal("2")),str(current.aggressive_sell_volume)),("sell_count_at_least_1_5x_previous",self._ratio_at_least(Decimal(current.sell_count),Decimal(previous.sell_count),Decimal("1.5")),current.sell_count)], "seller_activity"),
            ("RISING_CVD_ACTIVITY", "Cumulative delta rose while aggressive buy count also increased.", [("cumulative_delta_above_previous",current.cumulative_delta>previous.cumulative_delta,str(current.cumulative_delta)),("buy_count_above_previous",current.buy_count>previous.buy_count,current.buy_count)], "cvd_activity"),
            ("FALLING_CVD_ACTIVITY", "Cumulative delta fell while aggressive sell count also increased.", [("cumulative_delta_below_previous",current.cumulative_delta<previous.cumulative_delta,str(current.cumulative_delta)),("sell_count_above_previous",current.sell_count>previous.sell_count,current.sell_count)], "cvd_activity"),
            ("HIGH_TRADE_FREQUENCY", "Trade frequency and volume throughput both increased across adjacent windows.", [("trades_per_second_at_least_2x_previous",self._ratio_at_least(current.trades_per_second,previous.trades_per_second,Decimal("2")),str(current.trades_per_second)),("volume_per_second_at_least_1_5x_previous",self._ratio_at_least(current.volume_per_second,previous.volume_per_second,Decimal("1.5")),str(current.volume_per_second))], "frequency_activity"),
            ("LARGE_INDIVIDUAL_TRADE_ACTIVITY", "The largest trade exceeded both previous and current average-size references.", [("largest_trade_at_least_3x_previous_average",current.largest_trade>=previous.average_trade_size*Decimal("3") and previous.average_trade_size>0,str(current.largest_trade)),("largest_trade_at_least_2x_current_average",current.largest_trade>=current.average_trade_size*Decimal("2") and current.average_trade_size>0,str(current.largest_trade))], "size_activity"),
            ("EXTREME_BUY_RATIO_ACTIVITY", "Buy volume and buy count both exceeded fixed sell-side ratios.", [("buy_sell_volume_ratio_at_least_3",current.buy_sell_ratio is not None and current.buy_sell_ratio>=Decimal("3"),str(current.buy_sell_ratio)),("buy_count_at_least_2x_sell_count",current.sell_count>0 and current.buy_count>=current.sell_count*2,current.buy_count)], "ratio_activity"),
            ("EXTREME_SELL_RATIO_ACTIVITY", "Sell volume and sell count both exceeded fixed buy-side ratios.", [("sell_volume_at_least_3x_buy_volume",current.aggressive_buy_volume>0 and current.aggressive_sell_volume>=current.aggressive_buy_volume*Decimal("3"),str(current.aggressive_sell_volume)),("sell_count_at_least_2x_buy_count",current.buy_count>0 and current.sell_count>=current.buy_count*2,current.sell_count)], "ratio_activity"),
        ]
        output=[]
        for kind,summary,checks,rule_id in conditions:
            if not all(passed for _,passed,_ in checks):continue
            evidence=tuple({"condition":name,"value":value,"previous_source_hash":previous.source_hash,"current_source_hash":current.source_hash} for name,_,value in checks)
            if len(evidence)<2:raise AssertionError("Orderflow observation requires at least two evidence clauses")
            payload={"kind":kind,"rule_id":rule_id,"rule_version":RULE_VERSION,"previous_hash":previous.source_hash,"current_hash":current.source_hash,"evidence":evidence}
            digest=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
            timeframe=f"{int((current.window_end-current.window_start).total_seconds())}s"
            output.append(OrderflowObservation("ofobs_"+digest[:24],kind,current.symbol,timeframe,current.window_end,summary,evidence,RULE_VERSION,digest))
        return output


class OrderflowResearchCaseEngine:
    def create(self, observation: OrderflowObservation) -> ResearchCase:
        case_id="ofcase_"+hashlib.sha256(observation.observation_id.encode()).hexdigest()[:20]
        return ResearchCase(case_id,observation.symbol,observation.timeframe,observation.observed_at,observation.observed_at,observation_ids=[observation.observation_id],evidence=[{"observation_id":observation.observation_id,"kind":observation.kind,"observed_at":observation.observed_at.isoformat(),"input_hash":observation.input_hash,"provenance":observation.provenance,"evidence_count":len(observation.evidence)}],missing_evidence=["subsequent_orderflow_context"],rule_versions={"orderflow":observation.rule_version},documentation="Orderflow research container only; describes an observed metric combination, not a signal, prediction, or setup.")
