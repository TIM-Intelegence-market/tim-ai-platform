#!/usr/bin/env python3
"""Ehrlicher Abschlussbericht über trades.csv (nach 2-4 Wochen Papierhandel).

Zeigt: Anzahl Trades, Trefferquote, Gewinn/Verlust nach Gebühren, größter Verlust, Gebührenlast,
Erwartungswert in R und ob der Buzz-Score geholfen hat (Vergleich mit dem Schatten-Buch, Buzz < 7).
Das Urteil ist absichtlich streng: wenig Daten oder kein Gewinn nach Gebühren heißt "nein".
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import default_data_dir, load_json, read_rows  # noqa: E402

MIN_TRADES_FOR_VERDICT = 30
MIN_TRADES_PER_GROUP = 10


def stats(rows: list[dict]) -> dict:
    n = len(rows)
    if n == 0:
        return {"trades": 0}
    nets = [float(r["net_pnl"]) for r in rows]
    gross = [float(r["gross_pnl"]) for r in rows]
    rs = [float(r["r_multiple"]) for r in rows if r.get("r_multiple") not in ("", None)]
    wins = sum(1 for x in nets if x > 0)
    mean_r = sum(rs) / len(rs) if rs else 0.0
    sd_r = math.sqrt(sum((x - mean_r) ** 2 for x in rs) / (len(rs) - 1)) if len(rs) > 1 else 0.0
    reasons: dict[str, int] = {}
    for r in rows:
        reasons[r["exit_reason"]] = reasons.get(r["exit_reason"], 0) + 1
    worst = min(rows, key=lambda r: float(r["net_pnl"]))
    return {
        "trades": n, "wins": wins, "win_rate": wins / n, "net_pnl": sum(nets), "gross_pnl": sum(gross),
        "fees": sum(float(r["fees"]) for r in rows), "biggest_loss": float(worst["net_pnl"]),
        "biggest_loss_trade": f"{worst['trade_id']} {worst['symbol']} ({worst['exit_reason']})",
        "mean_r": mean_r, "sd_r": sd_r, "t_stat": mean_r / (sd_r / math.sqrt(len(rs))) if sd_r > 0 else 0.0,
        "exit_reasons": reasons,
    }


def buzz_verdict(real: dict, shadow: dict) -> str:
    if real.get("trades", 0) < MIN_TRADES_PER_GROUP or shadow.get("trades", 0) < MIN_TRADES_PER_GROUP:
        return (f"Nicht beurteilbar: je Gruppe mindestens {MIN_TRADES_PER_GROUP} Trades nötig "
                f"(Buzz >= 7: {real.get('trades', 0)}, Buzz < 7: {shadow.get('trades', 0)}).")
    diff = real["mean_r"] - shadow["mean_r"]
    if diff > 0.1:
        return f"Eher ja: Buzz >= 7 im Schnitt {diff:+.2f}R besser als Buzz < 7 (Stichprobe noch klein)."
    if diff < -0.1:
        return f"Nein: Buzz >= 7 im Schnitt {diff:+.2f}R schlechter als Buzz < 7."
    return f"Kein erkennbarer Unterschied ({diff:+.2f}R)."


def overall_verdict(real: dict) -> str:
    n = real.get("trades", 0)
    if n < MIN_TRADES_FOR_VERDICT:
        return (f"NEIN, nicht belegt: nur {n} Trades. Unter {MIN_TRADES_FOR_VERDICT} Trades ist jedes Ergebnis "
                f"vom Zufall nicht zu unterscheiden.")
    if real["net_pnl"] <= 0:
        return "NEIN: nach Gebühren kein Gewinn. Mit echten Orders käme noch schlechtere Ausführung dazu."
    if real["t_stat"] < 2.0:
        return (f"NEIN, nicht belegt: Gewinn nach Gebühren, aber statistisch schwach (t = {real['t_stat']:.2f} < 2). "
                f"Weiter auf Papier sammeln.")
    return (f"VIELLEICHT: Gewinn nach Gebühren und t = {real['t_stat']:.2f}. Vor jedem Echtgeld-Gedanken: "
            f"Out-of-Sample-Zeitraum, Research-Lab-Prüfung (backtest-expert, edge-strategy-reviewer) und Uzis Wort.")


def build(data_dir: Path) -> dict:
    rows = read_rows(data_dir / "trades.csv")
    real = stats([r for r in rows if r["ledger"] == "real"])
    shadow = stats([r for r in rows if r["ledger"] == "shadow"])
    state = load_json(data_dir / "state.json", {})
    return {
        "start_balance": state.get("start_balance"), "cash": state.get("cash"),
        "open_positions": len(state.get("open", [])), "real": real, "shadow": shadow,
        "buzz_helped": buzz_verdict(real, shadow), "verdict": overall_verdict(real),
    }


def render(rep: dict) -> str:
    r = rep["real"]
    lines = ["# Trading-Team: ehrlicher Bericht (nur Papier)", ""]
    if r.get("trades", 0) == 0:
        lines.append("Noch keine abgeschlossenen Trades.")
    else:
        lines += [
            f"- Trades gesamt: {r['trades']} (Gewinner {r['wins']}, Trefferquote {r['win_rate']:.1%})",
            f"- Ergebnis nach Gebühren: {r['net_pnl']:+.2f} USD (vor Gebühren {r['gross_pnl']:+.2f}, Gebühren {r['fees']:.2f})",
            f"- Größter Verlust: {r['biggest_loss']:+.2f} USD ({r['biggest_loss_trade']})",
            f"- Erwartungswert: {r['mean_r']:+.3f}R je Trade (Streuung {r['sd_r']:.3f}R, t = {r['t_stat']:.2f})",
            f"- Ausstiege: {', '.join(f'{k} {v}' for k, v in sorted(r['exit_reasons'].items()))}",
        ]
        if rep.get("start_balance") is not None:
            lines.append(f"- Konto: Start {rep['start_balance']:.2f} USD, frei {rep['cash']:.2f} USD, "
                         f"{rep['open_positions']} Position(en) offen")
    s = rep["shadow"]
    lines += ["", "## Hat der Buzz-Score geholfen?", ""]
    if s.get("trades", 0):
        lines.append(f"- Schatten-Buch (Buzz < 7): {s['trades']} Trades, Trefferquote {s['win_rate']:.1%}, "
                     f"{s['mean_r']:+.3f}R je Trade")
    lines += [f"- {rep['buzz_helped']}", "", "## Würde das mit echten Orders Geld verdienen?", "",
              rep["verdict"], "",
              "Hinweis: TIM handelt kein Echtgeld. Dieser Bericht ist Research, kein Handelssignal."]
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", type=Path, default=default_data_dir())
    p.add_argument("--json", action="store_true", help="Rohwerte als JSON ausgeben")
    a = p.parse_args(argv)
    rep = build(a.data_dir)
    print(json.dumps(rep, indent=2, ensure_ascii=False) if a.json else render(rep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
