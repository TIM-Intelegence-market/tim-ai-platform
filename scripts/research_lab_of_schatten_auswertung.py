"""Auswertung des Orderflow-Schattens nach docs/research_lab/studien/OF_SCHATTEN_AUSWERTUNGSREGEL.md (Version 1.2).

Nur lesend. Liest die Schatten-Datei und die Papier-Journale, schreibt ein JSON mit allen Zahlen und den zwei Urteilen.
Aufruf: python scripts/research_lab_of_schatten_auswertung.py --journal-dir data/journal --out bericht.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.dashboard.plan_journal import FEE_PER_SIDE, SLIPPAGE_PER_SIDE, STOP_EXITS, STOP_SLIPPAGE, THIRD, _r

TARGET = 30
DRAWS = 10_000
SEED = 20261116
BAND = (0.0125, 0.9875)          # Bonferroni, 2 Tests
MIN_GROUP, MIN_GROUP_CLUSTERS = 8, 5
MIN_CLUSTERS_B = 10
MAX_PRECHECK_ERRORS = 3
FILL_TOLERANCE = timedelta(minutes=5)


def _t(value: Any) -> datetime:
    moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _costs(entry: Mapping[str, Any], hits: int, exit_price: float, stop_exit: bool) -> float:
    """fee_r + slippage_r like plan_journal.costs_r, for ``hits`` booked thirds and the rest at ``exit_price``."""
    risk = abs(float(entry["entry"]) - float(entry["stop"]))
    fill = float(entry.get("fill_price") or entry["entry"])
    rest = 1.0 - THIRD * hits
    fee, slip = FEE_PER_SIDE * fill, SLIPPAGE_PER_SIDE * fill
    for index in range(hits):
        target = float(entry["targets"][index])
        fee += THIRD * FEE_PER_SIDE * target
        slip += THIRD * SLIPPAGE_PER_SIDE * target
    fee += rest * FEE_PER_SIDE * exit_price
    slip += rest * (STOP_SLIPPAGE if stop_exit else SLIPPAGE_PER_SIDE) * exit_price
    return (fee + slip) / risk


def _gross(entry: Mapping[str, Any], hits: int, exit_price: float) -> float:
    realised = sum(THIRD * _r(entry, entry["targets"][i]) for i in range(hits))
    return realised + (1.0 - THIRD * hits) * _r(entry, exit_price)


def journal_result(entry: Mapping[str, Any], cost_factor: float = 1.0) -> float:
    hits = len(entry.get("tp_hits") or [])
    price = float(entry["exit_price"])
    return _gross(entry, hits, price) - cost_factor * _costs(entry, hits, price, entry.get("exit_reason") in STOP_EXITS)


def shadow_result(entry: Mapping[str, Any], of_exit: Mapping[str, Any], cost_factor: float = 1.0) -> float:
    at = _t(of_exit["at"])
    hits = sum(1 for moment in entry.get("tp_hits") or [] if _t(moment) < at)
    price = float(of_exit["price"])
    return _gross(entry, hits, price) - cost_factor * _costs(entry, hits, price, False)


def active_stop(entry: Mapping[str, Any], at: datetime, *, strict: bool) -> float:
    """Stop in force at ``at``: last stop_path entry before the 1m candle of ``at``; else the plan stop.

    ``strict`` reads "vor der 1m-Kerze" as at < candle start; the other reading (at <= candle start) is the
    journal's own rule (a move written at a candle close is in force from the next candle). Both are reported."""
    candle = at.replace(second=0, microsecond=0)
    level = float(entry["stop"])
    for row in entry.get("stop_path") or []:
        moved = _t(row[0])
        if moved < candle or (not strict and moved == candle):
            level = float(row[1])
    return level


def gate_of(record: Mapping[str, Any], tolerance: timedelta) -> tuple[str, int]:
    journal = record["journal"]
    filled, closed = _t(journal["filled_at"]), _t(journal["closed_at"])
    view = record.get("lage_at_fill")
    if view and view.get("as_of") and _t(view["as_of"]) <= filled + tolerance and _t(view["as_of"]) < closed:
        return str(record.get("gate_at_fill")), 1
    view = record.get("lage_at_plan")
    if view and view.get("as_of") and _t(view["as_of"]) <= filled:
        return str(record.get("gate_at_plan")), 2
    return "UNBEKANNT", 3


