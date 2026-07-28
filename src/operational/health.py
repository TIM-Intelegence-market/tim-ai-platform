from __future__ import annotations
import asyncio,json
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
from urllib.request import urlopen
import asyncpg

class HealthChecker:
    def __init__(self,database_url:str,dashboard_url:str="http://127.0.0.1:8765/")->None:self.database_url=database_url;self.dashboard_url=dashboard_url
    async def database(self)->dict[str,Any]:
        started=asyncio.get_running_loop().time()
        connection=None
        try:
            connection=await asyncpg.connect(self.database_url,timeout=3);value=await connection.fetchval("SELECT 1");return {"status":"HEALTHY","query":value,"latency_ms":round((asyncio.get_running_loop().time()-started)*1000,2)}
        except Exception as exc:return {"status":"UNAVAILABLE","error":f"{type(exc).__name__}: {exc}","latency_ms":round((asyncio.get_running_loop().time()-started)*1000,2)}
        finally:
            if connection is not None:
                await connection.close()
    async def dashboard(self)->dict[str,Any]:
        def probe():
            started=datetime.now(timezone.utc)
            try:
                with urlopen(self.dashboard_url,timeout=3) as response:return {"status":"HEALTHY" if response.status==200 else "DEGRADED","http_status":response.status,"latency_ms":round((datetime.now(timezone.utc)-started).total_seconds()*1000,2)}
            except Exception as exc:return {"status":"UNAVAILABLE","error":f"{type(exc).__name__}: {exc}","latency_ms":round((datetime.now(timezone.utc)-started).total_seconds()*1000,2)}
        return await asyncio.to_thread(probe)
    @staticmethod
    def files(required:list[Path])->dict[str,Any]:
        missing=[str(path) for path in required if not path.exists()];return {"status":"HEALTHY" if not missing else "DEGRADED","missing":missing}
