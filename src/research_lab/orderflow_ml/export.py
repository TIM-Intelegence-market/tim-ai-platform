"""Versioned feature/label export with split manifest, exclusion report and replay.

Per decision minute of a day the export writes one feature row and, in a
separate file, one label row. The feature computation looks back at most to
the start of the previous day (``day_window``); the label looks at most
``horizon`` minutes into the next day. Splits follow the lab protocol
(training until 2022, validation 2023-2024); a row whose label horizon crosses
a section end is purged, so no training label reads a validation price. The
holdout is never loaded.

The quality report counts label *statuses* only. The class distribution and
any outcome statistic stay unreported until the study is registered.
"""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from src.research_lab.orderflow_ml.bars import BAR_VERSION, MINUTE_MS, DayProfile, MinuteBar
from src.research_lab.orderflow_ml.features import FEATURE_NAMES, FEATURE_VERSION, QUALITY_NAMES, TIME_BASIS, WARMUP_BARS, BarSeries, FeatureRow, features_at
from src.research_lab.orderflow_ml.labels import LABEL_VERSION, OK, LabelConfig, LabelRow, label_at
from src.research_lab.orderflow_ml.store import HOLDOUT_DAY, MinuteBarStore, day_start_ms, days_between, guard, sha256_file
from src.research_lab.protocol import HOLDOUT_START_MS, PROTOCOL_VERSION, VALIDATION_START_MS

STUDY = "S8"
EXPORT_SCHEMA = "1.0.0"
TRAIN_START = date(2020, 1, 1)
SECTIONS: dict[str, tuple[int, int]] = {
    "train": (day_start_ms(TRAIN_START), VALIDATION_START_MS),
    "validation": (VALIDATION_START_MS, HOLDOUT_START_MS),
}
FEATURE_HEADER = ["decision_ms", "section", "warm", "complete", *QUALITY_NAMES, *FEATURE_NAMES]
LABEL_HEADER = ["decision_ms", "section", "status", "start_price_e8", "target_price_e8", "log_return", "threshold", "label"]
EXCLUSION_ORDER = ("warmup", "incomplete_features", "purged_section_end", "stale_start", "stale_target", "beyond_data", "no_volatility")


@dataclass(frozen=True, slots=True)
class ExportConfig:
    first_day: date = TRAIN_START
    last_day: date = date(2024, 12, 31)
    symbol: str = "BTCUSDT"
    label: LabelConfig = field(default_factory=LabelConfig)

    def __post_init__(self) -> None:
        if self.last_day < self.first_day:
            raise ValueError("last_day before first_day")
        if self.last_day >= HOLDOUT_DAY:
            raise ValueError("the export ends before the holdout (2025-01-01)")
        if day_start_ms(self.first_day) < SECTIONS["train"][0]:
            raise ValueError("the export starts at the training start 2020-01-01 or later")

    def as_dict(self) -> dict:
        return {"study": STUDY, "schema": EXPORT_SCHEMA, "protocol": PROTOCOL_VERSION, "bar_version": BAR_VERSION,
                "feature_version": FEATURE_VERSION, "label_version": LABEL_VERSION, "time_basis": TIME_BASIS,
                "first_day": self.first_day.isoformat(), "last_day": self.last_day.isoformat(), "symbol": self.symbol,
                "label": asdict(self.label), "warmup_bars": WARMUP_BARS,
                "sections": {k: list(v) for k, v in SECTIONS.items()}, "features": list(FEATURE_NAMES)}

    def config_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.as_dict(), sort_keys=True).encode()).hexdigest()

    def export_id(self) -> str:
        return f"s8-f{FEATURE_VERSION}-l{LABEL_VERSION}-{self.config_hash()[:12]}"


def section_of(window_start_ms: int) -> str:
    for name, (start, end) in SECTIONS.items():
        if start <= window_start_ms < end:
            return name
    raise ValueError("minute outside training and validation")


def purged(decision_ms: int, cfg: LabelConfig, section: str) -> bool:
    return decision_ms + cfg.horizon_min * MINUTE_MS > SECTIONS[section][1]


