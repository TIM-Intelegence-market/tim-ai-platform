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


def _event_spec(**extra) -> dict:
    spec = {k: v for k, v in _spec().items() if k not in {"variants", "costs", "random_baseline"}}
    spec.update({"template": "ereignis_studie", "events": ["Funding im obersten Dezil"],
                 "comparison": "Gesamtverteilung gleicher Uhrzeit"}, **extra)
    return spec


def test_s16_style_spec_is_rejected_with_every_problem(lab) -> None:
    """The first worker draft for I-0001: objects instead of text, bare numbers, p-value stop, S5 unnamed."""
    queue = lab["queue"]
    idea = queue.add(source="uzi", title="Funding-Extreme", hypothesis="Nicht Carry wie in S5.",
                     data=["archive_usdm_klines"], template="ereignis_studie", at=NOW)
    queue.set_status(idea, "ready", at=NOW)
    spec = _event_spec(events=[{"name": "Rendite", "type": "continuous"}],
                       comparison={"group1": "oberstes Dezil", "group2": "Gesamt"}, min_effect=0.1,
                       stop_rule="Stop bei Erreichen von min_cases oder bei p-Wert < 0.05", limits=[0.05, "0.2"])
    with pytest.raises(DraftError) as err:
        create_draft(queue, idea, spec, now=NOW, studies_dir=lab["studies"], register_path=lab["register"],
                     logbook_path=lab["logbook"])
    message = str(err.value)
    for needle in ("'events' muss eine Liste aus Texten", "'comparison' muss Text", "'min_effect' muss Text",
                   "'limits' muss eine Liste aus Texten", "p-Wert", "nennt S5"):
        assert needle in message, needle
    assert list(lab["studies"].glob("S12*")) == [] and queue.ideas()[idea]["status"] == "ready"


@pytest.mark.parametrize("min_effect", ["0.1", "R", 0.1])
def test_min_effect_needs_number_and_unit(lab, min_effect) -> None:
    with pytest.raises(DraftError, match="min_effect"):
        _draft(lab, _spec(min_effect=min_effect), write=False)


@pytest.mark.parametrize("stop_rule", ["Abbruch bei p < 0,05", "Stop sobald signifikant", "stop at p-value 0.01"])
def test_p_value_stop_rule_is_optional_stopping(lab, stop_rule) -> None:
    with pytest.raises(DraftError, match="p-Wert"):
        _draft(lab, _spec(stop_rule=stop_rule), write=False)


@pytest.mark.parametrize("field,value", [("data", "archive_usdm_klines"), ("data", ["archive", 3]),
                                         ("limits", [{"x": 1}]), ("min_cases", "viele"), ("min_cases", 0), ("question", 42)])
def test_wrong_types_are_rejected(lab, field, value) -> None:
    with pytest.raises(DraftError, match=field):
        _draft(lab, _spec(**{field: value}), write=False)


def test_mentioned_study_must_appear_in_prior_burden(lab) -> None:
    spec = _spec(question="Hält der POC-Retest besser als in S7?")
    with pytest.raises(DraftError, match="nennt S7"):
        _draft(lab, spec, write=False)
    with pytest.raises(DraftError, match="S7 nennen"):
        _draft(lab, {**spec, "prior_burden": "S4 hat Ähnliches gezeigt"}, write=False)
    _, text = _draft(lab, {**spec, "prior_burden": "S7 lief auf denselben Daten 2020–2024"}, write=False)
    assert "S7 lief auf denselben Daten" in text


def test_clean_event_spec_still_renders_as_text(lab) -> None:
    _, text = _draft(lab, _event_spec(), write=False)
    assert "- Funding im obersten Dezil" in text and "{'" not in text
