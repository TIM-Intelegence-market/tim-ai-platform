"""Durable canonical-key -> GitHub-issue mapping with a create-once claim.

Uniqueness is enforced by the database (PRIMARY KEY on the fingerprint, UNIQUE
on the canonical key), not by an in-memory lock, so concurrent threads and
processes cannot both win the claim.
"""
from dataclasses import dataclass
from enum import Enum
import json
import functools
import sqlite3
import uuid
import threading
import time

SCHEMA_VERSION = 6


class EngineBindingConflict(ValueError):
    """Two engine tasks would share one task identity (and so one issue)."""


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
    create_intent INTEGER NOT NULL DEFAULT 0,
    create_started_at REAL,
    create_run TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS engine_bindings (
    task_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, canonical_key TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS registry_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS governance_incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT, fingerprint TEXT NOT NULL,
    reason TEXT NOT NULL, detail TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS claim_ends (
    fingerprint TEXT NOT NULL, run TEXT NOT NULL, ended_at REAL NOT NULL, PRIMARY KEY (fingerprint, run));
'''


def _serialized(method):
    """One connection may be shared by threads: statements and explicit transactions of different
    threads must not interleave (a COMMIT of one thread would end another thread's transaction)."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


HINT_ONLY_BLOCKS = ('POST_CREATE_CHECK_FAILED', 'EXPECTED_ISSUE_INVALID')   # blocks about an issue we created: never released blindly


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
    create_intent: bool = False                    # a create may have reached GitHub: nobody may create blindly again
    create_run: str | None = None                  # the run that recorded the intent (and took the create claim label, #68)


class TaskRegistry:
    def __init__(self, path: str, *, clock=time.time):
        self.path = path
        self.clock = clock
        self._lock = threading.RLock()
        self.db = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA busy_timeout=30000')
        self._init()

    @property
    def registry_id(self) -> str:
        """Identity of this registry file: the repository's create authority names it (`create_authority`)."""
        with self._lock:
            return self.db.execute("SELECT value FROM registry_meta WHERE key='registry_id'").fetchone()[0]

    @_serialized
    def rotate_registry_id(self, note: str) -> str:
        """Give this file a new identity. Operator step for a file that was copied to another host: the copy must not
        share the original's authority. Mappings stay; the new id is not designated until an operator says so."""
        if not note.strip():
            raise ValueError('a note is required')
        old = self.registry_id
        new = uuid.uuid4().hex
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.db.execute("UPDATE registry_meta SET value=? WHERE key='registry_id'", (new,))
            self.db.execute('INSERT INTO governance_incidents(fingerprint,reason,detail,created_at) VALUES(?,?,?,?)',
                            ('', 'REGISTRY_ID_ROTATED', f'{old} -> {new}: {note.strip()}', self.clock()))
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise
        return new

    def _init(self) -> None:
        """Switching to WAL and running DDL ignore busy_timeout when several processes open a fresh
        or old file at once, so retry on lock errors instead of failing the worker at startup."""
        deadline = time.monotonic() + 30
        while True:
            try:
                self.db.execute('PRAGMA journal_mode=WAL')
                self.db.executescript(SCHEMA)
                self._migrate()
                self.db.execute("INSERT OR IGNORE INTO registry_meta(key,value) VALUES('registry_id',?)", (uuid.uuid4().hex,))
                return
            except sqlite3.OperationalError as exc:
                if 'locked' not in str(exc) and 'busy' not in str(exc) or time.monotonic() > deadline:
                    raise
                time.sleep(0.02)

    def _migrate(self) -> None:
        """Bring a registry file written by an earlier release up to the current columns.

        One transaction: the column check, the ALTERs and the sweep of old claims must not interleave with
        another process that already migrated and started claiming (its fresh claim must never be swept)."""
        self.db.execute('BEGIN IMMEDIATE')
        try:
            have = {r['name'] for r in self.db.execute('PRAGMA table_info(task_mappings)')}
            pre_hint = 'hint_issue' not in have
            for name, ddl in (('claim_token', 'INTEGER NOT NULL DEFAULT 0'), ('block_candidates', "TEXT NOT NULL DEFAULT '[]'"),
                              ('hint_issue', 'INTEGER'), ('hint_legacy', "TEXT NOT NULL DEFAULT '[]'"),
                              ('create_intent', 'INTEGER NOT NULL DEFAULT 0'), ('create_started_at', 'REAL'),
                              ('create_run', 'TEXT')):
                if name not in have:
                    self.db.execute(f'ALTER TABLE task_mappings ADD COLUMN {name} {ddl}')
            if self.db.execute('PRAGMA user_version').fetchone()[0] < 5:
                # Files before schema 5 (including intermediate ones that already had these columns) did not record every
                # create. Any unfinished row may follow a create (an open claim in the middle of one, or a row released or
                # blocked by a worker that took over a crashed creator): never create blindly, and start the quiet period now.
                self.db.execute("UPDATE task_mappings SET create_intent=1, create_started_at=? WHERE state<>'MAPPED'",
                                (self.clock(),))
            # an intent without its start time could never be cleared by an operator: start the quiet period now
            self.db.execute('UPDATE task_mappings SET create_started_at=? WHERE create_intent=1 AND create_started_at IS NULL',
                            (self.clock(),))
            if pre_hint:
                # A claim written before hints were stored may belong to a run that had a hint we cannot recover:
                # fail closed instead of letting a hint-less run create next to a legacy issue.
                stuck = [r['fingerprint'] for r in self.db.execute("SELECT fingerprint FROM task_mappings WHERE state='CLAIMED'")]
                for fp in stuck:
                    self.db.execute("UPDATE task_mappings SET state='BLOCKED', block_reason='MIGRATED_CLAIM', "
                                    "block_candidates='[]' WHERE fingerprint=? AND state='CLAIMED'", (fp,))
                    self.db.execute('INSERT INTO governance_incidents(fingerprint,reason,detail,created_at) VALUES(?,?,?,?)',
                                    (fp, 'MIGRATED_CLAIM', 'open claim from a registry without stored hints; operator must unblock',
                                     time.time()))
            # An earlier release could bind two engine tasks to one identity. Keep both rows, but say so once per
            # identity: the lookup then refuses to answer and the operator decides with rebind_engine_task.
            for dup in self.db.execute('SELECT fingerprint FROM engine_bindings GROUP BY fingerprint HAVING COUNT(*)>1').fetchall():
                fp = dup[0]
                if self.db.execute("SELECT 1 FROM governance_incidents WHERE fingerprint=? AND reason='ENGINE_BINDING_DUPLICATE'",
                                   (fp,)).fetchone() is None:
                    tasks = sorted(r[0] for r in self.db.execute('SELECT task_id FROM engine_bindings WHERE fingerprint=?', (fp,)))
                    self.db.execute('INSERT INTO governance_incidents(fingerprint,reason,detail,created_at) VALUES(?,?,?,?)',
                                    (fp, 'ENGINE_BINDING_DUPLICATE', f'engine tasks {", ".join(tasks)} share this identity; '
                                     'operator must rebind all but one', time.time()))
            if self.db.execute('PRAGMA user_version').fetchone()[0] < SCHEMA_VERSION:   # never downgrade a newer file
                self.db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    @_serialized
    def bind_engine_task(self, task_id: str, fingerprint: str, canonical_key: str) -> str:
        """Pin `task_id` to one task identity before anything is created; returns the fingerprint it is bound to.

        The first binding wins and is durable, so a later run that derives another identity for the same engine task
        (phase, type, target or schema version changed) sees the mismatch even when the first run crashed after the
        issue was created and never recorded anything on the engine side."""
        self.db.execute('BEGIN IMMEDIATE')
        try:
            other = self.db.execute('SELECT task_id FROM engine_bindings WHERE fingerprint=? AND task_id!=?',
                                    (fingerprint, task_id)).fetchone()
            if other is not None:
                raise EngineBindingConflict(f'identity {fingerprint[:16]} is already bound to engine task {other[0]}; resolve with rebind_engine_task')
            self.db.execute('INSERT OR IGNORE INTO engine_bindings(task_id,fingerprint,canonical_key,created_at) VALUES(?,?,?,?)',
                            (task_id, fingerprint, canonical_key, self.clock()))
            bound = self.db.execute('SELECT fingerprint FROM engine_bindings WHERE task_id=?', (task_id,)).fetchone()[0]
            self.db.execute('COMMIT')
            return bound
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    @_serialized
    def engine_binding(self, task_id: str):
        row = self.db.execute('SELECT fingerprint, canonical_key FROM engine_bindings WHERE task_id=?', (task_id,)).fetchone()
        if row is None:
            return None
        other = self.db.execute('SELECT task_id FROM engine_bindings WHERE fingerprint=? AND task_id!=?', (row[0], task_id)).fetchone()
        if other is not None:                       # only a file written by an earlier release can get here
            raise EngineBindingConflict(f'identity {row[0][:16]} is bound to several engine tasks (also {other[0]}); '
                                        'resolve with rebind_engine_task')
        return (row[0], row[1])

    @_serialized
    def rebind_engine_task(self, task_id: str, fingerprint: str, canonical_key: str, note: str) -> None:
        """Operator decision to move an engine task to another identity (the old issue stays as it is)."""
        if not note.strip():
            raise ValueError('a note is required')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            other = self.db.execute('SELECT task_id FROM engine_bindings WHERE fingerprint=? AND task_id!=?',
                                    (fingerprint, task_id)).fetchone()
            if other is not None:
                raise EngineBindingConflict(f'identity {fingerprint[:16]} is already bound to engine task {other[0]}')
            old = self.db.execute('SELECT fingerprint FROM engine_bindings WHERE task_id=?', (task_id,)).fetchone()
            self.db.execute('INSERT OR REPLACE INTO engine_bindings(task_id,fingerprint,canonical_key,created_at) VALUES(?,?,?,?)',
                            (task_id, fingerprint, canonical_key, self.clock()))
            self.db.execute('INSERT INTO governance_incidents(fingerprint,reason,detail,created_at) VALUES(?,?,?,?)',
                            (fingerprint, 'ENGINE_REBOUND', f'{task_id}: {old[0] if old else None} -> {fingerprint}: {note}', self.clock()))
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    @_serialized
    def close(self):
        self.db.close()

    @_serialized
    def get(self, fingerprint: str) -> Mapping | None:
        row = self.db.execute('SELECT * FROM task_mappings WHERE fingerprint=?', (fingerprint,)).fetchone()
        return self._mapping(row) if row else None

    @_serialized
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
            mapping = self.get(fingerprint)                  # read inside the transaction: our token, not a successor's
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise
        return won, mapping

    @_serialized
    def replace_hint(self, fingerprint: str, hint: int | None, legacy=(), note: str = '') -> bool:
        """Operator decision: pin a different hint (or none) on a BLOCKED or RELEASED task.

        Refused (False) for CLAIMED (a live worker holds a fencing token and would not see the change;
        wait for its lease to expire or let it finish) and for MAPPED tasks. A HINT_CONFLICT block is
        lifted by this; the old hint stays in governance_incidents.
        """
        now = self.clock()
        n = self.db.execute(
            'UPDATE task_mappings SET hint_issue=?, hint_legacy=?, updated_at=?, '
            'state=CASE WHEN state=? AND block_reason=? THEN ? ELSE state END, '
            'block_reason=CASE WHEN state=? AND block_reason=? THEN \'\' ELSE block_reason END, '
            'block_candidates=CASE WHEN state=? AND block_reason=? THEN \'[]\' ELSE block_candidates END '
            'WHERE fingerprint=? AND state IN (?, ?)',
            (hint, json.dumps(sorted(set(legacy))) if hint is not None else '[]', now,
             MappingState.BLOCKED, 'HINT_CONFLICT', MappingState.RELEASED,
             MappingState.BLOCKED, 'HINT_CONFLICT', MappingState.BLOCKED, 'HINT_CONFLICT',
             fingerprint, MappingState.BLOCKED, MappingState.RELEASED)).rowcount
        if n:
            self.db.execute('INSERT INTO governance_incidents(fingerprint,reason,detail,created_at) VALUES(?,?,?,?)',
                            (fingerprint, 'HINT_REPLACED', f'hint={hint} {note}'.strip(), now))
        return bool(n)

    @_serialized
    def renew(self, fingerprint: str, token: int) -> bool:
        """Extend the lease if this claim was not taken over. Call right before the irreversible create."""
        cur = self.db.execute(
            'UPDATE task_mappings SET claimed_at=?, updated_at=? WHERE fingerprint=? AND state=? AND claim_token=?',
            (self.clock(), self.clock(), fingerprint, MappingState.CLAIMED, token))
        return cur.rowcount == 1

    @_serialized
    def begin_create(self, fingerprint: str, token: int, repository: str, run: str | None = None) -> bool:
        """Renew the lease and record, before the irreversible create, that a create for `repository` may happen.

        The record outlives a crash: a worker that takes the claim over later never creates blindly (the issue may exist
        while the listing does not show it yet). Only `release(..., create_not_sent=True)`, a later run that finds the
        recorded `run` in `claim_ends` (see `note_claim_ended`) or an operator clears it. `run` names this run of the
        claim; it is the identity the create claim label carries (#68)."""
        now = self.clock()
        cur = self.db.execute(
            'UPDATE task_mappings SET claimed_at=?, updated_at=?, create_intent=1, create_started_at=?, github_repository=?, '
            'create_run=? WHERE fingerprint=? AND state=? AND claim_token=?',
            (now, now, now, repository, run, fingerprint, MappingState.CLAIMED, token))
        return cur.rowcount == 1

    @_serialized
    def note_claim_ended(self, fingerprint: str, run: str) -> None:
        """Record that `run` (see `begin_create`) ended without sending a create request, after it dropped its create claim
        label or tried to. From now on a run of this registry may replace a claim label that still names `run`, and a
        claim row whose intent `run` recorded is stale (#68). Never recorded for a run that may have sent a request."""
        self.db.execute('INSERT OR IGNORE INTO claim_ends(fingerprint,run,ended_at) VALUES(?,?,?)',
                        (fingerprint, run, self.clock()))

    @_serialized
    def claim_ended(self, fingerprint: str, run: str | None) -> bool:
        if not run:
            return False
        return self.db.execute('SELECT 1 FROM claim_ends WHERE fingerprint=? AND run=?', (fingerprint, run)).fetchone() is not None

    @_serialized
    def clear_create_intent(self, fingerprint: str, token: int, note: str) -> bool:
        """Clear a create intent whose run is recorded as ended without a request (`claim_ended`): fenced to the claim
        `token` of the caller, who holds the row now. Records the incident `STALE_INTENT_CLEARED`."""
        now = self.clock()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            n = self.db.execute('UPDATE task_mappings SET create_intent=0, updated_at=? WHERE fingerprint=? AND state=? '
                                'AND claim_token=? AND create_intent=1 AND create_run IS NOT NULL '
                                'AND create_run IN (SELECT run FROM claim_ends WHERE fingerprint=?)',
                                (now, fingerprint, MappingState.CLAIMED, token, fingerprint)).rowcount
            if n:
                self.db.execute('INSERT INTO governance_incidents(fingerprint,reason,detail,created_at) VALUES(?,?,?,?)',
                                (fingerprint, 'STALE_INTENT_CLEARED', note, now))
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise
        return bool(n)

    @_serialized
    def release(self, fingerprint: str, token: int, *, create_not_sent: bool = False) -> None:
        """Give the claim up after a failure that happened before anything was created.

        `create_not_sent=True` (the gateway proved that the create request never left the process) also clears this
        claim's create record."""
        self.db.execute('UPDATE task_mappings SET state=?, updated_at=?, create_intent=CASE WHEN ? THEN 0 ELSE create_intent END '
                        'WHERE fingerprint=? AND state=? AND claim_token=?',
                        (MappingState.RELEASED, self.clock(), int(create_not_sent), fingerprint, MappingState.CLAIMED, token))

    @_serialized
    def confirm_not_created(self, fingerprint: str, note: str, *, quiet_seconds: float = 3600.0) -> bool:
        """Operator decision after checking GitHub: no issue of this task exists, a new create is allowed.

        Clears the create record of a BLOCKED (`CREATE_UNCERTAIN` becomes RELEASED) or RELEASED task; refused (False)
        while a worker holds the claim, for MAPPED tasks, and until `quiet_seconds` have passed since the recorded create
        started: the worker that recorded it may still be paused right before its request. Absence on GitHub alone does
        not prove that it will never send; the operator must also know that worker stopped."""
        if not note.strip():
            raise ValueError('a note is required')
        now = self.clock()
        self.db.execute('BEGIN IMMEDIATE')     # the row, the incident and the note of the run end together or not at all
        try:
            rows = self.db.execute(    # one statement: the quiet period is checked against the intent it clears, not an older read
                "UPDATE task_mappings SET create_intent=0, updated_at=?, "
                "state=CASE WHEN state=? AND block_reason='CREATE_UNCERTAIN' THEN ? ELSE state END, "
                "block_candidates=CASE WHEN state=? AND block_reason='CREATE_UNCERTAIN' THEN '[]' ELSE block_candidates END, "
                "block_reason=CASE WHEN state=? AND block_reason='CREATE_UNCERTAIN' THEN '' ELSE block_reason END "
                "WHERE fingerprint=? AND state IN (?, ?) AND create_intent=1 "
                "AND create_started_at IS NOT NULL AND ? - create_started_at >= ? RETURNING create_run",
                (now, MappingState.BLOCKED, MappingState.RELEASED, MappingState.BLOCKED, MappingState.BLOCKED,
                 fingerprint, MappingState.BLOCKED, MappingState.RELEASED, now, quiet_seconds)).fetchall()
            n = len(rows)
            if n:
                self.db.execute('INSERT INTO governance_incidents(fingerprint,reason,detail,created_at) VALUES(?,?,?,?)',
                                (fingerprint, 'CREATE_INTENT_CLEARED', note, now))
                if rows[0]['create_run']:      # the operator says that run stopped: its claim label may be replaced (#68)
                    self.db.execute('INSERT OR IGNORE INTO claim_ends(fingerprint,run,ended_at) VALUES(?,?,?)',
                                    (fingerprint, rows[0]['create_run'], now))
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise
        return bool(n)

    @_serialized
    def map_issue(self, fingerprint: str, token: int, repository: str, issue_number: int, duplicates=()) -> Mapping | None:
        """Persist the authoritative issue. None means the claim was lost and nothing was written."""
        cur = self.db.execute(
            'UPDATE task_mappings SET state=?, github_repository=?, github_issue_number=?, duplicate_issues=?, '
            'block_reason=\'\', block_candidates=\'[]\', updated_at=? WHERE fingerprint=? AND state=? AND claim_token=?',
            (MappingState.MAPPED, repository, issue_number, json.dumps(sorted(set(duplicates))), self.clock(),
             fingerprint, MappingState.CLAIMED, token))
        if cur.rowcount != 1:
            return None
        if duplicates:      # the local audit trail names every issue recorded as a duplicate (#134 G3)
            self.db.execute('INSERT INTO governance_incidents(fingerprint,reason,detail,created_at) VALUES(?,?,?,?)',
                            (fingerprint, 'DUPLICATES_RECORDED',
                             f'#{issue_number} authoritative; duplicates {sorted(set(duplicates))}', self.clock()))
        return self.get(fingerprint)

    @_serialized
    def block(self, fingerprint: str, reason: str, detail: str = '', *, token: int | None = None,
              candidates=(), expect=None, create_not_sent: bool = False) -> Mapping:
        """Fail closed: record the incident and stop the task, never delete or close anything.

        `candidates` are the issue numbers the block is about (structured, used to judge whether a
        later hint really addresses it). With a token the state change is fenced to that claim. A
        MAPPED task is never downgraded, by anyone: a stale worker or operator call only records
        the incident. `expect=(block_reason, candidates)` changes only that exact block, so a verdict taken on an older
        read cannot overwrite a newer one (the incident is still recorded). `create_not_sent=True` (only with a token)
        also clears the claim's create record in the same fenced statement: the worker proved that no request left.
        """
        now = self.clock()
        cands = json.dumps(sorted(set(candidates)))
        if create_not_sent and token is None:
            raise ValueError('create_not_sent needs the claim token')
        if expect is not None:
            self.db.execute('UPDATE task_mappings SET block_reason=?, block_candidates=?, updated_at=? '
                            'WHERE fingerprint=? AND state=? AND block_reason=? AND block_candidates=?',
                            (reason, cands, now, fingerprint, MappingState.BLOCKED, expect[0],
                             json.dumps(sorted(set(expect[1])))))
        elif token is None:
            self.db.execute('UPDATE task_mappings SET state=?, block_reason=?, block_candidates=?, updated_at=? '
                            'WHERE fingerprint=? AND state<>?',
                            (MappingState.BLOCKED, reason, cands, now, fingerprint, MappingState.MAPPED))
        else:
            self.db.execute('UPDATE task_mappings SET state=?, block_reason=?, block_candidates=?, updated_at=?, '
                            'create_intent=CASE WHEN ? THEN 0 ELSE create_intent END '
                            'WHERE fingerprint=? AND state=? AND claim_token=?',
                            (MappingState.BLOCKED, reason, cands, now, int(create_not_sent), fingerprint,
                             MappingState.CLAIMED, token))
        self.db.execute('INSERT INTO governance_incidents(fingerprint,reason,detail,created_at) VALUES(?,?,?,?)',
                        (fingerprint, reason, detail, now))
        return self.get(fingerprint)

    @_serialized
    def record_incident(self, fingerprint: str, reason: str, detail: str = '') -> None:
        self.db.execute('INSERT INTO governance_incidents(fingerprint,reason,detail,created_at) VALUES(?,?,?,?)',
                        (fingerprint, reason, detail, self.clock()))

    @_serialized
    def add_duplicates(self, fingerprint: str, numbers) -> Mapping | None:
        """Record extra duplicate issue numbers on a MAPPED task without touching its state."""
        row = self.get(fingerprint)
        if row is None:
            return None
        merged = sorted(set(row.duplicate_issues) | set(numbers))
        added = sorted(set(merged) - set(row.duplicate_issues))
        if not added:
            return row
        now = self.clock()
        self.db.execute('UPDATE task_mappings SET duplicate_issues=?, updated_at=? WHERE fingerprint=?',
                        (json.dumps(merged), now, fingerprint))
        self.db.execute('INSERT INTO governance_incidents(fingerprint,reason,detail,created_at) VALUES(?,?,?,?)',
                        (fingerprint, 'DUPLICATES_RECORDED',
                         f'#{row.github_issue_number} authoritative; duplicates added {added}', now))
        return self.get(fingerprint)

    @_serialized
    def unblock(self, fingerprint: str, note: str, *, hint: int | None = None, legacy=(), expect=None) -> bool:
        """Explicit release of a BLOCKED task (one transaction of state-guarded updates, no TOCTOU).

        With a mapped issue the task returns to MAPPED, otherwise to RELEASED (claimable again).
        History stays in governance_incidents. A given `hint`/`legacy` is pinned in the same transaction for every block reason (a rejected hint
        is replaced; a different pinned hint stays and shows up as HINT_CONFLICT), so no run can see the task
        without the hint the operator just supplied. `expect=(block_reason, candidates)` releases only that exact block
        (False otherwise), so a decision taken on an older read cannot lift a block another worker wrote meanwhile.
        """
        now = self.clock()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            # a rejected hint is worthless: swap in the replacement
            row = self.db.execute('SELECT block_reason, block_candidates, hint_issue, hint_legacy FROM task_mappings '
                                  'WHERE fingerprint=? AND state=?', (fingerprint, MappingState.BLOCKED)).fetchone()
            if expect is not None and (row is None or (row['block_reason'], tuple(json.loads(row['block_candidates'])))
                                       != (expect[0], tuple(expect[1]))):
                self.db.execute('COMMIT')
                return False
            if row is not None:
                if row['block_reason'] in HINT_ONLY_BLOCKS and hint is None:
                    # the created issue may exist: a plain release would let the next run create another one
                    raise ValueError(f"{row['block_reason']} can only be released with hint=<issue number> (or replace_hint)")
                if row['block_reason'] == 'HINT_CONFLICT' and hint is None:
                    # a plain release would drop the conflict without deciding which hint is authoritative
                    raise ValueError('HINT_CONFLICT can only be released with hint=<issue number> (or replace_hint)')
                if row['block_reason'] in ('HINT_NOT_FOUND', 'HINT_INVALID'):
                    pin = (hint, sorted(set(legacy))) if hint is not None else None   # replaced only by an explicit new hint
                elif hint is not None and row['hint_issue'] in (None, hint):
                    pin = (hint, sorted(set(json.loads(row['hint_legacy'])) | set(legacy)))  # e.g. MIGRATED_CLAIM
                else:
                    pin = None       # a different pinned hint stays; the next claim reports HINT_CONFLICT
                if pin is not None:
                    self.db.execute('UPDATE task_mappings SET hint_issue=?, hint_legacy=? WHERE fingerprint=?',
                                    (pin[0], json.dumps(pin[1]), fingerprint))
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

    @_serialized
    def incidents(self, fingerprint: str | None = None) -> list[dict]:
        sql, args = 'SELECT * FROM governance_incidents', ()
        if fingerprint:
            sql, args = sql + ' WHERE fingerprint=?', (fingerprint,)
        return [dict(r) for r in self.db.execute(sql + ' ORDER BY id', args)]

    @_serialized
    def count_mappings(self, canonical_key: str) -> int:
        return self.db.execute('SELECT COUNT(*) FROM task_mappings WHERE canonical_key=?', (canonical_key,)).fetchone()[0]

    @staticmethod
    def _mapping(row) -> Mapping:
        return Mapping(row['fingerprint'], row['canonical_key'], MappingState(row['state']), row['claimant'],
                       row['claimed_at'], row['claim_token'], row['github_repository'], row['github_issue_number'],
                       tuple(json.loads(row['duplicate_issues'])), row['block_reason'],
                       tuple(json.loads(row['block_candidates'])), row['hint_issue'],
                       tuple(json.loads(row['hint_legacy'])), bool(row['create_intent']), row['create_run'])
