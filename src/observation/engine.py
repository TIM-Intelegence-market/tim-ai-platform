from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Sequence
from uuid import NAMESPACE_URL, uuid5

from src.analysis.bos_detector import BOSDetector
from src.analysis.bronxc_rules import BroncxRules
from src.models.market_data import Candle, Observation

OBSERVATION_VERSION = 1
RULE_VERSIONS = {"bos": "1.0.0", "bronxc": "1.0.0"}


def candle_input_hash(candles: Sequence[Candle]) -> str:
    payload = [[item.symbol, item.timeframe, item.open_time.isoformat(), item.close_time.isoformat(), item.open, item.high, item.low, item.close, item.volume, item.trade_count, item.closed] for item in candles]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":"), sort_keys=False).encode()).hexdigest()


class ObservationEngine:
    """Central deterministic event layer. It enriches rules; it never infers values."""

    def __init__(self, bos: BOSDetector | None = None, bronxc: BroncxRules | None = None) -> None:
        self.bos = bos or BOSDetector()
        self.bronxc = bronxc or BroncxRules()
        self._seen: set[str] = set()

    def evaluate(self, candles: Sequence[Candle]) -> list[Observation]:
        if not candles:
            return []
        digest = candle_input_hash(candles)
        raw: list[tuple[str, Observation]] = []
        bos = self.bos.detect(candles)
        if bos is not None:
            raw.append(("bos", bos))
        raw.extend(("bronxc", item) for item in self.bronxc.evaluate(candles))
        output: list[Observation] = []
        for rule_id, item in raw:
            identity = f"tim:{OBSERVATION_VERSION}:{rule_id}:{RULE_VERSIONS[rule_id]}:{item.kind.value}:{item.symbol}:{item.timeframe}:{item.observed_at.isoformat()}:{digest}"
            stable_id = uuid5(NAMESPACE_URL, identity)
            if str(stable_id) in self._seen:
                continue
            self._seen.add(str(stable_id))
            output.append(replace(item, observation_id=stable_id, observation_version=OBSERVATION_VERSION, rule_id=rule_id, rule_version=RULE_VERSIONS[rule_id], input_hash=digest, source="observation_engine", provenance="PUBLIC_MARKET_DATA_DETERMINISTIC"))
        return output

    def restore_seen(self, observation_ids: Sequence[str]) -> None:
        self._seen.update(str(item) for item in observation_ids)
