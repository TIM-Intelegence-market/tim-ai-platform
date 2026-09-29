"""File-backed fake GitHub so threads and separate processes share one 'remote'."""
import sqlite3
import time

from src.task_governance import IssueRef, TaskRequest, fingerprint_marker


class FakeGitHub:
    repository = 'owner/repo'
    max_create_seconds = 5.0

    def __init__(self, path, *, latency=0.0, crash_after_create=False):
        self.path, self.latency, self.crash_after_create = path, latency, crash_after_create
        db = self._db()
        db.execute('CREATE TABLE IF NOT EXISTS issues(number INTEGER PRIMARY KEY, state TEXT, body TEXT, author TEXT DEFAULT \'owner\', is_pr INTEGER DEFAULT 0)')
        db.execute('CREATE TABLE IF NOT EXISTS log(id INTEGER PRIMARY KEY AUTOINCREMENT, op TEXT, number INTEGER, detail TEXT)')
        db.close()

    def _db(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.execute('PRAGMA busy_timeout=30000')
        return db

    def seed(self, number, fingerprint, state='open', extra='', marker=True, author='owner', pr=False):
        """marker=False models issues that predate the fingerprint marker (#11, #22-#65)."""
        db = self._db()
        db.execute('INSERT INTO issues VALUES(?,?,?,?,?)',
                   (number, state, (fingerprint_marker(fingerprint) if marker else 'legacy') + extra, author, int(pr)))
        db.close()

    def find_issues(self, fingerprint, canonical_key):
        db = self._db()
        rows = db.execute('SELECT number,state,author FROM issues WHERE body LIKE ? ORDER BY number',
                          (f'%{fingerprint_marker(fingerprint)}%',)).fetchall()
        db.close()
        time.sleep(self.latency)      # widen the check-then-create window
        return [IssueRef(n, s, author=a) for n, s, a in rows]

    def get_issue(self, number):
        db = self._db()
        row = db.execute('SELECT number,state,author,is_pr FROM issues WHERE number=?', (number,)).fetchone()
        db.close()
        return IssueRef(row[0], row[1], author=row[2], is_pull_request=bool(row[3])) if row else None

    def create_issue(self, request: TaskRequest, fingerprint, *, timeout):
        db = self._db()
        cur = db.execute('INSERT INTO issues(state,body) VALUES(?,?)', ('open', fingerprint_marker(fingerprint)))
        number = cur.lastrowid + 1000
        db.execute('UPDATE issues SET number=? WHERE number=?', (number, cur.lastrowid))
        db.execute('INSERT INTO log(op,number,detail) VALUES(?,?,?)', ('create', number, ''))
        db.close()
        if self.crash_after_create:
            raise RuntimeError('worker died after creating the issue')
        return IssueRef(number, 'open')

    def _log(self, op, number, detail=''):
        db = self._db()
        db.execute('INSERT INTO log(op,number,detail) VALUES(?,?,?)', (op, number, detail))
        db.close()

    def update_issue(self, number, request, reason):
        marker = fingerprint_marker(request.fingerprint)      # back-fills the marker like a real gateway must
        db = self._db()
        db.execute('UPDATE issues SET body=body || ? WHERE number=? AND body NOT LIKE ?', (marker, number, f'%{marker}%'))
        db.close()
        self._log('update', number, reason)

    def reopen_issue(self, number, request, reason):
        db = self._db()
        db.execute('UPDATE issues SET state=? WHERE number=?', ('open', number))
        db.close()
        self._log('reopen', number, reason)

    def is_documented_duplicate(self, number, authoritative):
        db = self._db()
        row = db.execute('SELECT 1 FROM log WHERE op=? AND number=? AND detail=?',
                         ('duplicate', number, f'of #{authoritative}')).fetchone()
        db.close()
        return row is not None

    def mark_duplicate(self, number, authoritative):
        self._log('duplicate', number, f'of #{authoritative}')

    # inspection helpers
    def ops(self, op):
        db = self._db()
        rows = db.execute('SELECT number,detail FROM log WHERE op=? ORDER BY id', (op,)).fetchall()
        db.close()
        return rows

    def state(self, number):
        db = self._db()
        row = db.execute('SELECT state FROM issues WHERE number=?', (number,)).fetchone()
        db.close()
        return row[0]

    def count(self):
        db = self._db()
        n = db.execute('SELECT COUNT(*) FROM issues').fetchone()[0]
        db.close()
        return n