ProfileLoader = Callable[[date], DayProfile]


def day_window(load: Callable[[date], list[MinuteBar]], day: date, present: set[date], horizon_min: int,
               load_profile: ProfileLoader | None = None) -> tuple[BarSeries, int]:
    """Bars of the previous day (if present), the day, and the first minutes of the next day (if present).

    Profiles of the previous day and the day itself feed the Volume-Profile/TPO features; the next
    day's profile is never loaded.
    """
    from datetime import timedelta

    prev, nxt = day - timedelta(days=1), day + timedelta(days=1)
    bars: list[MinuteBar] = []
    offset = 0
    profiles: dict[int, DayProfile] = {}
    if prev in present:
        bars += load(prev)
        offset = len(bars)
        if load_profile is not None:
            profiles[day_start_ms(prev)] = load_profile(prev)
    if load_profile is not None:
        profiles[day_start_ms(day)] = load_profile(day)
    bars += load(day)
    if nxt in present and nxt < HOLDOUT_DAY:
        bars += load(nxt)[: horizon_min + 1]
    return BarSeries(bars, profiles), offset


def exclusion_reason(row: FeatureRow, label: LabelRow, is_purged: bool) -> str | None:
    if not row.warm:
        return "warmup"
    if not row.complete:
        return "incomplete_features"
    if is_purged:
        return "purged_section_end"
    if label.status != OK:
        return label.status
    return None


