"""Frozen, paired S8 feature ablation. Lab only; no DB and no holdout permission path.

Run plan -> fetch -> export -> compare. The monthly eight-day cohort is selected
from dates alone, before market data are fetched. It is a sampled historical
development comparison, not the full S8 history or a confirmatory live test.
"""
from __future__ import annotations

import argparse
import calendar
import csv
import hashlib
import json
import platform
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from src.research_lab.orderflow_ml.export import ExportConfig, run_export
from src.research_lab.orderflow_ml.features import BASE_FEATURE_NAMES, FEATURE_NAMES, SEQUENCE_FEATURE_NAMES
from src.research_lab.orderflow_ml.labels import LabelConfig
from src.research_lab.orderflow_ml.store import MinuteBarStore, day_start_ms, guard, sha256_file

SEED = 20261028
STUDY_VERSION = "s8-sequence-ablation-1.0.0"
CLASS_NAMES = ("down", "neutral", "up")


def cohort_days() -> list[date]:
    """One rotating eight-day block in every month, 2020-2024 only; no outcome-based selection."""
    result = []
    for year in range(2020, 2025):
        for month in range(1, 13):
            key = f"{STUDY_VERSION}:{SEED}:{year:04d}-{month:02d}"
            first = 1 + int(hashlib.sha256(key.encode()).hexdigest()[:16], 16) % (calendar.monthrange(year, month)[1] - 7)
            result.extend(date(year, month, first) + timedelta(days=i) for i in range(8))
    for day in result:
        guard(day)
    return result


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def make_plan(min_relative_gain: float = 0.01) -> dict:
    if not 0 <= min_relative_gain < 1:
        raise ValueError("min_relative_gain must lie in [0, 1)")
    return {
        "version": STUDY_VERSION, "seed": SEED,
        "cohort": [d.isoformat() for d in cohort_days()],
        "cohort_scope": "date-only rotating 8-day block per month; first day provides previous-day profiles",
        "train": ["2020-01-01", "2022-12-31"], "validation": ["2023-01-01", "2024-12-31"],
        "holdout": "LOCKED; dates >= 2025-01-01 are never fetched or read",
        "baseline_features": list(BASE_FEATURE_NAMES), "extended_features": list(FEATURE_NAMES),
        "added_features": list(SEQUENCE_FEATURE_NAMES), "label": asdict(LabelConfig()),
        "primary_model": "catboost", "secondary_model": "logistic_descriptive_only",
        "catboost": {"iterations": 500, "depth": 4, "learning_rate": 0.05, "loss_function": "MultiClass",
                     "thread_count": 2, "random_seed": SEED, "verbose": False, "allow_writing_files": False},
        "logistic": {"C": 1.0, "solver": "lbfgs", "max_iter": 1000, "tol": 1e-6, "random_state": SEED},
        "primary_metric": "paired relative validation log-loss reduction (baseline - extended) / baseline",
        "practical_min_relative_gain": min_relative_gain,
        "uncertainty": {"cluster": "calendar month; complete paired sampled block", "bootstrap": 4000,
                        "confidence": 0.95, "minimum_validation_clusters": 24},
        "quality": "exclude id gaps/time regressions; common complete feature and valid-label rows for both models",
        "stopping": "one fixed cohort and two fixed model pairs; no tuning, early stopping or extension after outcomes",
        "limitations": ["historical development comparison only", "no prior trained baseline checkpoint exists",
                        "not a net-return/fill test", "no prospective confirmation or trading approval",
                        "finite block cohort; no claim of full-history coverage or a priori achieved power"],
    }


def write_plan(out: Path, min_relative_gain: float) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    path = out / "plan.json"
    plan = make_plan(min_relative_gain)
    if path.exists():
        existing = json.loads(path.read_text())
        if existing["plan"] != plan:
            raise ValueError("frozen plan differs; use a new study directory, never overwrite")
        return existing
    envelope = {"plan": plan, "plan_sha256": digest(plan),
                "frozen_utc": datetime.now(timezone.utc).isoformat()}
    with path.open("x") as handle:
        json.dump(envelope, handle, indent=2, sort_keys=True)
    return envelope


