"""Model register of the learning loop L1: champion and challengers, append-only.

Study: docs/research_lab/studien/L1_LERNSCHLEIFE_PRAEREGISTRIERUNG.md. The register is a
JSON-lines file with the same hash chain as the hypothesis register (stats/register.py):
editing, deleting or reordering an old line breaks the chain and every read fails.

What the register enforces (fail closed, every refusal raises LearningError):

- A family fixes its rules once (configuration id, window size, smallest effect, budget,
  interval level, start of the prospective live data). Rules never change; new rules mean
  a new family, which is a new registration.
- A challenger is announced before its test window starts, was trained only on data up to
  its cut-off (plus the purge gap of the horizon), never on archive days from the holdout
  (2025-01-01 on) and never on live data from before the family's prospective start.
- Budget: at most `per_week` challengers per ISO week and `per_quarter` per quarter; every
  announced challenger counts, rejected ones included.
- Each challenger is evaluated exactly once, after its window has ended. The verdict is
  computed here from the reported numbers, not passed in.
- Promotion needs an ELIGIBLE verdict and a registered approver (Uzi's card). A rollback needs
  no approval, but only strictly backwards: to a champion that held before the current one
  first became champion. Going back is the safe direction; a demoted model never returns that way.
- Entries are dated with the real clock (15 minutes tolerance) and time never runs backwards:
  no back-dating to announce after a window was seen, no forward-dating to skip the wait.
- Numbers must be finite (NaN or infinity never pass a check); the budget counts per configuration
  across families; model ids are unique over the whole register.
- Cutting lines off the end leaves a valid chain; `head()` must therefore be anchored in git.

Paper only. Nothing here trains, predicts, trades or touches a risk limit.
"""
from __future__ import annotations

import fcntl
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from src.research_lab.protocol import HOLDOUT_START_MS
from src.research_lab.stats.register import GENESIS, _digest

REGISTER_VERSION = "learning-register/1"
HOLDOUT_START = datetime.fromtimestamp(HOLDOUT_START_MS / 1000, tz=timezone.utc)
ELIGIBLE, REJECTED, NO_VERDICT = "ELIGIBLE", "REJECTED", "NO_VERDICT"
RULE_KEYS = ("config_id", "horizon_minutes", "min_window_days", "min_minutes", "min_effect", "ci_level",
             "per_week", "per_quarter", "prospective_start", "metric", "approvers")
CLOCK_TOLERANCE = timedelta(minutes=15)  # an entry's date must match the real clock this closely


class LearningError(ValueError):
    pass


def _time(value: Any) -> datetime:
    if isinstance(value, datetime):
        moment = value
    else:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if moment.tzinfo is None:
        raise LearningError(f"time without zone: {value}")
    return moment.astimezone(timezone.utc)


def _iso(value: Any) -> str:
    return _time(value).isoformat().replace("+00:00", "Z")


