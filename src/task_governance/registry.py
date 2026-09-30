"""Durable canonical-key -> GitHub-issue mapping with a create-once claim.

Uniqueness is enforced by the database (PRIMARY KEY on the fingerprint, UNIQUE
on the canonical key), not by an in-memory lock, so concurrent threads and
processes cannot both win the claim.
"""
from dataclasses import dataclass
from enum import Enum
import json
import sqlite3
import time

SCHEMA_VERSION = 3

SCHEMA = '''
CREATE TABLE IF NOT EXISTS task_mappings (
    fingerprint TEXT PRIMARY KEY,
    canonical_key TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL,
    claimant TEXT,
    claimed_at REAL,
    claim_token INTEGER NOT NULL DEFAULT 0,
    github_repository TEXT,
    github_issue_number INTEGER,
    duplicate_issues TEXT NOT NULL DEFAULT '[]',
    block_reason TEXT NOT NULL DEFAULT '',
    block_candidates TEXT NOT NULL DEFAULT '[]',
    hint_issue INTEGER,
    hint_legacy TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS governance_incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT, fingerprint TEXT NOT NULL,
    reason TEXT NOT NULL, detail TEXT NOT NULL, created_at REAL NOT NULL);
'''


class MappingState(str, Enum):
    CLAIMED = 'CLAIMED'    # a worker holds the create-once claim, no issue mapped yet
    MAPPED = 'MAPPED'      # authoritative issue persisted
    BLOCKED = 'BLOCKED'    # ambiguous or violated uniqueness, needs a human
    RELEASED = 'RELEASED'  # claim given up or block lifted; row and token counter are kept (tokens never restart)


@dataclass(frozen=True)
class Mapping:
    fingerprint: str
    canonical_key: str
    state: MappingState
    claimant: str | None
    claimed_at: float | None
    claim_token: int
    github_repository: str | None
    github_issue_number: int | None
    duplicate_issues: tuple[int, ...]
    block_reason: str
    block_candidates: tuple[int, ...]
    hint_issue: int | None = None                  # operator-designated authoritative issue, pinned by the first claim
    hint_legacy: tuple[int, ...] = ()              # known historical duplicates pinned together with it


