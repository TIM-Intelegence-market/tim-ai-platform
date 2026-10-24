#!/usr/bin/env python3
"""Bot 3: Papier-Trading-Bot. Handelt nur auf dem Papier, mit fiktivem Startkapital.

Regeln (aus dem Setup, für TIM präzisiert):
- Startguthaben 1.000 USD (fiktiv). Keine Börsenanbindung, keine Schlüssel, keine Orders.
- Kauf (nur Long, wie Spot) nur, wenn der Scanner den Coin mit Aufwärtsbewegung markiert hat UND der
  Buzz-Score mindestens 7 ist. Signal muss frisch sein (Standard: höchstens 15 Minuten alt).
- Risiko je Trade höchstens 1 % des Kontos: Größe so gewählt, dass Stop + Gebühren + Schlupf ≈ 1 % kosten.
- Jeder Trade hat Stop-Loss (Standard 3 %) und Take-Profit (Standard 2R = 6 %), dazu ein Zeitlimit (24 h).
- Gebühren 0,1 % je Seite (Binance-Taker) und 0,05 % Schlupf je Seite.
- Höchstens 10 neue Trades pro Kalendertag (UTC), höchstens eine offene Position je Coin.
- Ausstieg wird an 5-Minuten-Kerzen nach dem Einstieg geprüft. Trifft eine Kerze Stop und Ziel zugleich,
  zählt der Stop (vorsichtige Annahme). Kurslücken über den Stop werden zum Eröffnungskurs gefüllt.
- Schatten-Buch: Treffer mit Buzz < 7 werden mit denselben Regeln nur mitgerechnet (ohne Kontowirkung),
  damit der Bericht zeigen kann, ob der Buzz-Score überhaupt hilft.

Schreibt trades.csv (abgeschlossene Trades), signals.csv (jede Entscheidung) und state.json.
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    BinancePublic,
    SnapshotMarket,
    append_rows,
    default_data_dir,
    dt_to_ms,
    iso,
    load_json,
    ms_to_dt,
    parse_iso,
    read_rows,
    save_json_atomic,
    signal_key,
    utc_now,
)

TRADE_FIELDS = [
    "trade_id", "ledger", "symbol", "buzz_score", "opened_at", "closed_at", "entry_price", "exit_price",
    "qty", "notional", "fees", "gross_pnl", "net_pnl", "risk_amount", "r_multiple", "exit_reason",
    "balance_after",
]
SIGNAL_FIELDS = ["decided_at", "signal", "symbol", "direction", "buzz_score", "decision", "detail"]
FIVE_MIN_MS = 5 * 60 * 1000
MIN_NOTIONAL = 10.0


@dataclass(frozen=True)
class Config:
    start_balance: float = 1000.0
    risk_pct: float = 1.0
    stop_pct: float = 3.0
    reward_risk: float = 2.0
    fee_pct: float = 0.1
    slippage_pct: float = 0.05
    max_trades_per_day: int = 10
    max_hold_hours: float = 24.0
    buzz_min: float = 7.0
    max_signal_age_min: float = 15.0


def new_state(cfg: Config) -> dict:
    return {
        "start_balance": cfg.start_balance, "cash": cfg.start_balance, "realized_net_pnl": 0.0,
        "fees_paid": 0.0, "open": [], "shadow_open": [], "processed": [], "trades_by_day": {},
        "next_id": 1, "config": asdict(cfg), "mode": "PAPER_ONLY",
    }


def equity_at_cost(state: dict) -> float:
    return state["cash"] + sum(p["notional"] + p["entry_fee"] for p in state["open"])


def position_size(equity: float, cash: float, cfg: Config) -> tuple[float, float]:
    """Gibt (Nominalwert, Risikobetrag) zurück. Verlust am Stop inkl. Kosten ≈ risk_pct vom Konto."""
    risk_amount = equity * cfg.risk_pct / 100.0
    loss_per_unit = (cfg.stop_pct + 2 * cfg.fee_pct + cfg.slippage_pct) / 100.0
    notional = risk_amount / loss_per_unit
    notional = min(notional, cash / (1 + cfg.fee_pct / 100.0))
    return notional, risk_amount


def open_position(state: dict, ledger: str, symbol: str, buzz: float, key: str, mid_price: float,
                  now: datetime, cfg: Config) -> dict | None:
    equity = equity_at_cost(state)
    # Schatten-Trades binden kein Guthaben: Obergrenze ist das Konto, nicht das freie Guthaben.
    notional, risk_amount = position_size(equity, state["cash"] if ledger == "real" else equity, cfg)
    if notional < MIN_NOTIONAL:
        return None
    entry = mid_price * (1 + cfg.slippage_pct / 100.0)
    qty = notional / entry
    fee = notional * cfg.fee_pct / 100.0
    pos = {
        "trade_id": f"{ledger[0].upper()}{state['next_id']:05d}", "ledger": ledger, "symbol": symbol,
        "buzz_score": buzz, "signal": key, "opened_at": iso(now), "entry_price": entry, "qty": qty,
        "notional": notional, "entry_fee": fee, "risk_amount": risk_amount,
        "stop": entry * (1 - cfg.stop_pct / 100.0),
        "take_profit": entry * (1 + cfg.stop_pct * cfg.reward_risk / 100.0),
        "deadline": iso(now + timedelta(hours=cfg.max_hold_hours)),
    }
    state["next_id"] += 1
    if ledger == "real":
        state["cash"] -= notional + fee
        state["fees_paid"] += fee
        state["open"].append(pos)
    else:
        state["shadow_open"].append(pos)
    return pos


def find_exit(pos: dict, candles: list[list]) -> tuple[float, str, datetime] | None:
    """Erster Ausstieg in den Kerzen (vor Schlupf). None, solange nichts ausgelöst hat."""
    stop, tp = pos["stop"], pos["take_profit"]
    deadline = parse_iso(pos["deadline"])
    for k in candles:
        o, h, low, c = float(k[1]), float(k[2]), float(k[3]), float(k[4])
        close_time = ms_to_dt(int(k[6]) + 1)
        if o <= stop:
            return o, "stop_gap", close_time
        if low <= stop:
            return stop, "stop", close_time
        if o >= tp:
            return o, "take_profit_gap", close_time
        if h >= tp:
            return tp, "take_profit", close_time
        if close_time >= deadline:
            return c, "time", close_time
    return None


def close_position(state: dict, pos: dict, raw_exit: float, reason: str, when: datetime, cfg: Config) -> dict:
    exit_price = raw_exit * (1 - cfg.slippage_pct / 100.0)
    value = pos["qty"] * exit_price
    exit_fee = value * cfg.fee_pct / 100.0
    gross = value - pos["notional"]
    fees = pos["entry_fee"] + exit_fee
    net = gross - fees
    row = {
        "trade_id": pos["trade_id"], "ledger": pos["ledger"], "symbol": pos["symbol"],
        "buzz_score": pos["buzz_score"], "opened_at": pos["opened_at"], "closed_at": iso(when),
        "entry_price": round(pos["entry_price"], 8), "exit_price": round(exit_price, 8),
        "qty": round(pos["qty"], 8), "notional": round(pos["notional"], 4), "fees": round(fees, 4),
        "gross_pnl": round(gross, 4), "net_pnl": round(net, 4), "risk_amount": round(pos["risk_amount"], 4),
        "r_multiple": round(net / pos["risk_amount"], 3) if pos["risk_amount"] else "",
        "exit_reason": reason, "balance_after": "",
    }
    if pos["ledger"] == "real":
        state["cash"] += value - exit_fee
        state["fees_paid"] += exit_fee
        state["realized_net_pnl"] += net
        row["balance_after"] = round(state["cash"], 4)
    return row


def check_exits(state: dict, market, now: datetime, cfg: Config, log=print) -> list[dict]:
    closed = []
    for book in ("open", "shadow_open"):
        keep = []
        for pos in state[book]:
            start_ms = math.ceil(dt_to_ms(parse_iso(pos["opened_at"])) / FIVE_MIN_MS) * FIVE_MIN_MS
            try:
                kl = market.klines(pos["symbol"], "5m", 1000, start_ms=start_ms)
            except Exception as exc:
                log(f"  {pos['symbol']}: Kerzen für Ausstieg nicht geladen ({exc})", file=sys.stderr)
                keep.append(pos)
                continue
            candles = [k for k in kl if int(k[0]) >= start_ms and int(k[6]) < dt_to_ms(now)]
            hit = find_exit(pos, candles)
            if hit is None:
                keep.append(pos)
                continue
            closed.append(close_position(state, pos, hit[0], hit[1], hit[2], cfg))
        state[book] = keep
    return closed


def pending_signals(data_dir: Path, processed: set[str]) -> list[dict]:
    buzz = {signal_key(r["symbol"], r["candle_close_time"]): r for r in read_rows(data_dir / "buzz.csv")}
    out = []
    for r in read_rows(data_dir / "scanner.csv"):
        key = signal_key(r["symbol"], r["candle_close_time"])
        if key in processed or key not in buzz:
            continue
        out.append({**r, "key": key, "buzz_score": float(buzz[key]["buzz_score"])})
    return out


def decide(state: dict, sig: dict, market, now: datetime, cfg: Config) -> tuple[str, str]:
    age_min = (now - parse_iso(sig["scanned_at"])).total_seconds() / 60.0
    if sig["direction"] != "up":
        return "skip_down", "nur Long (Spot-Logik)"
    if age_min > cfg.max_signal_age_min:
        return "skip_stale", f"Signal {age_min:.0f} min alt"
    real = sig["buzz_score"] >= cfg.buzz_min
    ledger = "real" if real else "shadow"
    book = state["open"] if real else state["shadow_open"]
    if any(p["symbol"] == sig["symbol"] for p in book):
        return "skip_open_position", f"{ledger}: Position in {sig['symbol']} schon offen"
    day = now.date().isoformat()
    if real and state["trades_by_day"].get(day, 0) >= cfg.max_trades_per_day:
        return "skip_daily_cap", f"{cfg.max_trades_per_day} Trades heute erreicht"
    try:
        price = market.price(sig["symbol"])
    except Exception as exc:
        return "retry_price", f"Preis nicht geladen ({exc})"
    pos = open_position(state, ledger, sig["symbol"], sig["buzz_score"], sig["key"], price, now, cfg)
    if pos is None:
        return "skip_cash", "zu wenig freies Papier-Guthaben"
    if real:
        state["trades_by_day"][day] = state["trades_by_day"].get(day, 0) + 1
    return f"{ledger}_open", (
        f"{pos['trade_id']} Einstieg {pos['entry_price']:.6g}, Stop {pos['stop']:.6g}, Ziel {pos['take_profit']:.6g}, "
        f"Nominal {pos['notional']:.2f}"
    )


def run(market, data_dir: Path, now: datetime | None = None, cfg: Config = Config(), log=print) -> dict:
    now = now or utc_now()
    state_path = data_dir / "state.json"
    state = load_json(state_path, None) or new_state(cfg)
    closed = check_exits(state, market, now, cfg, log)
    append_rows(data_dir / "trades.csv", TRADE_FIELDS, closed)

    processed = set(state["processed"])
    decisions = []
    for sig in pending_signals(data_dir, processed):
        decision, detail = decide(state, sig, market, now, cfg)
        decisions.append({
            "decided_at": iso(now), "signal": sig["key"], "symbol": sig["symbol"], "direction": sig["direction"],
            "buzz_score": sig["buzz_score"], "decision": decision, "detail": detail,
        })
        if decision != "retry_price":
            processed.add(sig["key"])
    state["processed"] = sorted(processed)
    append_rows(data_dir / "signals.csv", SIGNAL_FIELDS, decisions)
    save_json_atomic(state_path, state)

    for row in closed:
        tag = "" if row["ledger"] == "real" else " (Schatten)"
        log(f"  Geschlossen{tag}: {row['symbol']} {row['exit_reason']}, netto {float(row['net_pnl']):+.2f} USD")
    for d in decisions:
        log(f"  Signal {d['symbol']} Buzz {d['buzz_score']:g}: {d['decision']} - {d['detail']}")
    log(
        f"Papier-Bot: Guthaben {state['cash']:.2f} USD frei, {len(state['open'])} offen, "
        f"realisiert netto nach Gebühren {state['realized_net_pnl']:+.2f} USD "
        f"(Gebühren gesamt {state['fees_paid']:.2f}), Schatten offen {len(state['shadow_open'])}"
    )
    return {"closed": closed, "decisions": decisions, "state": state}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", type=Path, default=default_data_dir())
    p.add_argument("--snapshot", type=Path, help="Offline-JSON statt Binance-Live-Daten")
    p.add_argument("--max-trades-per-day", type=int, default=10)
    p.add_argument("--stop-pct", type=float, default=3.0)
    p.add_argument("--reward-risk", type=float, default=2.0)
    p.add_argument("--fee-pct", type=float, default=0.1)
    a = p.parse_args(argv)
    cfg = Config(max_trades_per_day=a.max_trades_per_day, stop_pct=a.stop_pct, reward_risk=a.reward_risk,
                 fee_pct=a.fee_pct)
    market = SnapshotMarket.from_file(a.snapshot) if a.snapshot else BinancePublic()
    run(market, a.data_dir, cfg=cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
