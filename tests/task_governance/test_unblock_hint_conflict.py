import pytest

from src.task_governance import MappingState, TaskRegistry

FINGERPRINT = 'fp-hint-conflict'
KEY = 'M09|P0|SAMPLE_TASK|TIM|v1'


def _hint_conflict_registry(tmp_path):
    reg = TaskRegistry(str(tmp_path / 'reg.db'))
    won, mapping = reg.claim(FINGERPRINT, KEY, 'w1', 300, hint=11)
    assert won and mapping.hint_issue == 11
    reg.block(FINGERPRINT, 'HINT_CONFLICT', 'authoritative_hint=12', token=mapping.claim_token, candidates=(12,))
    return reg


def test_unblock_without_hint_is_refused_for_hint_conflict(tmp_path):
    reg = _hint_conflict_registry(tmp_path)
    with pytest.raises(ValueError, match='replace_hint'):
        reg.unblock(FINGERPRINT, 'operator')
    row = reg.get(FINGERPRINT)
    assert row.state is MappingState.BLOCKED
    assert row.block_reason == 'HINT_CONFLICT'
    assert row.hint_issue == 11


def test_unblock_with_hint_still_releases_hint_conflict(tmp_path):
    reg = _hint_conflict_registry(tmp_path)
    assert reg.unblock(FINGERPRINT, 'operator', hint=11) is True
    row = reg.get(FINGERPRINT)
    assert row.state is MappingState.RELEASED
    assert row.block_reason == ''