def _fmt(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return repr(value)
    return str(value)


@dataclass(slots=True)
class DayResult:
    features: list[list[str]]
    labels: list[list[str]]
    exclusions: Counter
    label_status: Counter
    rows: int


def export_day(load: Callable[[date], list[MinuteBar]], day: date, present: set[date], cfg: ExportConfig,
               load_profile: ProfileLoader | None = None) -> DayResult:
    series, offset = day_window(load, day, present, cfg.label.horizon_min, load_profile)
    features: list[list[str]] = []
    labels: list[list[str]] = []
    exclusions: Counter = Counter()
    statuses: Counter = Counter()
    for i in range(offset, offset + 1440):
        row = features_at(series, i)
        section = section_of(series.start[i])
        vol = row.values[FEATURE_NAMES.index("vol_60")]
        is_purged = purged(row.decision_ms, cfg.label, section)
        label = LabelRow(row.decision_ms, "purged_section_end") if is_purged else label_at(series, i, vol, cfg.label)
        statuses[label.status] += 1
        exclusions[exclusion_reason(row, label, is_purged) or "usable"] += 1
        features.append([_fmt(v) for v in (row.decision_ms, section, row.warm, row.complete, row.stale_ms, row.empty_minutes_60, *row.values)])
        labels.append([_fmt(v) for v in (label.decision_ms, section, label.status, label.start_price_e8, label.target_price_e8,
                                         label.log_return, label.threshold, label.label)])
    return DayResult(features, labels, exclusions, statuses, 1440)


def _write_csv(path: Path, header: list[str], rows: Iterable[list[str]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    return sha256_file(path)


def run_export(store: MinuteBarStore, cfg: ExportConfig, out_root: Path | str, *, code_version: str = "unknown") -> dict:
    """Write features, labels, split manifest and quality report for every present day in the range."""
    wanted = days_between(cfg.first_day, cfg.last_day)
    for day in wanted:
        guard(day)
    present = set(store.present_days()) & set(wanted)
    days = sorted(present)
    missing = [d for d in wanted if d not in present]
    out = Path(out_root) / cfg.export_id()
    cache: dict[date, list[MinuteBar]] = {}

    def load(day: date) -> list[MinuteBar]:
        if day not in cache:
            if len(cache) > 3:
                cache.pop(min(cache))
            cache[day] = store.load(day)
        return cache[day]

    per_day: dict[str, dict] = {}
    sections: dict[str, dict] = {name: {"days": 0, "rows": 0, "exclusions": Counter(), "label_status": Counter(),
                                        "bar_quality": Counter()} for name in SECTIONS}
    manifest_bars = store.manifest()
    for day in days:
        result = export_day(load, day, present, cfg, store.load_profile)
        name = section_of(day_start_ms(day))
        f_sha = _write_csv(out / "features" / f"{cfg.symbol}-{day.isoformat()}.csv", FEATURE_HEADER, result.features)
        l_sha = _write_csv(out / "labels" / f"{cfg.symbol}-{day.isoformat()}.csv", LABEL_HEADER, result.labels)
        per_day[day.isoformat()] = {"section": name, "features_sha256": f_sha, "labels_sha256": l_sha,
                                    "bars_sha256": manifest_bars[day.isoformat()]["bars_sha256"],
                                    "profile_sha256": manifest_bars[day.isoformat()]["profile_sha256"],
                                    "archive_sha256": manifest_bars[day.isoformat()]["archive_sha256"]}
        sec = sections[name]
        sec["days"] += 1
        sec["rows"] += result.rows
        sec["exclusions"].update(result.exclusions)
        sec["label_status"].update(result.label_status)
        sec["bar_quality"].update(manifest_bars[day.isoformat()].get("quality", {}))
    features_hash = hashlib.sha256(json.dumps(sorted((d, e["features_sha256"]) for d, e in per_day.items())).encode()).hexdigest()
    labels_hash = hashlib.sha256(json.dumps(sorted((d, e["labels_sha256"]) for d, e in per_day.items())).encode()).hexdigest()
    split = {
        "study": STUDY, "export_id": cfg.export_id(), "config_hash": cfg.config_hash(), "config": cfg.as_dict(),
        "code_version": code_version, "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "input_dataset_hash": store.dataset_hash(days) if days else None,
        "features_hash": features_hash, "labels_hash": labels_hash,
        "holdout": "nicht geladen (ab 2025-01-01 gesperrt)",
        "purge_rule": "Zeile entfällt, wenn t + Horizont hinter dem Abschnittsende liegt",
        "lookback_rule": "Merkmale lesen höchstens bis zum Beginn des Vortags zurück",
        "sections": {name: {"start_ms": SECTIONS[name][0], "end_ms": SECTIONS[name][1], "days": sec["days"], "rows": sec["rows"],
                             "usable_rows": sec["exclusions"].get("usable", 0),
                             "exclusions": dict(sorted(sec["exclusions"].items())),
                             "label_status": dict(sorted(sec["label_status"].items())),
                             "bar_quality": dict(sorted(sec["bar_quality"].items()))}
                     for name, sec in sections.items()},
        "missing_days": [d.isoformat() for d in missing],
        "days": per_day,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "split_manifest.json").write_text(json.dumps(split, indent=2, sort_keys=True) + "\n")
    (out / "quality_report.md").write_text(quality_report(split))
    return split


def quality_report(split: dict) -> str:
    lines = [f"# S8 Datenqualität und Ausschlüsse ({split['export_id']})", "",
             f"Erzeugt {split['created_utc']}, Code `{split['code_version']}`, Konfiguration `{split['config_hash'][:16]}…`.",
             f"Merkmals-Hash `{split['features_hash'][:16]}…`, Label-Hash `{split['labels_hash'][:16]}…`, "
             f"Eingangs-Hash `{(split['input_dataset_hash'] or '-')[:16]}…`.", "",
             "Ergebnisblind: Berichtet werden nur Zählungen von Datenqualität und Label-*Status*. "
             "Klassenverteilung, Renditen und jede Kennzahl über Ergebnisse bleiben bis zur Registrierung unberichtet. "
             "Holdout ab 2025-01-01 nicht geladen.", "",
             "| Abschnitt | Tage | Zeilen | nutzbar | " + " | ".join(EXCLUSION_ORDER) + " |",
             "|---|---|---|---|" + "---|" * len(EXCLUSION_ORDER)]
    for name, sec in split["sections"].items():
        ex = sec["exclusions"]
        lines.append(f"| {name} | {sec['days']} | {sec['rows']} | {sec['usable_rows']} | " + " | ".join(str(ex.get(k, 0)) for k in EXCLUSION_ORDER) + " |")
    lines += ["", "Rohdatenqualität je Abschnitt (aus der Reduktion):", ""]
    for name, sec in split["sections"].items():
        lines.append(f"- {name}: " + ", ".join(f"{k} {v}" for k, v in sec["bar_quality"].items()) if sec["bar_quality"] else f"- {name}: keine Tage")
    missing = split["missing_days"]
    lines += ["", f"Fehlende Tage: {len(missing)}" + (f" (erste: {', '.join(missing[:10])})" if missing else ""), ""]
    return "\n".join(lines)


def replay(store: MinuteBarStore, decision_ms: int, cfg: ExportConfig, export_dir: Path | str | None = None) -> dict:
    """Recompute one decision from the verified bar files and, if given, compare with the exported rows."""
    if decision_ms % MINUTE_MS:
        raise ValueError("decision_ms must be a minute boundary")
    minute_start = decision_ms - MINUTE_MS
    day = datetime.fromtimestamp(minute_start / 1000, tz=timezone.utc).date()
    guard(day)
    present = set(store.present_days()) & set(days_between(cfg.first_day, cfg.last_day))
    if day not in present:
        raise ValueError(f"{day} is not part of this export range or has not been fetched")
    series, offset = day_window(store.load, day, present, cfg.label.horizon_min, store.load_profile)
    i = offset + (minute_start - day_start_ms(day)) // MINUTE_MS
    row = features_at(series, i)
    section = section_of(minute_start)
    is_purged = purged(decision_ms, cfg.label, section)
    label = LabelRow(decision_ms, "purged_section_end") if is_purged else label_at(series, i, row.values[FEATURE_NAMES.index("vol_60")], cfg.label)
    entry = store.manifest()[day.isoformat()]
    result = {
        "decision_utc": datetime.fromtimestamp(decision_ms / 1000, tz=timezone.utc).isoformat(),
        "decision_ms": decision_ms, "section": section,
        "source": {"archive_url": entry["url"], "archive_sha256": entry["archive_sha256"], "bars_sha256": entry["bars_sha256"]},
        "last_bar_used": series.bars[i].as_row(),
        "features": dict(zip(FEATURE_NAMES, row.values)), "warm": row.warm, "complete": row.complete,
        "stale_ms": row.stale_ms, "label": asdict(label),
        "target_bar": series.bars[i + cfg.label.horizon_min].as_row() if i + cfg.label.horizon_min < len(series) else None,
    }
    if export_dir is not None:
        stem = f"{cfg.symbol}-{day.isoformat()}.csv"
        want_f = [_fmt(v) for v in (row.decision_ms, section, row.warm, row.complete, row.stale_ms, row.empty_minutes_60, *row.values)]
        want_l = [_fmt(v) for v in (label.decision_ms, section, label.status, label.start_price_e8, label.target_price_e8,
                                    label.log_return, label.threshold, label.label)]
        result["matches_export"] = _find(Path(export_dir) / "features" / stem, decision_ms) == want_f and \
            _find(Path(export_dir) / "labels" / stem, decision_ms) == want_l
    return result


def _find(path: Path, decision_ms: int) -> list[str] | None:
    with path.open(newline="") as handle:
        for row in csv.reader(handle):
            if row and row[0] == str(decision_ms):
                return row
    return None


def crosscheck_s2(store: MinuteBarStore, s2_store, days: Iterable[date]) -> dict:
    """Compare bars with the S2 count files (``agg/`` only; S2 ``px/`` is never opened).

    ``s2_store`` is an ``AggTradeDayStore``; its ``load_aggregates`` reads and verifies agg files only.
    """
    checked, mismatched = 0, []
    for day in days:
        ours = store.load(day)
        theirs = s2_store.load_aggregates(day)
        for bar, agg in zip(ours, theirs, strict=True):
            if (bar.window_start_ms, bar.trade_count, bar.buy_count, bar.buy_sats, bar.sell_sats, bar.largest_sats) != \
                    (agg.window_start_ms, agg.trade_count, agg.buy_count, agg.buy_sats, agg.sell_sats, agg.largest_sats):
                mismatched.append(day.isoformat())
                break
        checked += 1
    return {"days_checked": checked, "days_mismatched": mismatched}
