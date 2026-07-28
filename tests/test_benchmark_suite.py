from pathlib import Path

from src.benchmark.suite import BenchmarkSuite


ROOT = Path(__file__).resolve().parents[1]


def test_permanent_market_benchmark_passes() -> None:
    report = BenchmarkSuite(ROOT / "benchmarks/market_cases_v1.json").run()
    assert report["status"] == "PASS"
    assert report["total"] == 5
    assert report["passed"] == 5


def test_benchmark_results_are_reproducible() -> None:
    first = BenchmarkSuite(ROOT / "benchmarks/market_cases_v1.json").run()
    second = BenchmarkSuite(ROOT / "benchmarks/market_cases_v1.json").run()
    assert first["dataset_sha256"] == second["dataset_sha256"]
    assert first["cases"] == second["cases"]