def _number(value: Any, name: str) -> float:
    """A finite real number; bools, strings, NaN and infinity are refused."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise LearningError(f"{name} must be a finite number")
    return float(value)


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise LearningError(f"{name} must be a whole number of at least 1")
    return value


def _quarter(moment: datetime) -> tuple[int, int]:
    return moment.year, (moment.month - 1) // 3


class ModelRegister:
    def __init__(self, path: Path | str, *, clock: Any = None) -> None:
        self.path = Path(path)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    # -- file ---------------------------------------------------------------------------------
    def events(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            events = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except ValueError as error:
            raise LearningError(f"learning register is not valid JSON lines: {error}") from error
        previous = GENESIS
        for event in events:
            body = {k: v for k, v in event.items() if k != "hash"}
            if body.get("previous") != previous or event.get("hash") != _digest(previous, body):
                raise LearningError("learning register hash chain is broken; the file was edited")
            if event.get("register_version") != REGISTER_VERSION:
                raise LearningError(f"unknown register version {event.get('register_version')}")
            previous = event["hash"]
        return events

    def head(self) -> str:
        """Hash of the last entry. Cutting lines off the end leaves a valid chain, so the head must be
        anchored outside the file: the register lives in git and every report names its head."""
        events = self.events()
        return events[-1]["hash"] if events else GENESIS

    def _append(self, body: dict[str, Any]) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)  # one writer at a time, otherwise the chain forks
            events = self.events()
            moment = _time(body["at"])
            if abs(moment - _time(self.clock())) > CLOCK_TOLERANCE:
                raise LearningError("entry date differs from the real clock; nothing may be back- or forward-dated")
            times = [_time(e["at"]) for e in events if "at" in e]
            if times and moment < max(times):
                raise LearningError("time runs backwards; an entry may not be dated before the last one")
            previous = events[-1]["hash"] if events else GENESIS
            body = {**body, "previous": previous, "register_version": REGISTER_VERSION}
            event = {**body, "hash": _digest(previous, body)}
            handle.write(json.dumps(event, sort_keys=True) + "\n")
        return event

    # -- state --------------------------------------------------------------------------------
    def state(self) -> dict[str, Any]:
        """Families, models and the champion line, folded from the events."""
        families: dict[str, dict[str, Any]] = {}
        models: dict[str, dict[str, Any]] = {}
        ids: set[str] = set()
        for event in self.events():
            kind = event["kind"]
            if kind == "family":
                families[event["family"]] = {"rules": event["rules"], "champions": [], "champion": None}
            elif kind == "challenger":
                ids.add(event["model_id"])
                models[event["model_id"]] = {**event, "verdict": None, "evaluation": None}
            elif kind == "evaluation":
                models[event["model_id"]]["verdict"] = event["verdict"]
                models[event["model_id"]]["evaluation"] = event
            elif kind in {"promotion", "baseline", "rollback"}:
                ids.add(event["model_id"])
                family = families[event["family"]]
                family["champion"] = event["model_id"]
                family["champions"].append({"model_id": event["model_id"], "kind": kind, "at": event["at"]})
        return {"families": families, "models": models, "ids": sorted(ids)}

    def overdue(self, now: Any) -> list[str]:
        """Challengers whose window has ended without an evaluation: shown, never silently forgotten."""
        moment = _time(now)
        return sorted(m for m, v in self.state()["models"].items() if v["verdict"] is None and _time(v["window_end"]) <= moment)

    def champion(self, family: str) -> str | None:
        return self._family(family)["champion"]

    def _family(self, family: str) -> dict[str, Any]:
        families = self.state()["families"]
        if family not in families:
            raise LearningError(f"family {family} is not registered")
        return families[family]

    # -- writes -------------------------------------------------------------------------------
    def register_family(self, family: str, rules: Mapping[str, Any], *, at: Any) -> dict[str, Any]:
        if family in self.state()["families"]:
            raise LearningError(f"family {family} already exists; rules never change, use a new family")
        missing = [k for k in RULE_KEYS if k not in rules]
        if missing:
            raise LearningError(f"rules incomplete: {missing}")
        rules = dict(rules)
        if not (0.5 < _number(rules["ci_level"], "ci_level") < 1):
            raise LearningError("ci_level must lie between 0.5 and 1")
        if _number(rules["min_effect"], "min_effect") <= 0:
            raise LearningError("min_effect must be positive")
        for key in ("horizon_minutes", "min_window_days", "min_minutes", "per_week", "per_quarter"):
            _integer(rules[key], key)
        approvers = rules["approvers"]
        if not isinstance(approvers, list) or not approvers or not all(isinstance(a, str) and a.strip() for a in approvers):
            raise LearningError("approvers must be a non-empty list of names")
        if not str(rules["config_id"] or "").strip():
            raise LearningError("config_id is required")
        start = _time(rules["prospective_start"])
        if start < _time(at):
            raise LearningError("the prospective start must not lie before the registration")
        rules["prospective_start"] = _iso(start)
        return self._append({"kind": "family", "family": family, "rules": rules, "at": _iso(at)})

    def register_baseline(self, family: str, model_id: str, *, model_hash: str, at: Any, note: str = "") -> dict[str, Any]:
        """The first champion (e.g. the class base rate). Only once, before any promotion."""
        info = self._family(family)
        if info["champions"]:
            raise LearningError(f"family {family} already has a champion line")
        if model_id in self.state()["ids"]:
            raise LearningError(f"{model_id} already exists")
        return self._append({"kind": "baseline", "family": family, "model_id": model_id, "model_hash": model_hash,
                             "at": _iso(at), "note": note})

    def register_challenger(self, family: str, model_id: str, *, at: Any, trained_until: Any, window_start: Any,
                            window_end: Any, data_sources: list[Mapping[str, Any]], config_id: str, code_commit: str,
                            feature_version: str, label_version: str, data_hash: str, model_hash: str) -> dict[str, Any]:
        info = self._family(family)
        rules = info["rules"]
        state = self.state()
        if model_id in state["ids"]:
            raise LearningError(f"{model_id} already exists")
        if info["champion"] is None:
            raise LearningError("register a baseline champion first; a challenger needs something to beat")
        if config_id != rules["config_id"]:
            raise LearningError(f"config {config_id} differs from the registered {rules['config_id']}; that is a new study")
        for name, value in (("code_commit", code_commit), ("feature_version", feature_version), ("label_version", label_version),
                            ("data_hash", data_hash), ("model_hash", model_hash)):
            if not str(value or "").strip():
                raise LearningError(f"{name} is required")
        now, cut, start, end = _time(at), _time(trained_until), _time(window_start), _time(window_end)
        purge = timedelta(minutes=int(rules["horizon_minutes"]))
        if start < now:
            raise LearningError("the test window must start after the announcement (announce first, then test)")
        if cut + purge > start:
            raise LearningError("training must end at least one horizon before the test window")
        if end - start < timedelta(days=int(rules["min_window_days"])):
            raise LearningError(f"test window shorter than {rules['min_window_days']} days")
        prospective = _time(rules["prospective_start"])
        if start < prospective:
            raise LearningError("test window before the prospective start of the family")
        if not data_sources:
            raise LearningError("data_sources are required")
        sources = []
        for source in data_sources:
            if not isinstance(source, Mapping) or source.get("from") is None or source.get("to") is None:
                raise LearningError("each data source needs kind, from and to")
            try:
                kind, first, last = source.get("kind"), _time(source["from"]), _time(source["to"])
            except (TypeError, ValueError) as error:
                raise LearningError(f"data source time unreadable: {error}") from error
            if first > last:
                raise LearningError("data source ends before it begins")
            if last > cut:
                raise LearningError("a data source reaches past the training cut-off")
            if kind == "archive":
                if last >= HOLDOUT_START:
                    raise LearningError("archive data from 2025-01-01 on is the locked holdout")
            elif kind == "live":
                if first < prospective:
                    raise LearningError("live data from before the prospective start is closed (holdout gap)")
            else:
                raise LearningError(f"unknown data source kind {kind}")
            sources.append({"kind": kind, "from": _iso(first), "to": _iso(last)})
        # The budget counts every challenger of this configuration, in any family: a second family with
        # the same configuration is no way around it.
        mine = [m for m in state["models"].values() if m["config_id"] == config_id]
        week = now.isocalendar()[:2]
        if sum(_time(m["at"]).isocalendar()[:2] == week for m in mine) >= int(rules["per_week"]):
            raise LearningError("weekly challenger budget used up")
        if sum(_quarter(_time(m["at"])) == _quarter(now) for m in mine) >= int(rules["per_quarter"]):
            raise LearningError("quarterly challenger budget used up")
        return self._append({"kind": "challenger", "family": family, "model_id": model_id, "at": _iso(now),
                             "champion_at_announcement": info["champion"], "trained_until": _iso(cut),
                             "window_start": _iso(start), "window_end": _iso(end), "data_sources": sources,
                             "config_id": config_id, "code_commit": code_commit, "feature_version": feature_version,
                             "label_version": label_version, "data_hash": data_hash, "model_hash": model_hash})

    @staticmethod
    def verdict(rules: Mapping[str, Any], metrics: Mapping[str, Any]) -> tuple[str, list[str]]:
        """ELIGIBLE / REJECTED / NO_VERDICT and the reasons. delta = champion loss - challenger loss (> 0: better)."""
        reasons = []
        for key in ("n_minutes", "days", "delta", "ci_low", "ci_high", "ci_level"):
            _number(metrics.get(key), key)
        if not all(isinstance(metrics.get(k), bool) for k in ("calibration_ok", "quality_ok")):
            raise LearningError("calibration_ok and quality_ok must be true or false")
        if not metrics["ci_low"] <= metrics["delta"] <= metrics["ci_high"]:
            raise LearningError("interval must contain the estimate (ci_low <= delta <= ci_high)")
        if not metrics.get("quality_ok"):
            reasons.append("data quality gate not passed")
        if int(metrics.get("n_minutes", 0)) < int(rules["min_minutes"]):
            reasons.append(f"fewer than {rules['min_minutes']} valid minutes")
        if float(metrics.get("days", 0)) < int(rules["min_window_days"]):
            reasons.append(f"fewer than {rules['min_window_days']} days")
        if float(metrics.get("ci_level", 0)) < float(rules["ci_level"]):
            reasons.append(f"interval level below the registered {rules['ci_level']}")
        if reasons:
            return NO_VERDICT, reasons
        delta, low = float(metrics["delta"]), float(metrics["ci_low"])
        if delta < float(rules["min_effect"]):
            reasons.append(f"improvement {delta:.6f} below the smallest effect {rules['min_effect']}")
        if low <= 0:
            reasons.append("lower interval bound not above zero")
        if not metrics.get("calibration_ok"):
            reasons.append("calibration or per-class quality worse than tolerated")
        return (REJECTED, reasons) if reasons else (ELIGIBLE, ["all registered conditions met"])

    def record_evaluation(self, model_id: str, metrics: Mapping[str, Any], *, at: Any) -> dict[str, Any]:
        state = self.state()
        model = state["models"].get(model_id)
        if model is None:
            raise LearningError(f"{model_id} is not an announced challenger")
        if model["verdict"] is not None:
            raise LearningError(f"{model_id} was already evaluated; a window is used once")
        if _time(at) < _time(model["window_end"]):
            raise LearningError("evaluation before the end of the test window")
        rules = state["families"][model["family"]]["rules"]
        needed = ("n_minutes", "days", "delta", "ci_low", "ci_high", "ci_level", "calibration_ok", "quality_ok")
        missing = [k for k in needed if k not in metrics]
        if missing:
            raise LearningError(f"metrics incomplete: {missing}")
        if float(metrics["days"]) > (_time(model["window_end"]) - _time(model["window_start"])).total_seconds() / 86400 + 1e-9:
            raise LearningError("more days reported than the registered window holds")
        verdict, reasons = self.verdict(rules, metrics)
        return self._append({"kind": "evaluation", "family": model["family"], "model_id": model_id, "at": _iso(at),
                             "metrics": dict(metrics), "verdict": verdict, "reasons": reasons})

    def promote(self, model_id: str, *, approved_by: str, at: Any, note: str = "") -> dict[str, Any]:
        state = self.state()
        model = state["models"].get(model_id)
        if model is None or model["verdict"] != ELIGIBLE:
            raise LearningError(f"{model_id} has no ELIGIBLE verdict")
        family = state["families"][model["family"]]
        if approved_by not in family["rules"]["approvers"]:
            raise LearningError("a promotion needs a registered approver (Uzi's card)")
        if any(c["model_id"] == model_id for c in family["champions"]):
            raise LearningError(f"{model_id} was already champion")
        if family["champion"] != model["champion_at_announcement"]:
            raise LearningError("the champion changed since the announcement; the comparison is stale")
        return self._append({"kind": "promotion", "family": model["family"], "model_id": model_id, "at": _iso(at),
                             "approved_by": approved_by, "note": note})

    def rollback(self, family: str, *, to_model_id: str, reason: str, at: Any) -> dict[str, Any]:
        info = self._family(family)
        line = info["champions"]
        # Strictly backwards: only to a champion that held before the current one first became champion.
        # A model that was demoted by a rollback never comes back this way (no switching back and forth).
        first = min(i for i, c in enumerate(line) if c["model_id"] == info["champion"])
        earlier = {c["model_id"] for c in line[:first]}
        if to_model_id not in earlier:
            raise LearningError(f"{to_model_id} was never an earlier champion of {family}")
        if not str(reason or "").strip():
            raise LearningError("a rollback needs a reason")
        return self._append({"kind": "rollback", "family": family, "model_id": to_model_id, "at": _iso(at), "reason": reason})