class TaskRegistry:
    def __init__(self, path: str, *, clock=time.time):
        self.path = path
        self.clock = clock
        self.db = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA busy_timeout=30000')
        self._init()

    def _init(self) -> None:
        """Switching to WAL and running DDL ignore busy_timeout when several processes open a fresh
        or old file at once, so retry on lock errors instead of failing the worker at startup."""
        deadline = time.monotonic() + 30
        while True:
            try:
                self.db.execute('PRAGMA journal_mode=WAL')
                self.db.executescript(SCHEMA)
                self._migrate()
                return
            except sqlite3.OperationalError as exc:
                if 'locked' not in str(exc) and 'busy' not in str(exc) or time.monotonic() > deadline:
                    raise
                time.sleep(0.02)

    def _migrate(self) -> None:
        """Bring a registry file written by an earlier release up to the current columns."""
        have = {r['name'] for r in self.db.execute('PRAGMA table_info(task_mappings)')}
        for name, ddl in (('claim_token', 'INTEGER NOT NULL DEFAULT 0'), ('block_candidates', "TEXT NOT NULL DEFAULT '[]'"),
                          ('hint_issue', 'INTEGER'), ('hint_legacy', "TEXT NOT NULL DEFAULT '[]'")):
            if name not in have:
                try:
                    self.db.execute(f'ALTER TABLE task_mappings ADD COLUMN {name} {ddl}')
                except sqlite3.OperationalError as exc:
                    if 'duplicate column' not in str(exc):       # another process migrated first
                        raise
        self.db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')

    def close(self):
        self.db.close()

    def get(self, fingerprint: str) -> Mapping | None:
        row = self.db.execute('SELECT * FROM task_mappings WHERE fingerprint=?', (fingerprint,)).fetchone()
        return self._mapping(row) if row else None

    def claim(self, fingerprint: str, canonical_key: str, claimant: str, lease_seconds: float, *,
              hint: int | None = None, legacy=()) -> tuple[bool, Mapping]:
        """Atomically claim creation. True only for the single winner.

        Every successful claim gets a new `claim_token` (fencing token). A CLAIMED
        row can only be taken over after its lease expired, never by name: two
        workers sharing a claimant name must not both win. MAPPED and BLOCKED rows
        are never claimable. Rows are never deleted, so a fencing token is never reused.

        The winner also pins `hint`/`legacy` in the same transaction: the first hint sticks, the
        same hint only adds legacy numbers, a different hint is left out (the caller sees the
        mismatch in the returned row). So no later run can proceed without information an earlier
        run may already have acted on.
        """
        now = self.clock()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            cur = self.db.execute(
                'INSERT OR IGNORE INTO task_mappings(fingerprint,canonical_key,state,claimant,claimed_at,claim_token,'
                'hint_issue,hint_legacy,created_at,updated_at) VALUES(?,?,?,?,?,1,?,?,?,?)',
                (fingerprint, canonical_key, MappingState.CLAIMED, claimant, now, hint,
                 json.dumps(sorted(set(legacy))) if hint is not None else '[]', now, now))
            won = cur.rowcount == 1
            if not won:
                cur = self.db.execute(
                    'UPDATE task_mappings SET state=\'CLAIMED\', claimant=?, claimed_at=?, claim_token=claim_token+1, updated_at=? '
                    'WHERE fingerprint=? AND ((state=? AND claimed_at<?) OR state=?) RETURNING claim_token',
                    (claimant, now, now, fingerprint, MappingState.CLAIMED, now - lease_seconds, MappingState.RELEASED))
                won = cur.fetchone() is not None
                if won and hint is not None:
                    row = self.db.execute('SELECT hint_issue, hint_legacy FROM task_mappings WHERE fingerprint=?',
                                          (fingerprint,)).fetchone()
                    if row['hint_issue'] is None or row['hint_issue'] == hint:
                        merged = sorted(set(json.loads(row['hint_legacy'])) | set(legacy))
                        self.db.execute('UPDATE task_mappings SET hint_issue=?, hint_legacy=? WHERE fingerprint=?',
                                        (hint, json.dumps(merged), fingerprint))
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise
        return won, self.get(fingerprint)

    def replace_hint(self, fingerprint: str, hint: int | None, legacy=(), note: str = '') -> bool:
        """Operator decision: pin a different hint (or none) on a task that is not MAPPED.

        A HINT_CONFLICT block is lifted by this; the old hint stays in governance_incidents.
        """
        now = self.clock()
        n = self.db.execute(
            'UPDATE task_mappings SET hint_issue=?, hint_legacy=?, updated_at=?, '
            'state=CASE WHEN state=? AND block_reason=? THEN ? ELSE state END, '
            'block_reason=CASE WHEN state=? AND block_reason=? THEN \'\' ELSE block_reason END, '
            'block_candidates=CASE WHEN state=? AND block_reason=? THEN \'[]\' ELSE block_candidates END '
            'WHERE fingerprint=? AND state<>?',
            (hint, json.dumps(sorted(set(legacy))) if hint is not None else '[]', now,
             MappingState.BLOCKED, 'HINT_CONFLICT', MappingState.RELEASED,
             MappingState.BLOCKED, 'HINT_CONFLICT', MappingState.BLOCKED, 'HINT_CONFLICT',
             fingerprint, MappingState.MAPPED)).rowcount
        if n:
            self.db.execute('INSERT INTO governance_incidents(fingerprint,reason,detail,created_at) VALUES(?,?,?,?)',
                            (fingerprint, 'HINT_REPLACED', f'hint={hint} {note}'.strip(), now))
        return bool(n)

    def renew(self, fingerprint: str, token: int) -> bool:
        """Extend the lease if this claim was not taken over. Call right before the irreversible create."""
        cur = self.db.execute(
            'UPDATE task_mappings SET claimed_at=?, updated_at=? WHERE fingerprint=? AND state=? AND claim_token=?',
            (self.clock(), self.clock(), fingerprint, MappingState.CLAIMED, token))
        return cur.rowcount == 1

    def release(self, fingerprint: str, token: int) -> None:
        """Give the claim up after a failure that happened before anything was created."""
        self.db.execute('UPDATE task_mappings SET state=?, updated_at=? WHERE fingerprint=? AND state=? AND claim_token=?',
                        (MappingState.RELEASED, self.clock(), fingerprint, MappingState.CLAIMED, token))

    def map_issue(self, fingerprint: str, token: int, repository: str, issue_number: int, duplicates=()) -> Mapping | None:
        """Persist the authoritative issue. None means the claim was lost and nothing was written."""
        cur = self.db.execute(
            'UPDATE task_mappings SET state=?, github_repository=?, github_issue_number=?, duplicate_issues=?, '
            'block_reason=\'\', block_candidates=\'[]\', updated_at=? WHERE fingerprint=? AND state=? AND claim_token=?',
            (MappingState.MAPPED, repository, issue_number, json.dumps(sorted(set(duplicates))), self.clock(),
             fingerprint, MappingState.CLAIMED, token))
        return self.get(fingerprint) if cur.rowcount == 1 else None

    def block(self, fingerprint: str, reason: str, detail: str = '', *, token: int | None = None,
              candidates=()) -> Mapping:
        """Fail closed: record the incident and stop the task, never delete or close anything.

        `candidates` are the issue numbers the block is about (structured, used to judge whether a
        later hint really addresses it). With a token the state change is fenced to that claim. A
        MAPPED task is never downgraded, by anyone: a stale worker or operator call only records
        the incident.
        """
        now = self.clock()
        cands = json.dumps(sorted(set(candidates)))
        if token is None:
            self.db.execute('UPDATE task_mappings SET state=?, block_reason=?, block_candidates=?, updated_at=? '
                            'WHERE fingerprint=? AND state<>?',
                            (MappingState.BLOCKED, reason, cands, now, fingerprint, MappingState.MAPPED))
        else:
            self.db.execute('UPDATE task_mappings SET state=?, block_reason=?, block_candidates=?, updated_at=? '
                            'WHERE fingerprint=? AND state=? AND claim_token=?',
                            (MappingState.BLOCKED, reason, cands, now, fingerprint, MappingState.CLAIMED, token))
        self.db.execute('INSERT INTO governance_incidents(fingerprint,reason,detail,created_at) VALUES(?,?,?,?)',
                        (fingerprint, reason, detail, now))
        return self.get(fingerprint)

    def record_incident(self, fingerprint: str, reason: str, detail: str = '') -> None:
        self.db.execute('INSERT INTO governance_incidents(fingerprint,reason,detail,created_at) VALUES(?,?,?,?)',
                        (fingerprint, reason, detail, self.clock()))

    def add_duplicates(self, fingerprint: str, numbers) -> Mapping | None:
        """Record extra duplicate issue numbers on a MAPPED task without touching its state."""
        row = self.get(fingerprint)
        if row is None:
            return None
        merged = sorted(set(row.duplicate_issues) | set(numbers))
        self.db.execute('UPDATE task_mappings SET duplicate_issues=?, updated_at=? WHERE fingerprint=?',
                        (json.dumps(merged), self.clock(), fingerprint))
        return self.get(fingerprint)

    def unblock(self, fingerprint: str, note: str) -> bool:
        """Explicit release of a BLOCKED task (one transaction of state-guarded updates, no TOCTOU).

        With a mapped issue the task returns to MAPPED, otherwise to RELEASED (claimable again).
        History stays in governance_incidents.
        """
        now = self.clock()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            # a rejected hint is worthless: drop it so the operator's replacement can be pinned
            self.db.execute('UPDATE task_mappings SET hint_issue=NULL, hint_legacy=\'[]\' WHERE fingerprint=? AND state=? '
                            'AND block_reason IN (\'HINT_NOT_FOUND\', \'HINT_INVALID\')', (fingerprint, MappingState.BLOCKED))
            n = self.db.execute('UPDATE task_mappings SET state=?, block_reason=\'\', block_candidates=\'[]\', updated_at=? '
                                'WHERE fingerprint=? AND state=? AND github_issue_number IS NOT NULL',
                                (MappingState.MAPPED, now, fingerprint, MappingState.BLOCKED)).rowcount
            n += self.db.execute('UPDATE task_mappings SET state=?, block_reason=\'\', block_candidates=\'[]\', updated_at=? '
                                 'WHERE fingerprint=? AND state=? AND github_issue_number IS NULL',
                                 (MappingState.RELEASED, now, fingerprint, MappingState.BLOCKED)).rowcount
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise
        if n:
            self.db.execute('INSERT INTO governance_incidents(fingerprint,reason,detail,created_at) VALUES(?,?,?,?)',
                            (fingerprint, 'UNBLOCKED', note, now))
        return bool(n)

    def incidents(self, fingerprint: str | None = None) -> list[dict]:
        sql, args = 'SELECT * FROM governance_incidents', ()
        if fingerprint:
            sql, args = sql + ' WHERE fingerprint=?', (fingerprint,)
        return [dict(r) for r in self.db.execute(sql + ' ORDER BY id', args)]

    def count_mappings(self, canonical_key: str) -> int:
        return self.db.execute('SELECT COUNT(*) FROM task_mappings WHERE canonical_key=?', (canonical_key,)).fetchone()[0]

    @staticmethod
    def _mapping(row) -> Mapping:
        return Mapping(row['fingerprint'], row['canonical_key'], MappingState(row['state']), row['claimant'],
                       row['claimed_at'], row['claim_token'], row['github_repository'], row['github_issue_number'],
                       tuple(json.loads(row['duplicate_issues'])), row['block_reason'],
                       tuple(json.loads(row['block_candidates'])), row['hint_issue'],
                       tuple(json.loads(row['hint_legacy'])))
