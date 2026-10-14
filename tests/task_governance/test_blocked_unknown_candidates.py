from src.task_governance import EnsureOutcome, TaskRegistry, TaskRequest, ensure_task
from src.task_governance.sync import IssueRef

CREATED_NUMBER = 4
UNKNOWN_NUMBER = 9


def req():
    return TaskRequest(mission_id='M09', phase_id='P0', task_type='SAMPLE_TASK', target='TIM',
                       schema_version='v1', title='Sample')


class UnknownAfterCreateGateway:
    """Creates one issue; the duplicate check after the create reports another issue of unknown kind."""
    repository = 'owner/repo'
    max_create_seconds = 5.0

    def __init__(self):
        self.created = False
        self.creates = 0
        self.claims = {}

    def find_issues(self, fingerprint, canonical_key):
        if not self.created:
            return []
        return [IssueRef(number=UNKNOWN_NUMBER, state='open', author='someone', is_pull_request=None)]

    def get_issue(self, number):
        return None

    def carries_marker(self, number, fingerprint):
        return True

    def authorize_create(self, registry_id, trusted_authors):
        return None

    def claim_create(self, fingerprint, holder):
        """The repository-wide create claim (#68), held in memory: None for the first caller, else the holder."""
        if fingerprint in self.claims:
            return self.claims[fingerprint]
        self.claims[fingerprint] = holder
        return None

    def create_claim_holder(self, fingerprint):
        return self.claims.get(fingerprint)

    def release_create_claim(self, fingerprint):
        self.claims.pop(fingerprint, None)

    def create_issue(self, request, fingerprint, *, timeout):
        self.created = True
        self.creates += 1
        return IssueRef(number=CREATED_NUMBER, state='open', author='tim', is_pull_request=False)

    def update_issue(self, number, request, reason):
        raise AssertionError('update_issue must not be called')

    def reopen_issue(self, number, request, reason):
        raise AssertionError('reopen_issue must not be called')

    def is_documented_duplicate(self, number, authoritative):
        return False

    def mark_duplicate(self, number, authoritative):
        raise AssertionError('mark_duplicate must not be called')


def test_unknown_kind_after_create_blocks_with_created_and_unknown_candidates_sorted(tmp_path):
    registry = TaskRegistry(str(tmp_path / 'reg.db'))
    gateway = UnknownAfterCreateGateway()
    result = ensure_task(req(), registry, gateway, claimant='w1', trusted_authors=None)
    row = registry.get(req().fingerprint)
    assert gateway.creates == 1
    assert result.outcome is EnsureOutcome.BLOCKED
    assert result.detail == 'UNKNOWN_ISSUE_KIND'
    assert result.created is True and result.issue_number == CREATED_NUMBER
    assert row.block_reason == 'UNKNOWN_ISSUE_KIND'
    assert list(row.block_candidates) == [CREATED_NUMBER, UNKNOWN_NUMBER]