def read_plan(out: Path) -> dict:
    envelope = json.loads((out / "plan.json").read_text())
    plan = envelope["plan"]
    if digest(plan) != envelope["plan_sha256"] or plan != make_plan(plan["practical_min_relative_gain"]):
        raise ValueError("plan hash or frozen specification mismatch")
    # Validate ALL paths/dates before any archive or feature file can be opened.
    for day in plan["cohort"]:
        guard(date.fromisoformat(day))
    return envelope


def _prepare_day(root_day: tuple[str, str]) -> tuple[str, dict]:
    root, iso = root_day
    day = date.fromisoformat(iso)
    guard(day)
    store = MinuteBarStore(root)
    return iso, store.cached(day) or store.prepare(day)


def fetch_cohort(root: Path, out: Path, workers: int = 4) -> None:
    envelope = read_plan(out)
    if not 1 <= workers <= 4:
        raise ValueError("use between one and four download/reduction workers")
    store = MinuteBarStore(root)
    days = envelope["plan"]["cohort"]
    errors = {}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(_prepare_day, (str(root), d)): d for d in days}
        for n, future in enumerate(as_completed(pending), 1):
            try:
                iso, entry = future.result()
            except Exception as exc:
                errors[pending[future]] = f"{type(exc).__name__}: {exc}"
                print(json.dumps({"day": pending[future], "error": errors[pending[future]]}), flush=True)
                continue
            store.record(date.fromisoformat(iso), entry)  # manifest has a single writer
            print(json.dumps({"done": n, "total": len(days), "day": iso, "quality": entry["quality"]}), flush=True)
    if errors:
        (out / "fetch_errors.json").write_text(json.dumps(errors, indent=2, sort_keys=True))
        raise RuntimeError(f"{len(errors)} planned days failed; retry the same cohort, never substitute dates")


class CohortStore(MinuteBarStore):
    def __init__(self, root: Path, allowed: set[date]):
        super().__init__(root)
        self.allowed = allowed

    def present_days(self) -> list[date]:
        manifest = self.manifest()
        return [d for d in super().present_days() if d in self.allowed and
                not any(manifest[d.isoformat()]["quality"].get(k, 0) for k in ("id_gaps", "time_regressions"))]


def export_cohort(root: Path, out: Path, code_version: str) -> dict:
    envelope = read_plan(out)
    days = {date.fromisoformat(d) for d in envelope["plan"]["cohort"]}
    manifest = MinuteBarStore(root).manifest()
    missing = sorted(d.isoformat() for d in days if d.isoformat() not in manifest)
    if missing:
        raise ValueError(f"incomplete planned cohort: {len(missing)} missing days; no result-dependent substitution")
    split = run_export(CohortStore(root, days), ExportConfig(), out / "exports", code_version=code_version)
    split["sequence_plan_sha256"] = envelope["plan_sha256"]
    split["planned_days"] = len(days)
    split["scheduled_absences"] = "nonselected dates in the full export interval are intentional, not capture outages"
    path = out / "exports" / split["export_id"] / "split_manifest.json"
    path.write_text(json.dumps(split, indent=2, sort_keys=True) + "\n")
    (out / "export_path.txt").write_text(str(path.parent.resolve()))
    print(json.dumps({"export_id": split["export_id"], "sections": split["sections"]}), flush=True)
    return split


