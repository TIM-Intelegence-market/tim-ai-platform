"""Bounded, sanitized Python traceback assembly across polling checkpoints."""
import re

from src.bugfixer.processing import Event, parse_line, redact_text

_HEADER = 'Traceback (most recent call last):'
_TERMINAL = re.compile(r'^([A-Za-z_][A-Za-z0-9_.]*)(?::\s*(.*))?$')
# Frames from the worker's own package: drop the trace to avoid self-ingestion loops.
_OWN_FRAME = re.compile(r'^\s*File "(?:[^"]*[/\\])?src[/\\]bugfixer[/\\][^"]*"')


def _own_trace(lines) -> bool:
    return any(_OWN_FRAME.match(line) for line in lines)


class LegacyTraceAssembler:
    def __init__(self, pending=None, *, max_bytes=65536, max_lines=128):
        self.pending = pending
        self.max_bytes, self.max_lines = max_bytes, max_lines
        if pending:
            if set(pending) != {'timestamp', 'lines'} or not isinstance(pending['lines'], list):
                raise ValueError('invalid pending traceback')
            self._validate()

    def _validate(self):
        lines = self.pending['lines']
        if (not all(isinstance(line, str) for line in lines) or len(lines) > self.max_lines
                or sum(len(line.encode()) for line in lines) > self.max_bytes):
            raise ValueError('traceback exceeds assembly budget')

    def incomplete(self):
        if not self.pending:
            return []
        lines, started = self.pending['lines'], self.pending['timestamp']
        self.pending = None
        if _own_trace(lines):
            return []
        return [Event(started, 'legacy', '', 'Incomplete Python traceback', stack='\n'.join(lines))]

    def feed(self, line, observed_at):
        safe = redact_text(line).rstrip('\r\n')
        result = []
        if safe.strip() == _HEADER:
            result = self.incomplete()
            self.pending = {'timestamp': observed_at, 'lines': [safe]}
            return result
        if self.pending:
            terminal = _TERMINAL.fullmatch(safe) if safe and not safe[0].isspace() else None
            if terminal:
                self.pending['lines'].append(safe)
                self._validate()
                lines, started = self.pending['lines'], self.pending['timestamp']
                self.pending = None
                if _own_trace(lines):
                    return []
                return [Event(started, 'legacy', terminal[1], terminal[2] or terminal[1],
                              stack='\n'.join(lines))]
            if not safe.strip() or safe[0].isspace():
                self.pending['lines'].append(safe)
                self._validate()
                return []
            result = self.incomplete()
        parsed = parse_line(line, observed_at)
        if parsed:
            result.append(parsed)
        return result
