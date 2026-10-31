"""F7: shadow operation of a candidate update, on the learning register (src/research_lab/learning/registry.py).

A study whose report says ``candidate`` may run as a shadow for 30 days before anything changes:

1. ``start``: one family per study (``<study>-schatten``) with fixed rules, the baseline champion
   ``kein-trade`` (0 R per trade) and the candidate as challenger. Its window starts one horizon after
   the announcement and lasts ``SHADOW_WINDOW_DAYS``; the register refuses back- and forward-dating.
2. ``record_plan`` / ``record_outcome``: the candidate's plans go into its own append-only shadow journal
   (``data/research/shadow/<study>.jsonl``, hash chain, own id ``schatten:<study>``). A plan is written
   with the real clock before its outcome exists, only inside the window; each plan gets at most one
   outcome, dated after the plan. Shadow plans never enter the paper journal and never count in net R.
3. ``evaluate``: after the window, once: mean net R per trade of the shadow minus 0 R, with a bootstrap
   interval at ``CI_LEVEL``; the register computes the verdict (ELIGIBLE / REJECTED / NO_VERDICT).
4. A promotion stays Uzi's decision (``approvers = ["Uzi"]``), via the register's ``promote``.

Paper only. Nothing here trades, changes a live rule or touches a risk limit.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from src.research_lab.learning.registry import ModelRegister
from src.research_lab.workshop import charter

SHADOW_DIR = Path("data/research/shadow")
REGISTER_PATH = SHADOW_DIR / "register.jsonl"
SCHEMA = "tim_shadow_journal/1"
GENESIS = "0" * 64
BASELINE = "kein-trade"
CI_LEVEL = 0.995
BOOTSTRAP_DRAWS = 4000
MAX_GAP_SHARE = 0.10          # more outcomes with a data gap than this: data quality gate not passed
CLOCK_TOLERANCE = timedelta(minutes=15)
METRIC = "net_r_per_trade"
DIRECTIONS = {"LONG", "SHORT"}


class ShadowError(ValueError):
    pass


def _time(value: Any) -> datetime:
    moment = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if moment.tzinfo is None:
        raise ShadowError(f"Zeit ohne Zone: {value}")
    return moment.astimezone(timezone.utc)


def _iso(value: Any) -> str:
    return _time(value).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ShadowError(f"{name} muss eine endliche Zahl sein")
    return float(value)


def _digest(previous: str, body: Mapping[str, Any]) -> str:
    return hashlib.sha256((previous + json.dumps(body, sort_keys=True, ensure_ascii=False)).encode("utf-8")).hexdigest()


def family_name(study: str) -> str:
    return f"{study}-schatten"


def journal_id(study: str) -> str:
    return f"schatten:{study}"


# -- register bridge -----------------------------------------------------------------------------

def start(register: ModelRegister, study: str, *, model_id: str, variant_hash: str, code_commit: str,
          study_version: str, cost_rule: str, min_trades: int, min_effect: float, horizon_minutes: int,
          at: Any) -> dict[str, Any]:
    """Family, baseline and challenger in one go; returns the challenger entry (with its window)."""
    now = _time(at).replace(microsecond=0)
    family = family_name(study)
    prospective = now
    rules = {"config_id": variant_hash, "horizon_minutes": horizon_minutes, "min_window_days": charter.SHADOW_WINDOW_DAYS,
             "min_minutes": min_trades, "min_effect": min_effect, "ci_level": CI_LEVEL, "per_week": 1, "per_quarter": 2,
             "prospective_start": _iso(prospective), "metric": METRIC, "approvers": ["Uzi"]}
    register.register_family(family, rules, at=now)
    register.register_baseline(family, BASELINE, model_hash=hashlib.sha256(b"kein-trade: 0 R je Fall").hexdigest(),
                               at=now, note="Nullstrategie: kein Trade, 0 R")
    window_start = prospective + timedelta(minutes=horizon_minutes)
    return register.register_challenger(
        family, model_id, at=now, trained_until=prospective, window_start=window_start,
        window_end=window_start + timedelta(days=charter.SHADOW_WINDOW_DAYS),
        data_sources=[{"kind": "live", "from": _iso(prospective), "to": _iso(prospective)}], config_id=variant_hash,
        code_commit=code_commit, feature_version=study_version, label_version=cost_rule,
        data_hash=hashlib.sha256(f"live ab {_iso(prospective)}".encode()).hexdigest(), model_hash=variant_hash)


def challenger(register: ModelRegister, model_id: str) -> dict[str, Any]:
    model = register.state()["models"].get(model_id)
    if model is None:
        raise ShadowError(f"{model_id} ist kein angemeldeter Herausforderer")
    return model


# -- shadow journal ------------------------------------------------------------------------------

class ShadowJournal:
    """Append-only plans and outcomes of one shadow candidate. Separate from the paper journal on purpose."""

    def __init__(self, study: str, model_id: str, *, folder: Path | str = SHADOW_DIR,
                 clock: Callable[[], datetime] | None = None) -> None:
        self.study, self.model_id = study, model_id
        self.path = Path(folder) / f"{study}.jsonl"
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def events(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        events, previous = [], GENESIS
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            body = {k: v for k, v in event.items() if k != "hash"}
            if body.get("previous") != previous or event.get("hash") != _digest(previous, body):
                raise ShadowError(f"Schatten-Journal {self.path.name}: Hash-Kette gebrochen")
            previous = event["hash"]
            events.append(event)
        return events

    def _append(self, body: dict[str, Any]) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            events = self.events()
            previous = events[-1]["hash"] if events else GENESIS
            body = {**body, "schema": SCHEMA, "journal": journal_id(self.study), "model_id": self.model_id,
                    "counts_in_net_r": False, "previous": previous}
            event = {**body, "hash": _digest(previous, body)}
            handle.write(json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n")
        return event

    def plans(self) -> dict[str, dict[str, Any]]:
        plans: dict[str, dict[str, Any]] = {}
        for event in self.events():
            if event["kind"] == "plan":
                plans[event["plan_id"]] = {**event, "outcome": None}
            elif event["kind"] == "outcome":
                plans[event["plan_id"]]["outcome"] = event
        return plans

    def record_plan(self, register: ModelRegister, plan_id: str, *, decided_at: Any, direction: str, entry: float,
                    stop: float, targets: Sequence[float], inputs_hash: str, note: str = "") -> dict[str, Any]:
        model = challenger(register, self.model_id)
        now, decided = _time(self.clock()), _time(decided_at)
        if model["verdict"] is not None:
            raise ShadowError(f"{self.model_id} ist schon bewertet; das Fenster ist verbraucht")
        if not _time(model["window_start"]) <= decided < _time(model["window_end"]):
            raise ShadowError("Plan liegt außerhalb des angemeldeten Fensters")
        if abs(now - decided) > CLOCK_TOLERANCE:
            raise ShadowError("Plan muss zur Entscheidungszeit geschrieben werden (keine Nachträge)")
        if plan_id in self.plans():
            raise ShadowError(f"Plan {plan_id} steht schon im Schatten-Journal")
        if direction not in DIRECTIONS:
            raise ShadowError(f"Richtung {direction!r} unbekannt")
        if not str(inputs_hash or "").strip():
            raise ShadowError("inputs_hash ist Pflicht (welche Live-Daten der Plan sah)")
        levels = [_finite(entry, "entry"), _finite(stop, "stop"), *(_finite(t, "target") for t in targets)]
        return self._append({"kind": "plan", "plan_id": plan_id, "at": _iso(now), "decided_at": _iso(decided),
                             "direction": direction, "entry": levels[0], "stop": levels[1], "targets": levels[2:],
                             "inputs_hash": inputs_hash, "note": note})

    def record_outcome(self, plan_id: str, *, closed_at: Any, net_r: float, gross_r: float, cost_r: float,
                       exit_reason: str, data_gap: bool = False) -> dict[str, Any]:
        plans = self.plans()
        if plan_id not in plans:
            raise ShadowError(f"Plan {plan_id} steht nicht im Schatten-Journal")
        if plans[plan_id]["outcome"] is not None:
            raise ShadowError(f"Plan {plan_id} hat schon ein Ergebnis")
        now, closed = _time(self.clock()), _time(closed_at)
        if closed < _time(plans[plan_id]["at"]) or closed > now + CLOCK_TOLERANCE:
            raise ShadowError("Ergebnis muss nach dem Plan und nicht in der Zukunft liegen")
        return self._append({"kind": "outcome", "plan_id": plan_id, "at": _iso(now), "closed_at": _iso(closed),
                             "net_r": _finite(net_r, "net_r"), "gross_r": _finite(gross_r, "gross_r"),
                             "cost_r": _finite(cost_r, "cost_r"), "exit_reason": str(exit_reason),
                             "data_gap": bool(data_gap)})


# -- evaluation ----------------------------------------------------------------------------------

def bootstrap_interval(values: Sequence[float], level: float = CI_LEVEL, draws: int = BOOTSTRAP_DRAWS,
                       seed: int = 0) -> tuple[float, float]:
    """Percentile bootstrap of the mean (standard library only; numpy is not a TIM dependency)."""
    import random
    data = [float(v) for v in values]
    if not data:
        return 0.0, 0.0
    rng, size = random.Random(seed), len(data)
    means = sorted(sum(rng.choices(data, k=size)) / size for _ in range(draws))
    tail = (1 - level) / 2
    low = means[max(0, min(draws - 1, int(math.floor(tail * (draws - 1)))))]
    high = means[max(0, min(draws - 1, int(math.ceil((1 - tail) * (draws - 1)))))]
    return low, high


def metrics(register: ModelRegister, journal: ShadowJournal, *, seed: int = 0) -> dict[str, Any]:
    model = challenger(register, journal.model_id)
    start_, end = _time(model["window_start"]), _time(model["window_end"])
    plans = [p for p in journal.plans().values() if start_ <= _time(p["decided_at"]) < end]
    closed = [p["outcome"] for p in plans if p["outcome"] is not None]
    values = [o["net_r"] for o in closed if not o["data_gap"]]
    gaps = sum(o["data_gap"] for o in closed)
    open_plans = len(plans) - len(closed)
    delta = sum(values) / len(values) if values else 0.0
    low, high = bootstrap_interval(values, seed=seed)
    low, high = min(low, delta), max(high, delta)
    return {"n_minutes": len(values), "days": (end - start_).total_seconds() / 86400, "delta": delta,
            "ci_low": low, "ci_high": high, "ci_level": CI_LEVEL, "calibration_ok": True,
            "quality_ok": open_plans == 0 and (not closed or gaps / len(closed) <= MAX_GAP_SHARE),
            "plans": len(plans), "open_plans": open_plans, "data_gaps": gaps, "metric": METRIC,
            "register_head": register.head()}


def evaluate(register: ModelRegister, journal: ShadowJournal, *, at: Any, seed: int = 0) -> dict[str, Any]:
    """Once, after the window: the register refuses a second evaluation and an early one."""
    return register.record_evaluation(journal.model_id, metrics(register, journal, seed=seed), at=at)


def status(register: ModelRegister, folder: Path | str = SHADOW_DIR) -> list[dict[str, Any]]:
    """Read only, for the logbook, the monthly reflection and F9."""
    state = register.state()
    rows = []
    for model_id, model in sorted(state["models"].items()):
        family = model["family"]
        if not family.endswith("-schatten"):
            continue
        study = family[: -len("-schatten")]
        plans = ShadowJournal(study, model_id, folder=folder).plans()
        rows.append({"study": study, "model_id": model_id, "window_start": model["window_start"],
                     "window_end": model["window_end"], "verdict": model["verdict"],
                     "champion": state["families"][family]["champion"], "plans": len(plans),
                     "closed": sum(p["outcome"] is not None for p in plans.values())})
    return rows