def load_dataset(export_dir: Path, envelope: dict):
    import numpy as np
    manifest = json.loads((export_dir / "split_manifest.json").read_text())
    if manifest.get("sequence_plan_sha256") != envelope["plan_sha256"]:
        raise ValueError("export does not belong to the frozen plan")
    if manifest["config"]["features"] != list(FEATURE_NAMES) or manifest["config"]["label"] != envelope["plan"]["label"]:
        raise ValueError("feature or label contract mismatch")
    planned = set(envelope["plan"]["cohort"])
    days = sorted(manifest["days"])
    for iso in days:
        guard(date.fromisoformat(iso))
        if iso not in planned:
            raise ValueError("unexpected day in export")
    data = {s: {"x": [], "y": [], "day": [], "decision_ms": []} for s in ("train", "validation")}
    for iso in days:
        entry = manifest["days"][iso]
        fpath, lpath = (export_dir / kind / f"BTCUSDT-{iso}.csv" for kind in ("features", "labels"))
        if sha256_file(fpath) != entry["features_sha256"] or sha256_file(lpath) != entry["labels_sha256"]:
            raise ValueError("export file hash mismatch")
        expected = "train" if iso < "2023-01-01" else "validation"
        with fpath.open() as f, lpath.open() as lab:
            for row, label in zip(csv.DictReader(f), csv.DictReader(lab), strict=True):
                if row["decision_ms"] != label["decision_ms"] or row["section"] != expected or label["section"] != expected:
                    raise ValueError("unpaired or incorrectly split rows")
                stamp = int(row["decision_ms"])
                start = day_start_ms(date.fromisoformat(iso))
                if not start < stamp <= start + 86_400_000 or stamp % 60_000:
                    raise ValueError("decision time does not belong to its declared UTC day")
                # The final Dec-2024 decision may be midnight Jan-2025; its minute belongs to
                # Dec-2024, but its label is purged before any future target is read.
                if row["complete"] != "1" or label["status"] != "ok":
                    continue
                values = [float(row[k]) for k in FEATURE_NAMES]
                if not np.isfinite(values).all():
                    raise ValueError("nonfinite feature")
                end = 1672531200000 if expected == "train" else 1735689600000
                if stamp + 5 * 60_000 > end:
                    raise ValueError("label would cross a split or holdout boundary")
                dest = data[expected]
                dest["x"].append(values)
                dest["y"].append(CLASS_NAMES.index(label["label"]))
                dest["day"].append(iso)
                dest["decision_ms"].append(stamp)
    for dest in data.values():
        for k in dest:
            dest[k] = np.asarray(dest[k], dtype=np.float64 if k == "x" else None)
    if not all(len(data[s]["y"]) for s in data):
        raise ValueError("empty training or validation data")
    if set(data["train"]["y"].tolist()) != {0, 1, 2}:
        raise ValueError("training lacks a class")
    return data, manifest


def per_row_scores(y, probability):
    import numpy as np
    p = np.asarray(probability, dtype=float)
    if p.shape != (len(y), 3) or not np.isfinite(p).all() or (p < 0).any() or not np.allclose(p.sum(axis=1), 1):
        raise ValueError("invalid class probabilities")
    p = np.clip(p, 1e-12, 1)
    p /= p.sum(axis=1, keepdims=True)
    loss = -np.log(p[np.arange(len(y)), y])
    brier = ((p - np.eye(3)[y]) ** 2).sum(axis=1)
    return loss, {"log_loss": float(loss.mean()), "brier": float(brier.mean()),
                  "accuracy": float((p.argmax(axis=1) == y).mean())}


def paired_month_bootstrap(base_loss, extended_loss, days, *, replicates: int = 4000, seed: int = SEED) -> dict:
    import numpy as np
    base_loss, extended_loss = np.asarray(base_loss), np.asarray(extended_loss)
    if (len(base_loss) != len(extended_loss) or len(base_loss) != len(days) or replicates < 1
            or not np.isfinite(base_loss).all() or not np.isfinite(extended_loss).all()
            or (base_loss < 0).any() or (extended_loss < 0).any() or base_loss.sum() <= 0):
        raise ValueError("bootstrap requires finite, paired nonnegative losses and a positive baseline loss")
    months = np.asarray([str(d)[:7] for d in days])
    keys = sorted(set(months.tolist()))
    if not keys:
        raise ValueError("no paired validation clusters")
    sums = np.asarray([[float(base_loss[months == k].sum()), float(extended_loss[months == k].sum()),
                        int((months == k).sum())] for k in keys])
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(keys), size=(replicates, len(keys)))
    totals = sums[indices].sum(axis=1)
    draws = (totals[:, 0] - totals[:, 1]) / totals[:, 0]
    return {"relative_gain": float((sums[:, 0].sum() - sums[:, 1].sum()) / sums[:, 0].sum()),
            "ci95": np.quantile(draws, [0.025, 0.975]).tolist(), "clusters": len(keys),
            "monthly": {k: {"rows": int(n), "baseline_log_loss": float(b / n), "extended_log_loss": float(e / n),
                            "relative_gain": float((b-e)/b)} for k, (b, e, n) in zip(keys, sums)}}


