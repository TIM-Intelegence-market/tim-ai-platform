from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Iterable

from src.models.market_data import Trade
from src.research.case_engine import ResearchCase


VALIDATION_VERSION="1.0.0"
HORIZONS=(5,15,30)
SIDEWAYS_THRESHOLD_PERCENT=Decimal("0.10")


def _d(value:float|int|str|Decimal)->Decimal:return value if isinstance(value,Decimal) else Decimal(str(value))
def _s(value:Decimal)->str:return "0" if value==0 else format(value.normalize(),"f")


@dataclass(frozen=True,slots=True)
class HorizonResult:
    minutes:int;target_at:datetime;price:Decimal;price_change_percent:Decimal;net_delta:Decimal;trade_count:int;source_hash:str
    def to_dict(self)->dict[str,Any]:return {"minutes":self.minutes,"target_at":self.target_at.isoformat(),"price":_s(self.price),"price_change_percent":_s(self.price_change_percent),"net_delta":_s(self.net_delta),"trade_count":self.trade_count,"source_hash":self.source_hash}


@dataclass(frozen=True,slots=True)
class OrderflowValidation:
    observation_id:str;symbol:str;observed_at:datetime;baseline_price:Decimal;horizons:tuple[HorizonResult,...];complete:bool;outcome:str|None;validation_hash:str;validated_through:datetime;validation_version:str=VALIDATION_VERSION;mode:str="OBSERVE"
    def to_dict(self)->dict[str,Any]:return {"observation_id":self.observation_id,"symbol":self.symbol,"observed_at":self.observed_at.isoformat(),"baseline_price":_s(self.baseline_price),"horizons":[item.to_dict() for item in self.horizons],"complete":self.complete,"outcome":self.outcome,"validation_hash":self.validation_hash,"validated_through":self.validated_through.isoformat(),"validation_version":self.validation_version,"mode":self.mode}


class OrderflowValidationEngine:
    """Documents subsequent outcomes from persisted trades; never predicts them."""
    def validate(self,observation:dict[str,Any],trades:Iterable[Trade],as_of:datetime)->OrderflowValidation|None:
        observed_at=datetime.fromisoformat(str(observation["observed_at"]).replace("Z","+00:00"))
        if observed_at.tzinfo is None or as_of.tzinfo is None:raise ValueError("Validation timestamps must be timezone-aware")
        ordered=sorted(
            (item for item in trades if item.event_time<=as_of),
            key=lambda item:(item.event_time,item.trade_id if item.trade_id is not None else -1),
        )
        identities=[(item.symbol,item.trade_id) for item in ordered]
        if len(identities)!=len(set(identities)):raise ValueError("Duplicate aggTrade in validation input")
        symbol=str(observation["symbol"])
        if any(item.symbol!=symbol for item in ordered):raise ValueError("Validation input cannot mix symbols")
        baseline_candidates=[item for item in ordered if item.event_time<=observed_at]
        if not baseline_candidates:return None
        baseline=baseline_candidates[-1];baseline_price=_d(baseline.price);results=[]
        for minutes in HORIZONS:
            target=observed_at+timedelta(minutes=minutes)
            if target>as_of:continue
            subsequent=[item for item in ordered if observed_at<item.event_time<=target]
            if not subsequent:continue
            price=_d(subsequent[-1].price);change=(price-baseline_price)/baseline_price*Decimal("100")
            buy=sum((_d(item.quantity) for item in subsequent if item.buyer_is_maker is False),Decimal("0"));sell=sum((_d(item.quantity) for item in subsequent if item.buyer_is_maker is True),Decimal("0"))
            canonical=[[item.symbol,item.trade_id,item.event_time.isoformat(),str(item.price),str(item.quantity),item.buyer_is_maker] for item in subsequent]
            digest=hashlib.sha256(json.dumps({"observation_hash":observation["input_hash"],"minutes":minutes,"trades":canonical},separators=(",",":"),sort_keys=True).encode()).hexdigest()
            results.append(HorizonResult(minutes,target,price,change,buy-sell,len(subsequent),digest))
        returned_horizons={item.minutes for item in results}
        sequence_complete=all(
            left.trade_id is not None
            and right.trade_id is not None
            and right.trade_id==left.trade_id+1
            for left,right in zip(ordered,ordered[1:])
        )
        complete=set(HORIZONS).issubset(returned_horizons) and sequence_complete;outcome=None
        if complete:
            final=next(item for item in results if item.minutes==30)
            outcome="PRICE_INCREASED" if final.price_change_percent>SIDEWAYS_THRESHOLD_PERCENT else "PRICE_DECREASED" if final.price_change_percent<-SIDEWAYS_THRESHOLD_PERCENT else "PRICE_SIDEWAYS"
        if not results:return None
        payload={"observation_id":observation["observation_id"],"version":VALIDATION_VERSION,"baseline_price":_s(baseline_price),"horizons":[item.to_dict() for item in results],"outcome":outcome}
        digest=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        return OrderflowValidation(str(observation["observation_id"]),symbol,observed_at,baseline_price,tuple(results),complete,outcome,digest,results[-1].target_at)

    @staticmethod
    def apply_to_case(validation:OrderflowValidation,case:ResearchCase)->ResearchCase:
        if validation.complete:
            case.status="CLOSED";case.outcome=validation.outcome;case.updated_at=validation.validated_through;case.missing_evidence=[]
            case.evidence.append({"kind":"ORDERFLOW_OUTCOME","validated_through":validation.validated_through.isoformat(),"validation_hash":validation.validation_hash,"outcome":validation.outcome})
        return case
