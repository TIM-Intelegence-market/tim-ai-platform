from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import settings
from src.data_ingestion.binance_ws import BinanceTradeStream


async def main() -> None:
    url = f"{settings.binance_ws_url.rstrip('/')}/{settings.symbol.lower()}@aggTrade"
    async with websockets.connect(url, open_timeout=10, close_timeout=3) as socket:
        trade = BinanceTradeStream.parse_message(await asyncio.wait_for(socket.recv(), timeout=10))
    print(json.dumps({"symbol": trade.symbol, "price_positive": trade.price > 0, "quantity_positive": trade.quantity > 0, "trade_id": trade.trade_id, "event_time": trade.event_time.isoformat()}))


if __name__ == "__main__":
    asyncio.run(main())
