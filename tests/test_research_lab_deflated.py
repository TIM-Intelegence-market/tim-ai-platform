import json
import math
import random

import pytest

from src.research_lab.stats import deflated as d


def test_paper_example_bailey_lopez_de_prado_2014():
    # DSR paper, numerical example: SR 2.5 p.a., 1250 daily obs, skew -3, kurtosis 10, N = 100, V[SR] = 0.5 p.a.
    sr = 2.5 / math.sqrt(250)
    sr0 = d.expected_max_sharpe(100, 0.5 / 250)
    assert sr0 * math.sqrt(250) == pytest.approx(1.7894, abs=1e-3)
    assert d.probabilistic_sharpe(sr, 1250, -3.0, 10.0, sr0) == pytest.approx(0.9004, abs=1e-3)


def test_one_trial_is_plain_psr():
    rng = random.Random(1)
    r = [rng.gauss(0.1, 1.0) for _ in range(300)]
    res = d.deflated_sharpe(r, 1)
    assert res.sr0 == 0.0
    assert res.dsr == pytest.approx(res.psr_zero)


def test_more_trials_lower_dsr():
    rng = random.Random(2)
    r = [rng.gauss(0.15, 1.0) for _ in range(400)]
    values = [d.deflated_sharpe(r, n).dsr for n in (1, 10, 60, 200)]
    assert values == sorted(values, reverse=True)
    assert values[0] > values[-1]


def test_moments_normal_like():
    rng = random.Random(3)
    m = d.moments([rng.gauss(0, 1) for _ in range(20000)])
    assert m.skewness == pytest.approx(0, abs=0.1)
    assert m.kurtosis == pytest.approx(3, abs=0.15)


def test_null_variance_and_trial_variance():
    assert d.null_sr_variance(101) == pytest.approx(0.01)
    assert d.trial_sr_variance([0.1, 0.2, 0.3]) == pytest.approx(0.01)
    res = d.deflated_sharpe([0.5, -1, 2, -1, 3, -1, 0.2], 5, sr_variance=0.02)
    assert res.variance_source == "trials" and res.sr_variance == 0.02


@pytest.mark.parametrize("bad", [[], [1.0, 2.0], [1.0, 1.0, 1.0], [1.0, float("nan"), 2.0]])
def test_bad_inputs(bad):
    with pytest.raises(ValueError):
        d.moments(bad)


def test_invalid_counts():
    with pytest.raises(ValueError):
        d.expected_max_sharpe(0, 0.1)
    with pytest.raises(ValueError):
        d.total_trials(-1, {})
    assert d.total_trials(58, {"F1-F5": 5, "OF2": 1}) == 64


def test_register_count_on_repo_register():
    assert d.register_trials("docs/research_lab/REGISTER.jsonl") >= 58


def test_cli(tmp_path, capsys):
    rng = random.Random(4)
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"A": [rng.gauss(0.2, 1) for _ in range(200)]}))
    assert d.main([str(path), "--trials", "64"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out[0]["name"] == "A" and out[0]["trials"] == 64 and 0 <= out[0]["dsr"] <= 1
