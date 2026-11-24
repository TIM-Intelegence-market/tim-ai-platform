import json
import pytest

from src.llm.model_router import escalate, load_routes, route


def test_config_is_consistent():
    cfg = load_routes()
    assert cfg["standard"] in cfg["stufen"]


def test_image_goes_to_vision():
    assert route("status", hat_bild=True).stufe == "vision"


def test_private_never_cloud_even_with_image():
    assert route("studie", privat=True, hat_bild=True).ort != "cloud"
    with pytest.raises(RuntimeError):
        route(privat=True, lokal_verfuegbar=False)


def test_study_and_multistep_reasoning():
    assert route("studie").stufe == "reasoning"
    assert route("code", schritte=5).stufe == "reasoning"


def test_cheap_first_for_routine_status():
    assert route("status").stufe == "lokal_klein"
    assert route("status").hochstufen_auf == "lokal_gross"


def test_mass_goes_local():
    assert route(aufrufe=500).stufe == "lokal_klein"
    assert route("code", aufrufe=500).stufe == "mittel"  # bekannte Art gewinnt


def test_local_down_falls_back_to_cloud():
    assert route("status", lokal_verfuegbar=False).ort == "cloud"


def test_unknown_uses_default_and_escalation_ends():
    assert route("unbekannt").stufe == "mittel"
    assert escalate("lokal_klein") == "lokal_gross"
    assert escalate("reasoning") is None


def test_bad_config_rejected(tmp_path):
    p = tmp_path / "r.json"
    cfg = load_routes()
    cfg["aufgabenarten"]["x"] = "nix"
    p.write_text(json.dumps(cfg))
    with pytest.raises(ValueError):
        load_routes(p)


def test_no_secrets_in_config():
    text = open("config/model_router/routes.json").read().lower()
    assert "key" not in text and "token" not in text
