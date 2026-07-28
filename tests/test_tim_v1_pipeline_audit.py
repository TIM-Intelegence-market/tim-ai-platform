from scripts.tim_v1_pipeline_audit import run_once


def test_complete_audit_fixture_is_byte_deterministic():
    first = run_once("first")
    second = run_once("second")
    for key in ("input_hash", "dataset_hash", "output_hash", "replay_hash", "stage_hashes", "counts"):
        assert first[key] == second[key]


def test_audit_fixture_exercises_all_scientific_stages():
    result = run_once("coverage")
    assert result["counts"]["candles"] > 0
    assert result["counts"]["metrics"] == 2
    assert result["counts"]["observations"] > 0
    assert result["counts"]["cases"] == result["counts"]["observations"]
    assert result["counts"]["validations"] == result["counts"]["observations"]