def compare(out: Path) -> dict:
    # Read/validate guards before importing fitting libraries or opening feature files.
    envelope = read_plan(out)
    if (out / "result.json").exists():
        raise FileExistsError("do not overwrite an observed result; use a separate versioned run")
    export_dir = Path((out / "export_path.txt").read_text().strip())
    data, manifest = load_dataset(export_dir, envelope)
    import numpy as np
    import sklearn
    import catboost
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from threadpoolctl import threadpool_limits

    cfg = envelope["plan"]
    tr, va = data["train"], data["validation"]
    nbase = len(BASE_FEATURE_NAMES)
    results = {}
    prediction_dir = out / "predictions"
    prediction_dir.mkdir(exist_ok=True)
    prior = np.bincount(tr["y"], minlength=3) / len(tr["y"])
    _, prior_metrics = per_row_scores(va["y"], np.tile(prior, (len(va["y"]), 1)))
    for family in ("catboost", "logistic"):
        paired = {}
        for variant, width in (("baseline", nbase), ("sequence", len(FEATURE_NAMES))):
            print(f"Fitting {family}/{variant}: {len(tr['y'])} train / {len(va['y'])} validation rows", flush=True)
            if family == "catboost":
                model = catboost.CatBoostClassifier(**cfg["catboost"])
            else:
                model = make_pipeline(StandardScaler(), LogisticRegression(**cfg["logistic"]))
            with threadpool_limits(limits=2):
                model.fit(tr["x"][:, :width], tr["y"])
                probabilities = model.predict_proba(va["x"][:, :width])
            if list(model.classes_) != [0, 1, 2]:
                raise ValueError("model class order mismatch")
            loss, metrics = per_row_scores(va["y"], probabilities)
            if family == "logistic":
                iterations = model.named_steps["logisticregression"].n_iter_
                metrics["iterations"] = iterations.tolist()
                metrics["converged"] = bool((iterations < cfg["logistic"]["max_iter"]).all())
            paired[variant] = {"loss": loss, "metrics": metrics}
            path = prediction_dir / f"{family}-{variant}.npz"
            np.savez_compressed(path, probabilities=probabilities, y=va["y"], decision_ms=va["decision_ms"], day=va["day"])
            if family == "catboost":
                model.save_model(str(out / f"{family}-{variant}.cbm"))
            else:
                import joblib
                joblib.dump(model, out / f"{family}-{variant}.joblib")
        stats = paired_month_bootstrap(paired["baseline"]["loss"], paired["sequence"]["loss"], va["day"],
                                       replicates=cfg["uncertainty"]["bootstrap"])
        results[family] = {"baseline": paired["baseline"]["metrics"], "sequence": paired["sequence"]["metrics"], **stats}
    primary = results["catboost"]
    low, high = primary["ci95"]
    minimum = cfg["practical_min_relative_gain"]
    if primary["clusters"] < cfg["uncertainty"]["minimum_validation_clusters"]:
        verdict = "INSUFFICIENT_MONTH_CLUSTERS"
    elif low > minimum:
        verdict = "PRACTICAL_IMPROVEMENT_IN_SAMPLED_VALIDATION"
    elif low > 0:
        verdict = "MEASURABLE_GAIN_PRACTICAL_SIZE_UNCONFIRMED"
    elif high < 0:
        verdict = "WORSE_IN_SAMPLED_VALIDATION"
    elif high < minimum:
        verdict = "NO_PRACTICAL_GAIN_DEMONSTRATED"
    else:
        verdict = "INCONCLUSIVE"
    result = {"study": STUDY_VERSION, "created_utc": datetime.now(timezone.utc).isoformat(),
              "plan_sha256": envelope["plan_sha256"], "export_manifest_sha256": sha256_file(export_dir / "split_manifest.json"),
              "input_dataset_hash": manifest["input_dataset_hash"], "features_hash": manifest["features_hash"],
              "labels_hash": manifest["labels_hash"], "code_version": manifest["code_version"],
              "versions": {"python": platform.python_version(), "numpy": np.__version__, "sklearn": sklearn.__version__,
                           "catboost": catboost.__version__},
              "cohort": {s: {"rows": len(d["y"]), "days": len(set(d["day"].tolist()))} for s, d in data.items()},
              "class_prior_baseline": prior_metrics, "models": results, "verdict": verdict,
              "holdout": "NOT_FETCHED_NOT_READ", "limitations": cfg["limitations"]}
    path = out / "result.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    (out / "result.md").write_text(render_report(result, minimum))
    print(json.dumps({"verdict": verdict, "primary": primary, "cohort": result["cohort"]}, indent=2), flush=True)
    return result


