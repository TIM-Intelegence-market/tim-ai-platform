from __future__ import annotations

from typing import Protocol


class ReadOnlyMarketSource(Protocol):
    async def recent_candles(self,symbol:str,timeframe:str,limit:int=200)->list: ...
    async def recent_observations(self,symbol:str,limit:int=100)->list: ...


class ExternalSearchDisabled(RuntimeError):pass


def duckduckgo_search(*_:object,enabled:bool=False,**__:object)->list[dict]:
    """Explicit gate: network research is disabled unless separately authorized."""
    if not enabled:raise ExternalSearchDisabled("External research is disabled; no authorized source policy is configured")
    raise ExternalSearchDisabled("No external search connector is installed")


async def database_evidence(repository:ReadOnlyMarketSource,symbol:str,timeframe:str,limit:int=200)->dict:
    candles=await repository.recent_candles(symbol,timeframe,limit)
    observations=await repository.recent_observations(symbol,limit)
    return {"candles":candles,"observations":observations,"read_only":True}