def _stats(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    peak = total = drawdown = 0.0
    for value in values:
        total += value
        peak = max(peak, total)
        drawdown = max(drawdown, peak - total)
    return {"n": len(values), "summe_r": round(sum(values), 3), "mittel_r": round(sum(values) / len(values), 4),
            "trefferquote": round(sum(v > 0 for v in values) / len(values), 3), "max_drawdown_r": round(drawdown, 3)}


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    return sorted_values[min(len(sorted_values) - 1, max(0, int(q * len(sorted_values))))]


def bootstrap(clusters: Sequence[Sequence[Mapping[str, Any]]], statistic, rng: random.Random) -> dict[str, Any]:
    values, skipped = [], 0
    for _ in range(DRAWS):
        sample = [plan for _ in clusters for plan in rng.choice(clusters)]
        value = statistic(sample)
        if value is None:
            skipped += 1
        else:
            values.append(value)
    values.sort()
    if not values:
        return {"ziehungen": 0, "uebersprungen": skipped}
    return {"ziehungen": len(values), "uebersprungen": skipped,
            "band_97_5": [round(_quantile(values, BAND[0]), 4), round(_quantile(values, BAND[1]), 4)],
            "band_95": [round(_quantile(values, 0.025), 4), round(_quantile(values, 0.975), 4)]}


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def gate_difference(plans: Sequence[Mapping[str, Any]], key: str = "journal_net") -> float | None:
    yes, no = _mean([p[key] for p in plans if p["gate"] == "BESTÄTIGT"]), _mean([p[key] for p in plans if p["gate"] == "GEGEN"])
    return None if yes is None or no is None else yes - no


def evaluate(shadow: Mapping[str, Any], journals: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    started = _t(shadow["started_at"])
    entries = {name: {str(e["id"]): e for e in journal.get("entries") or []} for name, journal in journals.items()}
    countable = []
    for record in (shadow.get("plans") or {}).values():
        journal = record.get("journal") or {}
        if journal.get("status") == "CLOSED" and journal.get("net_r") is not None and _t(record["created_at"]) >= started:
            entry = entries.get(record["journal_file"], {}).get(str(record["id"]))
            if entry is None or entry.get("excluded"):
                continue
            countable.append((record, entry))
    countable.sort(key=lambda pair: (_t(pair[0]["journal"]["closed_at"]), str(pair[0]["id"])))
    sample = countable[:TARGET]

    plans: list[dict[str, Any]] = []
    for record, entry in sample:
        journal = record["journal"]
        gate, stage = gate_of(record, FILL_TOLERANCE)
        gate35, _ = gate_of(record, timedelta(minutes=35))
        plan = {"id": str(record["id"]), "tf": record.get("timeframe"), "direction": record.get("direction"),
                "filled_at": journal["filled_at"], "closed_at": journal["closed_at"], "exit_reason": journal.get("exit_reason"),
                "journal_net": float(journal["net_r"]), "journal_net_nachgerechnet": round(journal_result(entry), 4),
                "journal_net_x2": journal_result(entry, 2.0), "gate": gate, "gate_stufe": stage, "gate_35min": gate35,
                "lage_at_fill_fehlt": not record.get("lage_at_fill"), "of_exit": bool(record.get("of_exit")), "precheck": "kein_of_exit"}
        plan["shadow_net"], plan["shadow_net_x2"] = plan["journal_net"], plan["journal_net_x2"]
        of_exit = record.get("of_exit")
        if of_exit:
            at, long = _t(of_exit["at"]), record.get("direction") == "LONG"
            in_time = _t(journal["filled_at"]) < at < _t(journal["closed_at"])
            checks = {}
            for name, strict in (("streng", True), ("wie_journal", False)):
                stop = active_stop(entry, at, strict=strict)
                checks[name] = in_time and (float(of_exit["price"]) > stop if long else float(of_exit["price"]) < stop)
            plan["precheck_lesarten"] = checks
            plan["precheck"] = "ok" if checks["wie_journal"] else ("zeit" if not in_time else "stop")
            if plan["precheck"] == "ok":
                plan["shadow_net"] = shadow_result(entry, of_exit)
                plan["shadow_net_x2"] = shadow_result(entry, of_exit, 2.0)
        plan["diff"], plan["diff_x2"] = plan["shadow_net"] - plan["journal_net"], plan["shadow_net_x2"] - plan["journal_net_x2"]
        plans.append(plan)

    by_cluster: dict[tuple, list[dict[str, Any]]] = {}
    for plan in plans:
        by_cluster.setdefault((plan["direction"], plan["filled_at"], plan["closed_at"]), []).append(plan)
    clusters = list(by_cluster.values())
    spans = [(_t(k[1]), _t(k[2])) for k in by_cluster]
    overlapping = sum(any(i != j and a < d and c < b for j, (c, d) in enumerate(spans)) for i, (a, b) in enumerate(spans))

    rng = random.Random(SEED)
    groups = {name: [p for p in plans if p["gate"] == name] for name in ("BESTÄTIGT", "GEGEN", "NEUTRAL", "UNBEKANNT")}
    group_clusters = {name: sum(any(p["gate"] == name for p in c) for c in clusters) for name in groups}
    diff_a, diff_a_x2 = gate_difference(plans), gate_difference(plans, "journal_net_x2")
    band_a = bootstrap(clusters, gate_difference, rng)
    enough = all(len(groups[g]) >= MIN_GROUP and group_clusters[g] >= MIN_GROUP_CLUSTERS for g in ("BESTÄTIGT", "GEGEN"))
    if not enough:
        verdict_a = "ZU WENIG"
    elif diff_a > 0 and band_a["band_97_5"][0] > 0 and diff_a_x2 > 0:
        verdict_a = "GATE HILFT IM PAPIER"
    elif band_a["band_97_5"][1] < 0:
        verdict_a = "GATE UMGEKEHRT"
    else:
        verdict_a = "NICHT BELEGT"

    errors = [p["id"] for p in plans if p["precheck"] in ("zeit", "stop")]
    diffs, diffs_x2 = [p["diff"] for p in plans], [p["diff_x2"] for p in plans]
    band_b = bootstrap(clusters, lambda s: _mean([p["diff"] for p in s]), rng)
    mean_b, mean_b_x2 = _mean(diffs), _mean(diffs_x2)
    if len(plans) < TARGET or len(clusters) < MIN_CLUSTERS_B or len(errors) > MAX_PRECHECK_ERRORS:
        verdict_b = "KEIN URTEIL"
    elif mean_b > 0 and band_b["band_97_5"][0] > 0 and mean_b_x2 > 0:
        verdict_b = "OF-AUSSTIEG BESSER IM PAPIER"
    elif band_b["band_97_5"][1] < 0:
        verdict_b = "OF-AUSSTIEG SCHLECHTER"
    else:
        verdict_b = "NICHT BELEGT"

    winners = [p for p in plans if p["journal_net"] > 0]
    losers = [p for p in plans if p["journal_net"] <= 0]
    return {
        "regel": "OF_SCHATTEN_AUSWERTUNGSREGEL 1.2", "seed": SEED, "ziehungen": DRAWS,
        "stichprobe": {"zaehlbar_gesamt": len(countable), "ausgewertet": len(plans), "cluster": len(clusters),
                       "cluster_ueberlappend": overlapping, "richtungen": sorted({p["direction"] for p in plans}),
                       "erster_schluss": plans[0]["closed_at"] if plans else None, "letzter_schluss": plans[-1]["closed_at"] if plans else None,
                       "journal_nachrechnung_max_abweichung": round(max((abs(p["journal_net"] - p["journal_net_nachgerechnet"]) for p in plans), default=0), 4)},
        "alle": {"journal": _stats([p["journal_net"] for p in plans]), "schatten_of_ausstieg": _stats([p["shadow_net"] for p in plans])},
        "vergleich_a": {"gruppen": {g: {**_stats([p["journal_net"] for p in ps]), "cluster": group_clusters[g]} for g, ps in groups.items()},
                        "gate_stufen": {str(s): sum(p["gate_stufe"] == s for p in plans) for s in (1, 2, 3)},
                        "differenz_bestaetigt_minus_gegen": None if diff_a is None else round(diff_a, 4),
                        "differenz_doppelte_kosten": None if diff_a_x2 is None else round(diff_a_x2, 4), "bootstrap": band_a,
                        "nur_beschreibend_35min": {g: sum(p["gate_35min"] == g for p in plans) for g in groups}, "urteil": verdict_a},
        "vergleich_b": {"mit_of_exit": sum(p["of_exit"] for p in plans), "ohne_of_exit": sum(not p["of_exit"] for p in plans),
                        "lage_at_fill_fehlt": sum(p["lage_at_fill_fehlt"] for p in plans),
                        "precheck_fehler": errors, "precheck_fehler_lesart_streng": [p["id"] for p in plans if p.get("precheck_lesarten") and not p["precheck_lesarten"]["streng"]],
                        "mittlere_differenz": round(mean_b, 4), "summe_differenz": round(sum(diffs), 3),
                        "mittlere_differenz_doppelte_kosten": round(mean_b_x2, 4), "bootstrap": band_b,
                        "journal_stop_anteil": round(sum(p["exit_reason"] in STOP_EXITS for p in plans) / len(plans), 3) if plans else None,
                        "differenz_journal_gewinner": {"n": len(winners), "mittel": None if not winners else round(_mean([p["diff"] for p in winners]), 4)},
                        "differenz_journal_verlierer": {"n": len(losers), "mittel": None if not losers else round(_mean([p["diff"] for p in losers]), 4)},
                        "urteil": verdict_b},
        "plaene": [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in p.items()} for p in plans],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal-dir", type=Path, default=Path("data/journal"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    shadow_path = args.journal_dir / "tim_orderflow_shadow.json"
    shadow = json.loads(shadow_path.read_text(encoding="utf-8"))
    names = sorted({str(r.get("journal_file")) for r in (shadow.get("plans") or {}).values()})
    journals, hashes = {}, {shadow_path.name: hashlib.sha256(shadow_path.read_bytes()).hexdigest()}
    for name in names:
        raw = (args.journal_dir / name).read_bytes()
        journals[name], hashes[name] = json.loads(raw), hashlib.sha256(raw).hexdigest()
    report = evaluate(shadow, journals)
    report["eingaben_sha256"] = hashes
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("stichprobe", "alle")}, ensure_ascii=False))
    print(json.dumps({k: v for k, v in report["vergleich_a"].items()}, ensure_ascii=False))
    print(json.dumps({k: v for k, v in report["vergleich_b"].items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
