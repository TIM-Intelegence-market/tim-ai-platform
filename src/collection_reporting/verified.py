"""Prospective bounded market-data evidence, isolated from the legacy database.

SQLite is the collection's durable journal and raw/outbox/candle store. It has
no order API, no PostgreSQL write connection and no catch-up/recovery client.
Processing uses TIM's existing CandleAggregator; it does not claim downstream
research/observation processing or closed coverage for boundary candles.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.data_ingestion.aggregator import CandleAggregator
from src.models.market_data import Trade

SOURCE = "BINANCE_SPOT_AGGTRADE"
WORKER = "COLLECTION_CANDLE_V1"
TIMEFRAMES = ("1m", "5m", "15m", "1h")
STATUSES = ("PENDING", "PROCESSING", "RETRY", "QUARANTINED", "COMPLETED")
LEGACY_WARNING = "Legacy historical ingress evidence is incomplete."


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def raw_bytes(value: str | bytes) -> bytes:
    return value.encode() if isinstance(value, str) else value


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


class CollectionStop(RuntimeError):
    pass


def parse_trade(raw: str, symbol: str, received_at: str) -> tuple[Trade, dict]:
    payload = json.loads(raw)
    if not isinstance(payload, dict) or payload.get("e") != "aggTrade" or payload.get("s") != symbol:
        raise ValueError("WRONG_SOURCE_EVENT_OR_SYMBOL")
    if any(type(payload.get(k)) is not int or payload[k] < 0 for k in ("a", "T", "E")):
        raise ValueError("INVALID_ID_OR_TIMESTAMP")
    if type(payload.get("m")) is not bool:
        raise ValueError("INVALID_MAKER_FLAG")
    price, quantity = float(payload["p"]), float(payload["q"])
    if not all(math.isfinite(v) and v > 0 for v in (price, quantity)):
        raise ValueError("INVALID_PRICE_OR_QUANTITY")
    event_time = datetime.fromtimestamp(payload["T"] / 1000, timezone.utc)
    received = datetime.fromisoformat(received_at)
    if received.tzinfo is None:
        raise ValueError("NAIVE_RECEIPT_TIMESTAMP")
    if (event_time - received).total_seconds() > 5:
        raise ValueError("FUTURE_SOURCE_TIMESTAMP")
    return Trade(symbol, price, quantity, event_time, payload["a"], payload["m"]), payload


def trade_data(trade: Trade) -> dict:
    return {**asdict(trade), "event_time": trade.event_time.isoformat()}


def load_trade(data: str) -> Trade:
    value = json.loads(data)
    value["event_time"] = datetime.fromisoformat(value["event_time"])
    return Trade(**value)


def candle_output(aggregator: CandleAggregator, trade: Trade) -> dict:
    closed = aggregator.add_trade(trade)
    return {"worker": WORKER, "event_id": trade.trade_id,
            "closed": [asdict(c) for c in closed],
            "active": [asdict(c) for c in aggregator.snapshots()],
            "trading_actions": 0, "live_trading": False}


class VerifiedJournal:
    def __init__(self, path: Path, contract: dict | None = None):
        self.path = path
        if contract is None and not path.exists():
            raise CollectionStop("journal does not exist")
        if contract is not None:
            if path.exists():
                raise CollectionStop("refusing to replace an existing collection")
            if (type(contract.get("max_events")) is not int or not 1 <= contract["max_events"] <= 10000
                    or not 1 <= contract.get("max_duration_seconds", 0) <= 300
                    or contract.get("live_trading") is not False or contract.get("trading_actions") != 0
                    or contract.get("source") != SOURCE or contract.get("symbol") != "BTCUSDT"):
                raise CollectionStop("invalid bounded observe-only contract")
            path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA foreign_keys=ON")
        if contract is not None:
            self.db.executescript("""
                CREATE TABLE control(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE receipts(
                    seq INTEGER PRIMARY KEY, collection_id TEXT NOT NULL, source TEXT NOT NULL,
                    symbol TEXT NOT NULL, event_id INTEGER, received_at TEXT NOT NULL,
                    source_timestamp TEXT, raw_payload_hash TEXT NOT NULL, raw_payload TEXT NOT NULL,
                    validation_result TEXT NOT NULL DEFAULT 'UNCLASSIFIED', disposition TEXT NOT NULL DEFAULT 'UNKNOWN',
                    rejection_reason TEXT, durable_record_id TEXT, prev_hash TEXT NOT NULL, entry_hash TEXT NOT NULL);
                CREATE TABLE events(event_id INTEGER PRIMARY KEY, receipt_seq INTEGER UNIQUE NOT NULL REFERENCES receipts(seq),
                    trade_json TEXT NOT NULL, input_hash TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('PENDING','PROCESSING','RETRY','QUARANTINED','COMPLETED')),
                    output_hash TEXT, completed_at TEXT, error TEXT);
                CREATE TABLE candles(timeframe TEXT NOT NULL,open_time TEXT NOT NULL,payload TEXT NOT NULL,
                    PRIMARY KEY(timeframe,open_time));
                CREATE TABLE telemetry(seq INTEGER PRIMARY KEY,measured_at TEXT NOT NULL,payload TEXT NOT NULL);
            """)
            with self.db:
                self._set("contract", contract)
                self._set("state", "PREPARED")
                self._set("session_started", False)
                self._set("application_received", 0)
                self._set("gaps", [])
                self._set("stop_reason", None)
        self.contract = self.get("contract")
        if contract is None and self.get("state") in {"OPEN", "DRAINING"}:
            self.stop("UNCLEAN_SESSION_REQUIRES_AUDIT", safe=True)
        self.aggregator = CandleAggregator(TIMEFRAMES)
        # Resume processing only. Never reopen an existing network session.
        for row in self.db.execute("SELECT * FROM events WHERE status='COMPLETED' ORDER BY receipt_seq"):
            output = candle_output(self.aggregator, load_trade(row["trade_json"]))
            if digest(output) != row["output_hash"]:
                raise CollectionStop("completed output replay mismatch")

    def close(self):
        self.db.close()

    def _set(self, key: str, value: Any):
        self.db.execute("INSERT INTO control VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, canonical(value)))

    def get(self, key: str):
        row = self.db.execute("SELECT value FROM control WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def begin(self, at: str | None = None):
        if self.get("session_started") or self.get("state") != "PREPARED":
            raise CollectionStop("network session cannot be resumed or duplicated")
        with self.db:
            self._set("session_started", True)
            self._set("started_at", at or utc())
            self._set("state", "OPEN")

    def stop(self, reason: str, *, safe: bool = False):
        with self.db:
            if self.get("state") != "SAFE_STOP":
                self._set("state", "SAFE_STOP" if safe else "DRAINING")
                self._set("stop_reason", reason)
            self._set("ended_at", utc())

    def receive(self, raw: str | bytes, at: str | None = None) -> int:
        """Commit the exact message BEFORE parsing/disposition. Never skip errors."""
        if self.get("state") != "OPEN":
            raise CollectionStop("collection is not open for receipt assignment")
        n = self.db.execute("SELECT count(*) FROM receipts").fetchone()[0]
        if n >= self.contract["max_events"]:
            self.stop("MAX_EVENTS")
            raise CollectionStop("hard max_events reached")
        received_at = at or utc()
        # Binance's public feed uses text. Binary bytes are stored reversibly.
        raw_text = raw
        seq = n + 1
        previous = self.db.execute("SELECT entry_hash FROM receipts ORDER BY seq DESC LIMIT 1").fetchone()
        previous_hash = previous[0] if previous else digest(self.contract)
        raw_hash = hashlib.sha256(raw_bytes(raw_text)).hexdigest()
        material = [seq, self.contract["collection_id"], SOURCE, self.contract["symbol"], received_at, raw_hash, previous_hash]
        with self.db:
            self.db.execute("""INSERT INTO receipts(seq,collection_id,source,symbol,received_at,raw_payload_hash,
                raw_payload,prev_hash,entry_hash) VALUES(?,?,?,?,?,?,?,?,?)""",
                (seq, self.contract["collection_id"], SOURCE, self.contract["symbol"], received_at,
                 raw_hash, raw_text, previous_hash, digest(material)))
            self._set("application_received", seq)
        return seq

    def classify(self, seq: int):
        row = self.db.execute("SELECT * FROM receipts WHERE seq=?", (seq,)).fetchone()
        if row is None:
            self.stop("MISSING_RECEIPT", safe=True)
            raise CollectionStop("missing receipt")
        if row["disposition"] != "UNKNOWN":
            return row["disposition"]
        reason, trade, payload = None, None, None
        try:
            trade, payload = parse_trade(row["raw_payload"], self.contract["symbol"], row["received_at"])
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            reason = f"VALIDATION:{type(exc).__name__}:{str(exc)[:100]}"
        disposition, durable_id = "REJECTED", None
        if trade is not None:
            record = self.db.execute("SELECT * FROM events WHERE event_id=?", (trade.trade_id,)).fetchone()
            if record is not None:
                if record["input_hash"] == digest(trade_data(trade)):
                    disposition, durable_id = "DUPLICATE", f"{self.contract['collection_id']}:{trade.trade_id}"
                else:
                    reason = "CONFLICTING_EVENT_ID"
            else:
                last = self.db.execute("SELECT max(event_id) FROM events").fetchone()[0]
                if last is not None and trade.trade_id <= last:
                    reason = "OUT_OF_ORDER_EVENT_ID"
                else:
                    disposition, durable_id = "ACCEPTED", f"{self.contract['collection_id']}:{trade.trade_id}"
        observed_id = trade.trade_id if trade else None
        observed_time = trade.event_time.isoformat() if trade else None
        if trade is None:
            try:
                invalid_payload = json.loads(row["raw_payload"])
                if isinstance(invalid_payload, dict) and type(invalid_payload.get("a")) is int:
                    observed_id = invalid_payload["a"]
                if isinstance(invalid_payload, dict) and type(invalid_payload.get("T")) is int:
                    observed_time = datetime.fromtimestamp(invalid_payload["T"] / 1000, timezone.utc).isoformat()
            except (ValueError, TypeError, OverflowError):
                pass
        with self.db:
            if disposition == "ACCEPTED":
                if last is not None and trade.trade_id != last + 1:
                    gaps = self.get("gaps")
                    gaps.append({"missing_from_id": last + 1, "missing_to_id": trade.trade_id - 1})
                    self._set("gaps", gaps)
                self.db.execute("INSERT INTO events(event_id,receipt_seq,trade_json,input_hash,status) VALUES(?,?,?,?, 'PENDING')",
                    (trade.trade_id, seq, canonical(trade_data(trade)), digest(trade_data(trade))))
            self.db.execute("""UPDATE receipts SET event_id=?,source_timestamp=?,validation_result=?,
                disposition=?,rejection_reason=?,durable_record_id=? WHERE seq=?""",
                (observed_id, observed_time,
                 "VALID" if trade else "INVALID", disposition, reason, durable_id, seq))
        if self.get("gaps") or reason in {"CONFLICTING_EVENT_ID", "OUT_OF_ORDER_EVENT_ID"}:
            self.stop(reason or "INTRA_COLLECTION_GAP", safe=True)
        return disposition

    def drain(self):
        """Atomically store candle outputs and per-event completion evidence."""
        for row in self.db.execute("SELECT * FROM events WHERE status='PENDING' ORDER BY receipt_seq").fetchall():
            with self.db:
                self.db.execute("UPDATE events SET status='PROCESSING' WHERE event_id=?", (row["event_id"],))
            try:
                output = candle_output(self.aggregator, load_trade(row["trade_json"]))
                with self.db:
                    for candle in output["closed"] + output["active"]:
                        self.db.execute("INSERT INTO candles VALUES(?,?,?) ON CONFLICT(timeframe,open_time) DO UPDATE SET payload=excluded.payload",
                            (candle["timeframe"], str(candle["open_time"]), canonical(candle)))
                    self.db.execute("UPDATE events SET status='COMPLETED',output_hash=?,completed_at=? WHERE event_id=?",
                        (digest(output), utc(), row["event_id"]))
            except Exception as exc:
                with self.db:
                    self.db.execute("UPDATE events SET status='QUARANTINED',error=? WHERE event_id=?",
                        (type(exc).__name__, row["event_id"]))
                self.stop("PROCESSOR_FAILURE", safe=True)
                raise CollectionStop("processor failed") from exc

    def counts(self):
        dispositions = {k: 0 for k in ("ACCEPTED", "DUPLICATE", "REJECTED", "UNKNOWN")}
        dispositions.update({r[0]: r[1] for r in self.db.execute("SELECT disposition,count(*) FROM receipts GROUP BY disposition")})
        statuses = {s: 0 for s in STATUSES}
        statuses.update({r[0]: r[1] for r in self.db.execute("SELECT status,count(*) FROM events GROUP BY status")})
        return {"received": sum(dispositions.values()), "accepted_unique": dispositions["ACCEPTED"],
                "duplicates": dispositions["DUPLICATE"], "rejected": dispositions["REJECTED"],
                "unknown": dispositions["UNKNOWN"], "statuses": statuses}

    def finish(self, application_received: int):
        with self.db:
            self._set("application_received", application_received)
        self.drain()
        c = self.counts()
        healthy = (c["received"] > 0 and c["unknown"] == 0 and c["received"] == application_received
                   and c["accepted_unique"] > 0 and c["accepted_unique"] == c["statuses"]["COMPLETED"]
                   and not self.get("gaps") and self.get("state") == "DRAINING"
                   and self.get("stop_reason") in {"MAX_EVENTS", "DURATION"}
                   and (self.get("stop_reason") != "MAX_EVENTS" or c["received"] == self.contract["max_events"]))
        with self.db:
            self._set("state", "CLOSED" if healthy else "SAFE_STOP")
            self._set("closed_at", utc())
        return healthy

    def record_telemetry(self, data: dict):
        with self.db:
            self.db.execute("INSERT INTO telemetry(measured_at,payload) VALUES(?,?)", (utc(), canonical(data)))

    def verify(self) -> dict:
        receipts = self.db.execute("SELECT * FROM receipts ORDER BY seq").fetchall()
        events = self.db.execute("SELECT * FROM events ORDER BY receipt_seq").fetchall()
        by_id = {e["event_id"]: e for e in events}
        previous, chain_ok, lineage_ok = digest(self.contract), True, True
        accepted, references = set(), set()
        for i, r in enumerate(receipts, 1):
            material = [i, self.contract["collection_id"], SOURCE, self.contract["symbol"], r["received_at"], r["raw_payload_hash"], previous]
            chain_ok &= (r["seq"] == i and r["collection_id"] == self.contract["collection_id"] and r["source"] == SOURCE
                         and r["symbol"] == self.contract["symbol"] and r["prev_hash"] == previous
                         and hashlib.sha256(raw_bytes(r["raw_payload"])).hexdigest() == r["raw_payload_hash"]
                         and digest(material) == r["entry_hash"])
            previous = r["entry_hash"]
            if r["disposition"] in {"ACCEPTED", "DUPLICATE"}:
                try:
                    t, _ = parse_trade(r["raw_payload"], self.contract["symbol"], r["received_at"])
                    record = by_id.get(r["event_id"])
                    lineage_ok &= (record is not None and t.trade_id == r["event_id"]
                        and r["durable_record_id"] == f"{self.contract['collection_id']}:{t.trade_id}"
                        and record["input_hash"] == digest(trade_data(t)) and record["trade_json"] == canonical(trade_data(t))
                        and r["validation_result"] == "VALID" and r["source_timestamp"] == t.event_time.isoformat()
                        and r["rejection_reason"] is None)
                    if r["disposition"] == "ACCEPTED":
                        lineage_ok &= t.trade_id not in accepted and record is not None and record["receipt_seq"] == r["seq"]
                        accepted.add(t.trade_id)
                    else:
                        lineage_ok &= t.trade_id in accepted
                    references.add(t.trade_id)
                except (ValueError, TypeError, KeyError):
                    lineage_ok = False
            elif r["disposition"] == "REJECTED":
                lineage_ok &= bool(r["rejection_reason"]) and r["durable_record_id"] is None
                try:
                    t, _ = parse_trade(r["raw_payload"], self.contract["symbol"], r["received_at"])
                    conflict = t.trade_id in accepted and by_id[t.trade_id]["input_hash"] != digest(trade_data(t))
                    out_of_order = bool(accepted) and t.trade_id < max(accepted) and t.trade_id not in accepted
                    lineage_ok &= (r["validation_result"] == "VALID" and
                        ((conflict and r["rejection_reason"] == "CONFLICTING_EVENT_ID") or
                         (out_of_order and r["rejection_reason"] == "OUT_OF_ORDER_EVENT_ID")))
                except (ValueError, TypeError, KeyError, OverflowError):
                    lineage_ok &= r["validation_result"] == "INVALID" and r["rejection_reason"].startswith("VALIDATION:")
            else:
                lineage_ok = False
        replay = CandleAggregator(TIMEFRAMES)
        replay_ok = True
        outputs = []
        expected_candles = {}
        try:
            for e in events:
                output = candle_output(replay, load_trade(e["trade_json"]))
                for candle in output["closed"] + output["active"]:
                    expected_candles[(candle["timeframe"], str(candle["open_time"]))] = canonical(candle)
                hashed = digest(output)
                replay_ok &= (e["status"] == "COMPLETED" and e["completed_at"] is not None and e["output_hash"] == hashed)
                outputs.append(hashed)
        except (ValueError, TypeError, KeyError):
            replay_ok = False
        stored_candles = {(r["timeframe"], r["open_time"]): r["payload"] for r in self.db.execute("SELECT * FROM candles")}
        replay_ok &= expected_candles == stored_candles
        c = self.counts()
        boundary_ok = (0 < c["received"] <= self.contract["max_events"]
                       and c["received"] == self.get("application_received"))
        counts_ok = (chain_ok and lineage_ok and boundary_ok and c["unknown"] == 0
                     and c["received"] == c["accepted_unique"] + c["duplicates"] + c["rejected"])
        event_ids = {e["event_id"] for e in events}
        processing_ok = (counts_ok and replay_ok and accepted == event_ids and len(accepted) > 0
                         and c["accepted_unique"] == sum(c["statuses"].values())
                         and c["accepted_unique"] == c["statuses"]["COMPLETED"])
        return {"counts": c, "journal_chain_valid": bool(chain_ok), "lineage_valid": bool(lineage_ok),
            "hard_boundary_valid": bool(boundary_ok), "COUNTS_ACCOUNTED": "PASS" if counts_ok else "FAIL",
            "ALL_UNIQUE_EVENTS_PROCESSED": "PASS" if processing_ok else "FAIL",
            "DETERMINISM": "PASS" if replay_ok and processing_ok else "FAIL",
            "journal_hash": previous, "processing_hash": digest(outputs),
            "cursor": {"first_event_id": min(event_ids) if event_ids else None,
                "last_event_id": max(event_ids) if event_ids else None,
                "hash": digest(sorted(event_ids)), "scope": self.contract["collection_id"]}}


def bounded_live_gate(checks: dict) -> dict:
    required = ("runtime_stable", "queue_clean", "cursor_valid", "journal_active",
                "hard_boundary_active", "automatic_stops_active", "tests_passed",
                "trading_disabled", "legacy_stream_disabled", "single_collector", "repair_readiness_passed")
    blockers = [name for name in required if checks.get(name) is not True]
    return {"SAFE_TO_ENABLE_BOUNDED_LIVE_INGESTION": "NO" if blockers else "YES",
            "checks": checks, "blockers": blockers,
            "legacy_evidence_is_separate": True, "unbounded_live_authorized": False}


def build_verified_report(journal: VerifiedJournal, legacy: dict) -> dict:
    proof = journal.verify()
    healthy = (journal.get("state") == "CLOSED" and proof["COUNTS_ACCOUNTED"] == "PASS"
               and proof["ALL_UNIQUE_EVENTS_PROCESSED"] == "PASS" and proof["DETERMINISM"] == "PASS"
               and not journal.get("gaps"))
    quality = "PASS" if healthy else "FAIL"
    c = proof["counts"]
    result = {"schema_version": "3.0.0", "collection_id": journal.contract["collection_id"],
        "classification": "VERIFIED_COLLECTION" if healthy else "UNVERIFIED_COLLECTION",
        "contract": journal.contract, "started_at": journal.get("started_at"), "ended_at": journal.get("ended_at"),
        "state": journal.get("state"), "stop_reason": journal.get("stop_reason"), **proof,
        "GLOBAL_LEGACY_DATA_QUALITY": "WARN" if legacy["status"] == "INCOMPLETE" else "PASS",
        "CURRENT_COLLECTION_DATA_QUALITY": quality, "DATA_QUALITY": quality,
        "legacy_evidence_hash": digest(legacy), "legacy_limitation": LEGACY_WARNING,
        "current_evidence_statement": "Current bounded collection has complete ingress and processing evidence." if healthy else "Current collection evidence is incomplete.",
        "GAPS": journal.get("gaps"), "legacy_gaps": legacy.get("gaps", {}),
        "gap_boundary_note": "Collection starts at its first observed live ID; no continuity to the legacy cursor is asserted.",
        "processed_definition": f"{WORKER}: persisted raw event transformed by TIM CandleAggregator and output-hash replay verified; downstream intelligence not run.",
        "TRADING_ACTIONS": 0, "LIVE_TRADING": "DISABLED", "LIVE_INGESTION_AFTER": "DISABLED",
        "BOUNDED_LIVE_COLLECTION": "PASS" if healthy else "FAIL",
        "MISSION_04_CURRENT_COLLECTION_ACCEPTANCE": "PASS" if healthy else "FAIL",
        "TIM_AUTONOMOUS_COLLECTION_READY": "YES" if healthy else "NO",
        "SHORT_DATA_READINESS": "LIMITED" if healthy else "NOT_READY",
        "MID_DATA_READINESS": "LIMITED" if legacy.get("raw_trades_total", 0) else "NOT_READY",
        "LONG_DATA_READINESS": "LIMITED" if legacy.get("raw_trades_total", 0) else "NOT_READY",
        "readiness_reason": "Bounded technical collection evidence is not full horizon coverage; legacy data remains LEGACY_EVIDENCE_INCOMPLETE. No horizon qualification/strategy validation performed.",
        "QUEUE_AFTER": sum(c["statuses"][s] for s in STATUSES if s != "COMPLETED")}
    result["RESULT_HASH"] = digest(result)
    return result