def render_report(result: dict, minimum: float) -> str:
    lines = ["# S8: Drei Sequenzmerkmale im direkten Vergleich", "", f"Urteil: **{result['verdict']}**.", "",
             "Historischer Stichprobenvergleich, keine prospektive Bestätigung und kein Nachweis eines Handelsgewinns.",
             "Holdout ab 2025-01-01 wurde weder abgerufen noch gelesen.", "",
             f"Vorab festgelegte praktische Schwelle: {minimum:.2%} relative Log-Loss-Verbesserung.", "",
             "| Modell | bisherige 35 Merkmale | 38 Merkmale | relative Verbesserung | 95%-Intervall |", "|---|---:|---:|---:|---|" ]
    for family, r in result["models"].items():
        lines.append(f"| {family} | {r['baseline']['log_loss']:.8f} | {r['sequence']['log_loss']:.8f} | {r['relative_gain']:.3%} | {r['ci95'][0]:.3%} bis {r['ci95'][1]:.3%} |")
    lines += ["", "Primärmodell: CatBoost; logistische Regression nur ergänzend. Beide Varianten sehen dieselben Zeilen und Labels.",
              "Unsicherheit: gepaarter Bootstrap ganzer Monatsblöcke; keine Annahme unabhängiger Minuten.",
              "Die 480 Archivtagesdateien wurden nach Kalender/Hash ausgewählt; nicht die vollständige Historie.", "",
              f"Datenumfang: `{json.dumps(result['cohort'], sort_keys=True)}`.",
              f"Klassen-Basisrate, Validierungs-Log-Loss: {result['class_prior_baseline']['log_loss']:.8f}.", "",
              f"Plan-Hash: `{result['plan_sha256']}`", f"Daten-Hash: `{result['input_dataset_hash']}`",
              f"Merkmals-Hash: `{result['features_hash']}`", f"Label-Hash: `{result['labels_hash']}`",
              f"Code: `{result['code_version']}`", f"Paketversionen: `{json.dumps(result['versions'], sort_keys=True)}`", "",
              "## Grenzen", "", *[f"- {v}" for v in result["limitations"]], "",
              "Die Konfidenzgrenzen beschreiben diesen endlichen historischen Vergleich. Sie ersetzen keine vorab begründete Power für eine prospektive Bestätigung.", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "fetch", "export", "compare"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--min-relative-gain", type=float, default=0.01)
    parser.add_argument("--code-version", default="unknown")
    args = parser.parse_args(argv)
    if args.command == "plan":
        print(json.dumps(write_plan(args.out, args.min_relative_gain), indent=2))
    elif args.command == "fetch":
        fetch_cohort(args.root, args.out)
    elif args.command == "export":
        export_cohort(args.root, args.out, args.code_version)
    else:
        compare(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
