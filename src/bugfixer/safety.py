"""Fail-closed bugfixer policy; this module never opens a connection."""
from dataclasses import dataclass
import re
from urllib.parse import unquote, urlsplit


class SafetyViolation(ValueError):
    pass


def database_identity(url: str) -> tuple:
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port or 5432
        name = unquote(parsed.path.removeprefix('/'))
        if (parsed.scheme not in {'postgres', 'postgresql'} or not host or not name
                or '/' in name or parsed.query or parsed.fragment or not 1 <= port <= 65535):
            raise ValueError()
        host = host.lower().rstrip('.')
        if host in {'localhost', '127.0.0.1', '::1'}:
            host = 'loopback'
        return host, port, name
    except (ValueError, TypeError, AttributeError):
        raise SafetyViolation('invalid or ambiguous database target') from None


def require_isolated_database(test_url: str, runtime_url: str):
    """Explicit identities required; credentials do not establish isolation."""
    target, runtime = database_identity(test_url), database_identity(runtime_url)
    if target == runtime:
        raise SafetyViolation('test database is the runtime database')
    if target[0] != 'loopback' or not re.search(r'(?:^|_)(?:test|pytest|isolated)(?:_|$)', target[2], re.I):
        raise SafetyViolation('test database must be an explicit isolated loopback target')
    return target


@dataclass(frozen=True)
class Policy:
    mode: str = 'OBSERVE'
    live_trading: bool = False
    execution: bool = False
    auto_remediate: bool = False
    mutate_queue: bool = False
    mutate_outbox: bool = False
    reset_attempts: bool = False
    skip_events: bool = False
    strict_ordering: bool = True
    determinism: bool = True
    lookahead_safety: bool = True

    def verify(self) -> dict:
        checks = {
            'observe_mode': self.mode == 'OBSERVE',
            'live_disabled': self.live_trading is False,
            'execution_disabled': self.execution is False,
            'auto_remediation_disabled': self.auto_remediate is False,
            'queue_immutable': self.mutate_queue is False,
            'outbox_immutable': self.mutate_outbox is False,
            'attempts_immutable': self.reset_attempts is False,
            'no_event_skip': self.skip_events is False,
            'strict_ordering': self.strict_ordering is True,
            'determinism': self.determinism is True,
            'lookahead_safety': self.lookahead_safety is True,
        }
        if not all(checks.values()):
            raise SafetyViolation('bugfixer policy forbids requested operation')
        return checks
