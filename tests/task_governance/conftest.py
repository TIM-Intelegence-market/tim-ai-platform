import pytest

from src.task_governance import GitHubRestGateway


class AllowEveryRegistry:
    """Test double only: unlike `UnrestrictedCreateAuthority` it also accepts the production repository name, which
    several older tests use for their fake transport."""

    def check(self, gateway, registry_id, trusted_authors):
        return None


@pytest.fixture(autouse=True)
def _gateways_may_create_unless_the_test_checks_the_authority(request, monkeypatch):
    """The older tests exercise create-once, recovery and fencing, which do not depend on WHICH registry may create.
    They run with a gateway that lets every registry create. The production default (a gateway built without
    an authority refuses every create) is what `test_create_authority.py` checks; it opts out with `real_create_authority`."""
    if request.node.get_closest_marker('real_create_authority'):
        return
    original = GitHubRestGateway.__init__

    def init(self, *args, create_authority=None, **kwargs):
        original(self, *args, create_authority=create_authority or AllowEveryRegistry(), **kwargs)

    monkeypatch.setattr(GitHubRestGateway, '__init__', init)
