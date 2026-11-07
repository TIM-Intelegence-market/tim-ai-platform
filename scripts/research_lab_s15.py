"""Study S15: GARCH(1,1) volatility forecast against the rolling 14-day variance (BTC/ETH/SOL, 4h and 1d).

    python scripts/research_lab_s15.py count --out DIR    # forecast periods per section, no loss, no forecast
    python scripts/research_lab_s15.py run --out DIR      # training and validation with losses (section 5)

Uses the 5m USD-M klines already fetched for S10 (`scripts/research_lab_s10.py fetch`, run on the Mac).
Holdout months (2025+) are refused by the store and never requested here.
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.research_lab.data.archive import ArchiveRef, Dataset, Market
from src.research_lab.data.store import DEFAULT_ROOT, ArchiveStore, months
from src.research_lab.protocol import HOLDOUT_START_MS, UNIVERSE_LIMITATION, VALIDATION_START_MS
from src.research_lab.studies import s15

LAST = (2024, 12)
SYMBOLS = {"BTCUSDT": (2020, 1), "ETHUSDT": (2020, 1), "SOLUSDT": (2020, 9)}  # first full USD-M month (as S10/S14)
SECTIONS = {"train": (0, VALIDATION_START_MS), "validation": (VALIDATION_START_MS, HOLDOUT_START_MS)}


def refs(symbol: str) -> list[ArchiveRef]:
    return [ArchiveRef(Market.USDM, Dataset.KLINES, y, m, "5m", symbol) for y, m in months(SYMBOLS[symbol], LAST)]


def year_of(ms: int) -> str:
    return str(datetime.fromtimestamp(ms / 1000, tz=timezone.utc).year)


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def load_periods(store: ArchiveStore) -> tuple[dict, dict]:
    """Complete periods per variant and symbol, holdout cut off; info per symbol."""
    series: dict[str, dict[str, list[s15.Period]]] = {v.variant_id: {} for v in s15.S15_VARIANTS}
    info: dict[str, dict] = {}
    for symbol, first in SYMBOLS.items():
        bars = [b for b in store.load_klines(refs(symbol)) if b.open_time < HOLDOUT_START_MS]
        info[symbol] = {"first_month": f"{first[0]}-{first[1]:02d}", "bars_5m": len(bars)}
        for v in s15.S15_VARIANTS:
            series[v.variant_id][symbol] = s15.periods(bars, v)
            info[symbol][v.variant_id] = len(series[v.variant_id][symbol])
        del bars
    return series, info


def _header(store: ArchiveStore) -> dict:
    return {"study": "S15", "commit": _commit(), "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "dataset_hash": store.dataset_hash([r for s in SYMBOLS for r in refs(s)]),
            "burn_in_days": s15.BURN_IN_DAYS, "rolling_days": s15.ROLLING_DAYS, "refit_days": s15.REFIT_DAYS,
            "gate": s15.GATE}


def count_rows(series: dict) -> dict:
    """Outcome blind: evaluable periods (after the burn-in) per section; no forecast, no loss."""
    rows: dict = {}
    for v in s15.S15_VARIANTS:
        burn = s15.BURN_IN_DAYS * v.per_day
        per = {sec: {} for sec in SECTIONS}
        for symbol, ps in series[v.variant_id].items():
            starts = [p.start for p in ps[burn:]]
            for sec, (a, b) in SECTIONS.items():
                per[sec][symbol] = sum(1 for t in starts if a <= t < b)
        pooled = {sec: len({p.start for ps in series[v.variant_id].values() for p in ps[burn:]
                            if SECTIONS[sec][0] <= p.start < SECTIONS[sec][1]}) for sec in SECTIONS}
        rows[v.variant_id] = {"by_symbol": per, "pooled_periods": pooled,
                              "passes_gate": all(pooled[sec] >= s15.GATE[sec] for sec in SECTIONS)}
    return rows


def count(store: ArchiveStore, out_dir: Path) -> int:
    series, info = load_periods(store)
    payload = _header(store) | {"outcome_blind": True, "symbols": info, "variants": count_rows(series)}
    for vid, row in payload["variants"].items():
        print(f"{vid}: train {row['pooled_periods']['train']}, validation {row['pooled_periods']['validation']} "
              f"{'PASS' if row['passes_gate'] else 'below gate'}", flush=True)
    return _write(out_dir, "count", payload, count_markdown(payload))


def section_result(by_symbol: dict[str, list[s15.Forecast]]) -> dict:
    pooled = s15.pooled_by_start(by_symbol)
    d = list(pooled.values())
    usable = {sym: [f for f in fs if s15.usable(f)] for sym, fs in by_symbol.items()}
    loss = {}
    for name in ("rolling", "ewma", "garch"):
        q = [s15.qlike(f.rv, getattr(f, name)) for fs in usable.values() for f in fs]
        m = [s15.mse(f.rv, getattr(f, name)) for fs in usable.values() for f in fs]
        loss[name] = {"qlike": statistics.fmean(q) if q else None, "mse": statistics.fmean(m) if m else None}
    years: dict[str, list[float]] = {}
    for start, x in pooled.items():
        years.setdefault(year_of(start), []).append(x)
    return {
        "dm_rolling": s15.diebold_mariano(d),
        "dm_ewma": s15.diebold_mariano(s15.pooled_differences(by_symbol, "ewma")),
        "dm_rolling_mse": s15.diebold_mariano(s15.pooled_differences(by_symbol, "rolling", s15.mse)),
        "dm_ewma_mse": s15.diebold_mariano(s15.pooled_differences(by_symbol, "ewma", s15.mse)),
        "by_symbol": {sym: statistics.fmean(s15.qlike(f.rv, f.rolling) - s15.qlike(f.rv, f.garch) for f in fs) if fs else 0.0
                      for sym, fs in sorted(usable.items())},
        "by_year": {y: statistics.fmean(v) for y, v in sorted(years.items())},
        "loss": loss,
        "zero_rv": sum(1 for fs in by_symbol.values() for f in fs if f.rv <= 0),
        "excluded": sum(1 for fs in by_symbol.values() for f in fs if not s15.usable(f)),
    }


def run(store: ArchiveStore, out_dir: Path) -> int:
    series, info = load_periods(store)
    gate = count_rows(series)
    payload = _header(store) | {"symbols": info, "variants": {}, "gate_counts": gate}
    for v in s15.S15_VARIANTS:
        if not gate[v.variant_id]["passes_gate"]:
            print(f"{v.variant_id}: below the count gate 5.1, not evaluated", flush=True)
            continue
        forecasts: dict[str, dict[str, list]] = {sec: {} for sec in SECTIONS}
        refits: dict[str, list] = {}
        for symbol, ps in series[v.variant_id].items():
            got: list = []
            all_f = s15.forecasts(ps, v, 0, HOLDOUT_START_MS, got)
            refits[symbol] = [{"time": t, "omega": g.omega, "alpha": g.alpha, "beta": g.beta,
                               "persistence": g.persistence, "half_life_periods": g.half_life} for t, g in got]
            for sec, (a, b) in SECTIONS.items():
                forecasts[sec][symbol] = [f for f in all_f if a <= f.start < b]
            print(f"{v.variant_id} {symbol}: {len(all_f)} forecasts, {len(got)} refits", flush=True)
        res = {sec: section_result(forecasts[sec]) for sec in SECTIONS}
        res["verdict"] = s15.verdict(res["train"]["dm_rolling"], res["validation"]["dm_rolling"],
                                     res["validation"]["by_symbol"], res["validation"]["by_year"])
        res["last_fit"] = {sym: r[-1] for sym, r in refits.items() if r}
        res["refits"] = refits
        payload["variants"][v.variant_id] = res
        print(f"{v.variant_id}: {'PASSED' if res['verdict']['passed'] else 'not passed'}", flush=True)
    return _write(out_dir, "run", payload, run_markdown(payload))


def _write(out_dir: Path, kind: str, payload: dict, markdown: str) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    path = out_dir / f"s15_{kind}_{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    (out_dir / f"s15_{kind}_{stamp}.md").write_text(markdown)
    print(f"written {path}")
    return 0


def _f(x: float | None, digits: int = 3) -> str:
    return "–" if x is None else f"{x:.{digits}f}".replace(".", ",")


def _source(p: dict) -> str:
    return (f"Commit `{p['commit']}`, Datensatz-Hash `{p['dataset_hash']}`, erstellt {p['created']}. USD-M 5m, "
            f"{', '.join(f'{s} ab {v['first_month']}' for s, v in p['symbols'].items())}, bis 2024-12. Einlaufzeit "
            f"{p['burn_in_days']} Tage, Vergleich {p['rolling_days']}-Tage-Varianz, GARCH-Neuschätzung alle {p['refit_days']} Tage.")


def count_markdown(p: dict) -> str:
    lines = ["# S15 Zähllauf (Machbarkeits-Gate, ergebnisblind)", "", _source(p) +
             f" Gezählt werden nur vollständige Perioden nach der Einlaufzeit, keine Prognose und kein Fehler. "
             f"Gate gepoolt (verschiedene Periodenstarts): Training ≥ {p['gate']['train']}, Validierung ≥ {p['gate']['validation']}.", "",
             "| Variante | Training gepoolt | Validierung gepoolt | BTC / ETH / SOL Training | BTC / ETH / SOL Validierung | Gate |",
             "|---|---:|---:|---:|---:|---|"]
    for vid, v in p["variants"].items():
        bs = v["by_symbol"]
        lines.append(f"| {vid} | {v['pooled_periods']['train']} | {v['pooled_periods']['validation']} | "
                     f"{' / '.join(str(bs['train'][s]) for s in SYMBOLS)} | {' / '.join(str(bs['validation'][s]) for s in SYMBOLS)} | "
                     f"{'BESTANDEN' if v['passes_gate'] else 'nicht bestanden'} |")
    lines += ["", f"Holdout 2025+ nicht geladen. {UNIVERSE_LIMITATION}"]
    return "\n".join(lines) + "\n"


def run_markdown(p: dict) -> str:
    lines = ["# S15 Auswertung Training und Validierung (Prognosestudie, kein Holdout)", "", _source(p), "",
             "Differenz d = QLIKE(14-Tage-Varianz) − QLIKE(GARCH), gepoolt je Periodenstart. d > 0 heißt: GARCH ist besser. "
             "p einseitig aus Diebold-Mariano mit Newey-West.", "",
             "| Variante | Abschnitt | n | Ø d | t | p | Ø d gegen EWMA (p) | MSE: p gegen 14 T / gegen EWMA | QLIKE 14 T / EWMA / GARCH | ausgelassen (RV = 0) |",
             "|---|---|---:|---:|---:|---:|---:|---|---|---:|"]
    for vid, v in p["variants"].items():
        for sec, name in (("train", "Training"), ("validation", "Validierung")):
            r = v[sec]
            dm, de, lo = r["dm_rolling"], r["dm_ewma"], r["loss"]
            lines.append(f"| {vid} | {name} | {dm['n']} | {_f(dm['mean'], 4)} | {_f(dm['t'], 2)} | {_f(dm['p_one_sided'], 4)} | "
                         f"{_f(de['mean'], 4)} ({_f(de['p_one_sided'], 3)}) | "
                         f"{_f(r['dm_rolling_mse']['p_one_sided'], 3)} / {_f(r['dm_ewma_mse']['p_one_sided'], 3)} | "
                         f"{_f(lo['rolling']['qlike'])} / {_f(lo['ewma']['qlike'])} / {_f(lo['garch']['qlike'])} | "
                         f"{r['excluded']} ({r['zero_rv']}) |")
    lines.append("")
    for vid, g in p["gate_counts"].items():
        if vid not in p["variants"]:
            lines.append(f"**{vid}: am Zähl-Gate gescheitert, nicht ausgewertet.**")
    for vid, v in p["variants"].items():
        c = v["verdict"]["checks"]
        val = v["validation"]
        lines.append(f"**{vid}: {'BESTANDEN' if v['verdict']['passed'] else 'NICHT BESTANDEN'}.** "
                     + ", ".join(f"{k} {'ja' if ok else 'nein'}" for k, ok in c.items())
                     + ". Validierung je Coin Ø d: " + ", ".join(f"{s} {_f(x, 4)}" for s, x in val["by_symbol"].items())
                     + "; je Jahr: " + ", ".join(f"{y} {_f(x, 4)}" for y, x in val["by_year"].items()) + ".")
        lf = v["last_fit"]
        lines.append("Letzte Schätzung (α, β, Halbwertszeit in Perioden): " + "; ".join(
            f"{s} {_f(g['alpha'])}, {_f(g['beta'])}, {_f(g['half_life_periods'], 1)}" for s, g in lf.items()) + ".")
        if v["verdict"]["passed"]:
            ewma_p = val["dm_ewma"]["p_one_sided"]
            lines.append("Lesart 5.2: " + ("GARCH liegt auch vor EWMA (p < 0,05), GARCH ist die Empfehlung."
                                           if val["dm_ewma"]["mean"] > 0 and ewma_p < 0.05
                                           else "GARCH liegt nicht klar vor EWMA, Empfehlung ist EWMA als einfachere Wahl."))
        lines.append("")
    lines += ["Beschreibend (ohne Urteil): EWMA und MSE. Ausgelassen sind Perioden mit RV = 0 oder einer Prognose ≤ 0.",
              "", f"Holdout 2025+ nicht geladen. {UNIVERSE_LIMITATION}"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["count", "run"])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--out", type=Path, default=Path("docs/research_lab/reports"))
    args = parser.parse_args(argv)
    if args.command == "run":
        return run(ArchiveStore(args.root), args.out)
    return count(ArchiveStore(args.root), args.out)


if __name__ == "__main__":
    raise SystemExit(main())
