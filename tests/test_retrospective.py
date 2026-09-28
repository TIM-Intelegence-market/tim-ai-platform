from datetime import datetime, timedelta, timezone

import pytest

from src.orderflow.validation import VALIDATION_VERSION
from src.research.case_export import build_case_export, to_html, verify_case_export
from src.research.retrospective import LABEL, MIN_SAMPLE, case_retrospective, retrospective

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
AS_OF = T0 + timedelta(days=10)
KIND, RULE = "ABSORPTION", "1.0.0"


def history(n: int, outcome: str = "PRICE_INCREASED", start: datetime = T0, prefix: str = "o", **overrides):
    observations, validations = [], []
    for i in range(n):
        at = start + timedelta(hours=i)
        oid = f"{prefix}{i}"
        observations.append({"observation_id": oid, "kind": overrides.get("kind", KIND), "rule_version": overrides.get("rule_version", RULE)})
        validations.append({
            "observation_id": oid, "observed_at": at.isoformat(), "complete": True, "outcome": outcome,
            "validation_version": overrides.get("validation_version", VALIDATION_VERSION),
            "validated_through": (at + timedelta(minutes=30)).isoformat(),
            "horizons": [{"minutes": m, "target_at": (at + timedelta(minutes=m)).isoformat()} for m in (5, 15, 30)],
        })
    return observations, validations


def test_counts_past_outcomes_of_same_type_and_rule() -> None:
    obs_up, val_up = history(8, "PRICE_INCREASED", prefix="u")
    obs_dn, val_dn = history(4, "PRICE_DECREASED", prefix="d")
    result = retrospective(KIND, RULE, AS_OF, obs_up + obs_dn, val_up + val_dn)
    assert result["label"] == LABEL and result["sufficient"]
    assert result["sample_size"] == 12
    assert result["outcomes"] == {"PRICE_DECREASED": 4, "PRICE_INCREASED": 8, "PRICE_SIDEWAYS": 0}
    assert "Keine Prognose" in result["note"]


def test_no_look_ahead() -> None:
    obs, val = history(MIN_SAMPLE, start=AS_OF - timedelta(minutes=10))
    # observed before as_of, but horizons end after as_of -> outcome not yet known
    assert retrospective(KIND, RULE, AS_OF, obs, val)["sample_size"] == 0
    obs, val = history(MIN_SAMPLE, start=AS_OF)
    assert retrospective(KIND, RULE, AS_OF, obs, val)["sample_size"] == 0


def test_other_types_versions_incomplete_and_test_data_are_excluded() -> None:
    parts = [
        history(MIN_SAMPLE, prefix="k", kind="OTHER"),
        history(MIN_SAMPLE, prefix="r", rule_version="2.0.0"),
        history(MIN_SAMPLE, prefix="v", validation_version="0.9.0"),
    ]
    obs = [o for p in parts for o in p[0]]
    val = [v for p in parts for v in p[1]]
    inc_obs, inc_val = history(MIN_SAMPLE, prefix="i")
    for item in inc_val:
        item["complete"] = False
    test_obs, test_val = history(MIN_SAMPLE, prefix="TEST_ONLY_")
    result = retrospective(KIND, RULE, AS_OF, obs + inc_obs + test_obs, val + inc_val + test_val)
    assert result["sample_size"] == 0


def test_small_samples_hide_frequencies() -> None:
    obs, val = history(MIN_SAMPLE - 1)
    result = retrospective(KIND, RULE, AS_OF, obs, val)
    assert result["sample_size"] == MIN_SAMPLE - 1
    assert not result["sufficient"] and result["outcomes"] is None
    assert "Zu wenige" in result["note"]


def test_naive_as_of_rejected() -> None:
    with pytest.raises(ValueError):
        retrospective(KIND, RULE, datetime(2026, 9, 1), [], [])


def test_case_retrospective_excludes_own_observations_and_is_exported() -> None:
    obs, val = history(MIN_SAMPLE + 1)
    case = {
        "case_id": "case_ofabc", "symbol": "BTCUSDT", "timeframe": "1m", "opened_at": AS_OF.isoformat(), "updated_at": AS_OF.isoformat(),
        "status": "OPEN", "observation_ids": ["o0"], "evidence": [{"observation_id": "o0", "kind": KIND}],
        "missing_evidence": [], "rule_versions": {"orderflow": RULE},
    }
    blocks = case_retrospective(case, obs, val)
    assert len(blocks) == 1 and blocks[0]["sample_size"] == MIN_SAMPLE
    export = build_case_export(case, exported_at=AS_OF, retrospective=blocks)
    assert verify_case_export(export)
    export["retrospective"][0]["sample_size"] = 999
    assert not verify_case_export(export)
    page = to_html(build_case_export(case, exported_at=AS_OF, retrospective=blocks))
    assert "RETROSPECTIVE" in page and "Keine Prognose" in page


def test_case_without_orderflow_rule_has_no_retrospective() -> None:
    assert case_retrospective({"opened_at": AS_OF.isoformat(), "rule_versions": {"bos": "1.2.0"}}, [], []) == []
