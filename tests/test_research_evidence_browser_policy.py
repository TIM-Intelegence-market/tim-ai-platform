import dataclasses

import pytest

from src.research_evidence import browser_policy
from src.research_evidence.browser_policy import BrowserBudget, BrowserPolicy


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def allow_urls(monkeypatch):
    monkeypatch.setattr(browser_policy, "check_url", lambda url, policy: True)


def _enabled(**kw) -> BrowserPolicy:
    return BrowserPolicy(enabled=True, **kw)


def test_default_policy_is_disabled():
    assert BrowserPolicy().enabled is False


def test_policy_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        BrowserPolicy().enabled = True


def test_start_raises_when_disabled():
    with pytest.raises(PermissionError):
        BrowserBudget(BrowserPolicy(), FakeClock()).start()


def test_from_env_enabled_outside_ci_and_production():
    assert BrowserPolicy.from_env({"TIM_BROWSER_USE_ENABLED": "1"}).enabled is True


def test_from_env_requires_flag():
    assert BrowserPolicy.from_env({}).enabled is False


def test_from_env_disabled_in_ci():
    env = {"TIM_BROWSER_USE_ENABLED": "1", "CI": "true"}
    assert BrowserPolicy.from_env(env).enabled is False


def test_from_env_disabled_in_production():
    env = {"TIM_BROWSER_USE_ENABLED": "1", "TIM_ENV": "production"}
    assert BrowserPolicy.from_env(env).enabled is False


def test_kill_switch_blocks_start():
    with pytest.raises(PermissionError):
        BrowserBudget(_enabled(kill_switch=True), FakeClock()).start()


def test_navigate_before_start_is_denied(allow_urls):
    budget = BrowserBudget(_enabled(), FakeClock())
    assert budget.navigate("https://example.com") is False
    assert budget.audit()[0]["reason"] == "not_running"


def test_navigation_limit(allow_urls):
    budget = BrowserBudget(_enabled(max_navigations=2), FakeClock())
    budget.start()
    assert budget.navigate("https://example.com/a") is True
    assert budget.navigate("https://example.com/b") is True
    assert budget.navigate("https://example.com/c") is False
    assert budget.audit()[-1]["reason"] == "navigation_limit"


def test_time_limit_with_fake_clock(allow_urls):
    clock = FakeClock()
    budget = BrowserBudget(_enabled(max_seconds=5.0), clock)
    budget.start()
    assert budget.navigate("https://example.com/a") is True
    clock.now += 6.0
    assert budget.navigate("https://example.com/b") is False
    assert budget.audit()[-1]["reason"] == "time_limit"


def test_private_url_is_denied():
    budget = BrowserBudget(_enabled(), FakeClock())
    budget.start()
    assert budget.navigate("http://127.0.0.1/admin") is False
    entry = budget.audit()[0]
    assert entry["action"] == "navigate"
    assert entry["url"] == "http://127.0.0.1/admin"
    assert entry["allowed"] is False


def test_download_default_budget_denies_any_bytes():
    budget = BrowserBudget(_enabled(), FakeClock())
    budget.start()
    assert budget.download(1) is False


def test_download_within_limit_is_allowed():
    budget = BrowserBudget(_enabled(max_download_bytes=100), FakeClock())
    budget.start()
    assert budget.download(100) is True
    assert budget.download(101) is False
    assert [e["allowed"] for e in budget.audit()] == [True, False]


def test_download_before_start_is_denied():
    budget = BrowserBudget(_enabled(max_download_bytes=100), FakeClock())
    assert budget.download(1) is False


def test_audit_cannot_be_mutated_from_outside(allow_urls):
    budget = BrowserBudget(_enabled(), FakeClock())
    budget.start()
    budget.navigate("https://example.com")
    copy = budget.audit()
    copy[0]["allowed"] = False
    copy.append({"action": "fake"})
    assert len(budget.audit()) == 1
    assert budget.audit()[0]["allowed"] is True
