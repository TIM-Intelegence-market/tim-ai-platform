"""Research workshop F3: study generator from templates, mandatory fields, register count, budget."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.research_lab.stats.register import HypothesisRegister
from src.research_lab.workshop import charter
from src.research_lab.workshop.__main__ import main
from src.research_lab.workshop.generator import DraftError, create_draft, next_study_id
from src.research_lab.workshop.ideas import IdeaQueue

NOW = "2026-10-31T13:00:00Z"


def _spec(**extra) -> dict:
    spec = {
        "template": "regel_backtest", "title": "POC-Retest London",
        "question": "Hält ein Retest am Vortags-POC zur London-Öffnung öfter als Zufall?",
        "data": ["archive_usdm_klines"], "period": ["2020-01-01", "2024-12-31"],
        "variants": [{"id": "S-A", "rule": "Long am POC", "params": {"stop_atr": 1.0}},
                     {"id": "S-B", "rule": "Short am POC", "params": {"stop_atr": 1.0}}],
        "costs": "Protokoll 4.4 (Taker), Stress doppelt", "random_baseline": "7.1, gleiche Geometrie",
        "metric": "netto R je Trade", "min_effect": "0,05 R", "min_cases": 500,
        "stop_rule": "Zähllauf unter 500 Signalen: nicht prüfbar", "limits": ["nur 5m-Kerzen"],
    }
    spec.update(extra)
    return spec


@pytest.fixture()
def lab(tmp_path: Path):
    studies = tmp_path / "studien"
    studies.mkdir()
    (studies / "S10_X.md").write_text("x")
    logbook = tmp_path / "LOGBUCH.json"
    logbook.write_text(json.dumps({"entries": [{"id": "S10", "lesson": "Variante S11 abgelehnt"}]}))
    register = tmp_path / "REGISTER.jsonl"
    queue = IdeaQueue(tmp_path / "IDEEN.jsonl")
    idea = queue.add(source="uzi", title="POC-Retest London", hypothesis="Retest am POC hält", data=["archive_usdm_klines"],
                     template="regel_backtest", at=NOW)
    queue.set_status(idea, "ready", at=NOW)
    return {"queue": queue, "idea": idea, "studies": studies, "logbook": logbook, "register": register}


def _draft(lab, spec, **kw):
    return create_draft(lab["queue"], lab["idea"], spec, now=NOW, studies_dir=lab["studies"], register_path=lab["register"],
                        logbook_path=lab["logbook"], **kw)


def test_draft_is_written_named_after_free_id_and_closes_the_idea(lab) -> None:
    path, text = _draft(lab, _spec())
    assert path.name.startswith("S12_POC_RETEST_LONDON") and path.read_text() == text  # S11 is a rejected name
    assert "m = 0 → 2 von 60" in text and "wartet auf Uzis Freigabe" in text and "14:00 Ortszeit" in text
    idea = lab["queue"].ideas()[lab["idea"]]
    assert idea["status"] == "study_draft" and "S12" in idea["reasons"][0]
    assert not lab["register"].exists()  # nothing is registered by the generator
    with pytest.raises(DraftError, match="nicht bereit"):
        _draft(lab, _spec())


def test_missing_mandatory_field_stops_without_writing(lab) -> None:
    spec = _spec()
    del spec["stop_rule"]
    with pytest.raises(DraftError, match="stop_rule"):
        _draft(lab, spec)
    assert list(lab["studies"].glob("S12*")) == [] and lab["queue"].ideas()[lab["idea"]]["status"] == "ready"


def test_derived_idea_needs_prior_burden(lab) -> None:
    queue = lab["queue"]
    derived = queue.add(source="uzi", title="IB ohne Filter", hypothesis="h2", data=["archive_usdm_klines"],
                        template="regel_backtest", derived_from="S10", at=NOW)
    queue.set_status(derived, "ready", at=NOW)
    with pytest.raises(DraftError, match="Vorbelastung"):
        create_draft(queue, derived, _spec(title="IB ohne Filter"), now=NOW, studies_dir=lab["studies"],
                     register_path=lab["register"], logbook_path=lab["logbook"])


def test_holdout_period_is_refused(lab) -> None:
    with pytest.raises(DraftError, match="Holdout"):
        _draft(lab, _spec(period=["2023-01-01", "2025-06-30"]))


def test_snooping_test_is_mandatory_from_five_variants(lab) -> None:
    variants = [{"id": f"V{i}", "rule": "r", "params": {"k": i}} for i in range(charter.SNOOPING_TEST_FROM_VARIANTS)]
    _, text = _draft(lab, _spec(variants=variants), write=False)
    assert "Glückstest SPA/StepM Pflicht" in text
    _, text = _draft(lab, _spec(), write=False)
    assert "Glückstest" not in text


def test_full_register_refuses(lab) -> None:
    register = HypothesisRegister(lab["register"], limit=100)
    for i in range(59):
        register.register(f"X{i}", "h", {})
    with pytest.raises(DraftError, match="Register voll"):
        _draft(lab, _spec())


def test_model_and_event_templates_use_own_family(lab) -> None:
    spec = {k: v for k, v in _spec().items() if k not in {"variants", "costs", "random_baseline"}}
    model = {**spec, "template": "modellvergleich", "model": "LogReg", "features": "1.1.0", "label": "5-min-Richtung",
             "prospective_window": {"start": "2026-11-15", "days": 30}}
    _, text = _draft(lab, model, write=False)
    assert "Eigene Familie" in text and "ab 2026-11-15 für 30 Tage" in text
    event = {**spec, "template": "ereignis_studie", "events": ["FOMC"], "comparison": "gleiche Stunde ±1–4 Wochen"}
    _, text = _draft(lab, event, write=False)
    assert "FOMC" in text


def test_budget_blocks_a_fifth_draft_in_the_month(lab) -> None:
    queue = lab["queue"]
    for i in range(charter.MONTHLY_STUDY_BUDGET):
        other = queue.add(source="uzi", title=f"t{i}", hypothesis=f"x{i}", data=["plan_journal"], at=NOW)
        queue.set_status(other, "study_draft", at=NOW)
    with pytest.raises(DraftError, match="Budget"):
        _draft(lab, _spec())


def test_repository_next_id_skips_used_names() -> None:
    assert int(next_study_id().lstrip("S")) >= 12


def test_cli_draft_dry_run_writes_nothing(lab, tmp_path: Path, capsys) -> None:
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps(_spec()))
    before = lab["queue"].path.read_text()
    assert main(["--queue", str(lab["queue"].path), "--logbook", str(lab["logbook"]), "draft", "--idea", lab["idea"],
                 "--spec", str(spec), "--studies-dir", str(lab["studies"]), "--register", str(lab["register"]), "--dry-run"]) == 0
    assert "# S12: POC-Retest London" in capsys.readouterr().out
    assert lab["queue"].path.read_text() == before and list(lab["studies"].glob("S12*")) == []
