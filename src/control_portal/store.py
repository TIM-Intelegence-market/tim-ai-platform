from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from .security import hash_password, new_token, token_hash, validate_username, verify_password


ROLES = {"viewer", "operator", "admin"}
CHANGE_CATEGORIES = {"SOURCE", "SECURITY", "NETWORK", "HARDWARE", "STORAGE", "MODEL", "ACCESS"}
CRITICAL_CATEGORIES = {"SECURITY", "NETWORK", "HARDWARE", "ACCESS"}
API_SCOPES = {"tasks:read", "tasks:submit", "changes:read", "system:read"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PortalStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connection() as db:
            db.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('viewer','operator','admin')),
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    created_by INTEGER REFERENCES users(id),
                    last_login_at TEXT
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    csrf_token TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS invites (
                    token_hash TEXT PRIMARY KEY,
                    kind TEXT NOT NULL CHECK(kind IN ('register','reset')),
                    role TEXT NOT NULL CHECK(role IN ('viewer','operator','admin')),
                    target_user_id INTEGER REFERENCES users(id),
                    created_by INTEGER REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    actor_user_id INTEGER REFERENCES users(id),
                    event TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    details_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task_feedback (
                    id INTEGER PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    verdict TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS training_campaigns (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    hypothesis TEXT NOT NULL,
                    target_metrics TEXT NOT NULL,
                    dataset_query TEXT NOT NULL,
                    status TEXT NOT NULL,
                    requested_by INTEGER NOT NULL REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    approved_by INTEGER REFERENCES users(id),
                    approved_at TEXT,
                    result_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS change_requests (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    category TEXT NOT NULL CHECK(category IN ('SOURCE','SECURITY','NETWORK','HARDWARE','STORAGE','MODEL','ACCESS')),
                    reason TEXT NOT NULL,
                    proposed_change TEXT NOT NULL,
                    resource_impact TEXT NOT NULL,
                    rollback_plan TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('PENDING','APPROVED','REJECTED','CANCELLED')),
                    requested_by INTEGER NOT NULL REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    decided_by INTEGER REFERENCES users(id),
                    decided_at TEXT,
                    decision_reason TEXT
                );
                CREATE TABLE IF NOT EXISTS change_votes (
                    change_id INTEGER NOT NULL REFERENCES change_requests(id) ON DELETE CASCADE,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    vote TEXT NOT NULL CHECK(vote IN ('SUPPORT','OBJECT','ABSTAIN')),
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(change_id,user_id)
                );
                CREATE TABLE IF NOT EXISTS api_keys (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    prefix TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    scopes TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    last_used_at TEXT,
                    revoked_at TEXT
                );
                CREATE TABLE IF NOT EXISTS role_requests (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    requested_role TEXT NOT NULL CHECK(requested_role IN ('operator','admin')),
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('PENDING','APPROVED','REJECTED')),
                    created_at TEXT NOT NULL,
                    decided_by INTEGER REFERENCES users(id),
                    decided_at TEXT,
                    decision_reason TEXT
                );
                """
            )
            columns = {str(row[1]) for row in db.execute("PRAGMA table_info(users)")}
            if "is_owner" not in columns:
                db.execute("ALTER TABLE users ADD COLUMN is_owner INTEGER NOT NULL DEFAULT 0")
            if int(db.execute("SELECT COUNT(*) FROM users WHERE is_owner=1").fetchone()[0]) == 0:
                first_admin = db.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1").fetchone()
                if first_admin:
                    db.execute("UPDATE users SET is_owner=1 WHERE id=?", (first_admin["id"],))
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def user_count(self) -> int:
        with self.connection() as db:
            return int(db.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    def create_first_admin(self, username: str, display_name: str, password: str) -> dict[str, Any]:
        username = validate_username(username)
        with self.connection() as db:
            if int(db.execute("SELECT COUNT(*) FROM users").fetchone()[0]) != 0:
                raise ValueError("Der erste Administrator wurde bereits angelegt.")
            cursor = db.execute(
                "INSERT INTO users(username,display_name,password_hash,role,created_at,is_owner) VALUES(?,?,?,?,?,1)",
                (username, display_name.strip() or username, hash_password(password), "admin", utc_now()),
            )
            user_id = int(cursor.lastrowid)
            self._audit(db, user_id, "BOOTSTRAP_ADMIN_CREATED", username, {"role": "admin"})
            return self.get_user(user_id, db=db)

    def authenticate(self, username: str, password: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM users WHERE username=?", (username.strip().lower(),)).fetchone()
            if not row or not row["active"] or not verify_password(password, row["password_hash"]):
                return None
            db.execute("UPDATE users SET last_login_at=? WHERE id=?", (utc_now(), row["id"]))
            self._audit(db, row["id"], "LOGIN", row["username"], {})
            return dict(row)

    def create_session(self, user_id: int, hours: int = 12) -> tuple[str, str]:
        raw, csrf = new_token(), new_token()
        now = datetime.now(timezone.utc)
        with self.connection() as db:
            db.execute("DELETE FROM sessions WHERE expires_at < ?", (now.isoformat(),))
            db.execute(
                "INSERT INTO sessions(token_hash,user_id,csrf_token,created_at,expires_at) VALUES(?,?,?,?,?)",
                (token_hash(raw), user_id, csrf, now.isoformat(), (now + timedelta(hours=hours)).isoformat()),
            )
        return raw, csrf

    def session_user(self, raw: str | None) -> tuple[dict[str, Any], str] | None:
        if not raw:
            return None
        with self.connection() as db:
            row = db.execute(
                """SELECT users.*, sessions.csrf_token, sessions.expires_at
                   FROM sessions JOIN users ON users.id=sessions.user_id
                   WHERE sessions.token_hash=? AND users.active=1""",
                (token_hash(raw),),
            ).fetchone()
            if not row or datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
                return None
            value = dict(row)
            csrf = str(value.pop("csrf_token"))
            value.pop("password_hash", None)
            return value, csrf

    def delete_session(self, raw: str | None) -> None:
        if raw:
            with self.connection() as db:
                db.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(raw),))

    def list_users(self) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT id,username,display_name,role,active,is_owner,created_at,last_login_at FROM users ORDER BY username"
            ).fetchall()
            return [dict(row) for row in rows]

    def get_user(self, user_id: int, *, db: sqlite3.Connection | None = None) -> dict[str, Any]:
        if db is None:
            with self.connection() as connection:
                return self.get_user(user_id, db=connection)
        row = db.execute(
            "SELECT id,username,display_name,role,active,is_owner,created_at,last_login_at FROM users WHERE id=?",
            (user_id,),
        ).fetchone()
        if not row:
            raise ValueError("Benutzer nicht gefunden.")
        return dict(row)

    def create_invite(
        self, actor_id: int, role: str, *, kind: str = "register", target_username: str | None = None
    ) -> str:
        if role not in ROLES or kind not in {"register", "reset"}:
            raise ValueError("Ungültige Einladung.")
        if kind == "register":
            role = "viewer"
        raw = new_token()
        now = datetime.now(timezone.utc)
        with self.connection() as db:
            target_id = None
            if kind == "reset":
                row = db.execute("SELECT id,role FROM users WHERE username=?", (validate_username(target_username or ""),)).fetchone()
                if not row:
                    raise ValueError("Benutzer nicht gefunden.")
                target_id, role = int(row["id"]), str(row["role"])
            db.execute(
                "INSERT INTO invites(token_hash,kind,role,target_user_id,created_by,created_at,expires_at) VALUES(?,?,?,?,?,?,?)",
                (token_hash(raw), kind, role, target_id, actor_id, now.isoformat(), (now + timedelta(hours=24)).isoformat()),
            )
            self._audit(db, actor_id, "INVITE_CREATED", target_username or role, {"kind": kind, "role": role})
        return raw

    def invite_info(self, raw: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute(
                """SELECT invites.*, users.username AS target_username
                   FROM invites LEFT JOIN users ON users.id=invites.target_user_id
                   WHERE token_hash=? AND used_at IS NULL""",
                (token_hash(raw),),
            ).fetchone()
            if not row or datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
                return None
            return dict(row)

    def redeem_invite(self, raw: str, username: str, display_name: str, password: str) -> dict[str, Any]:
        validate_password_hash = hash_password(password)
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM invites WHERE token_hash=? AND used_at IS NULL", (token_hash(raw),)
            ).fetchone()
            if not row or datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
                raise ValueError("Einladung ist ungültig oder abgelaufen.")
            if row["kind"] == "reset":
                user_id = int(row["target_user_id"])
                db.execute("UPDATE users SET password_hash=? WHERE id=?", (validate_password_hash, user_id))
                db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
                user = self.get_user(user_id, db=db)
                event = "PASSWORD_RESET"
            else:
                normalized = validate_username(username)
                cursor = db.execute(
                    "INSERT INTO users(username,display_name,password_hash,role,created_at,created_by) VALUES(?,?,?,?,?,?)",
                    (normalized, display_name.strip() or normalized, validate_password_hash, row["role"], utc_now(), row["created_by"]),
                )
                user_id = int(cursor.lastrowid)
                user = self.get_user(user_id, db=db)
                event = "USER_REGISTERED"
            db.execute("UPDATE invites SET used_at=? WHERE token_hash=?", (utc_now(), token_hash(raw)))
            self._audit(db, user_id, event, user["username"], {"role": user["role"]})
            return user

    def change_password(self, user_id: int, current: str, new: str) -> None:
        new_hash = hash_password(new)
        with self.connection() as db:
            row = db.execute("SELECT username,password_hash FROM users WHERE id=?", (user_id,)).fetchone()
            if not row or not verify_password(current, row["password_hash"]):
                raise ValueError("Das aktuelle Passwort ist falsch.")
            db.execute("UPDATE users SET password_hash=? WHERE id=?", (new_hash, user_id))
            db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            self._audit(db, user_id, "PASSWORD_CHANGED", row["username"], {})

    def set_user_active(self, actor_id: int, target_id: int, active: bool) -> None:
        if actor_id == target_id and not active:
            raise ValueError("Das eigene Administratorkonto kann nicht deaktiviert werden.")
        with self.connection() as db:
            actor = self.get_user(actor_id, db=db)
            user = self.get_user(target_id, db=db)
            if user["is_owner"] and not active:
                raise ValueError("Das Eigentümerkonto kann nicht deaktiviert werden.")
            if user["role"] == "admin" and not actor["is_owner"]:
                raise ValueError("Nur der Eigentümer darf Administratorkonten deaktivieren.")
            db.execute("UPDATE users SET active=? WHERE id=?", (1 if active else 0, target_id))
            if not active:
                db.execute("DELETE FROM sessions WHERE user_id=?", (target_id,))
            self._audit(db, actor_id, "USER_STATUS_CHANGED", user["username"], {"active": active})

    def create_role_request(self, user_id: int, requested_role: str, reason: str) -> int:
        requested_role = requested_role.strip().lower()
        if requested_role not in {"operator", "admin"} or not reason.strip():
            raise ValueError("Zielrolle und Begründung sind erforderlich.")
        with self.connection() as db:
            user = self.get_user(user_id, db=db)
            if user["role"] == requested_role:
                raise ValueError("Diese Rolle ist bereits aktiv.")
            if db.execute("SELECT 1 FROM role_requests WHERE user_id=? AND status='PENDING'", (user_id,)).fetchone():
                raise ValueError("Es existiert bereits ein offener Rollenantrag.")
            cursor = db.execute(
                "INSERT INTO role_requests(user_id,requested_role,reason,status,created_at) VALUES(?,?,?,'PENDING',?)",
                (user_id, requested_role, reason.strip()[:2000], utc_now()),
            )
            request_id = int(cursor.lastrowid)
            self._audit(db, user_id, "ROLE_REQUESTED", str(request_id), {"requested_role": requested_role})
            return request_id

    def list_role_requests(self, *, pending_only: bool = False) -> list[dict[str, Any]]:
        with self.connection() as db:
            where = "WHERE role_requests.status='PENDING'" if pending_only else ""
            rows = db.execute(
                f"""SELECT role_requests.*, users.username,users.display_name,users.role AS current_role,
                           decider.username AS decided_by_name
                    FROM role_requests JOIN users ON users.id=role_requests.user_id
                    LEFT JOIN users decider ON decider.id=role_requests.decided_by
                    {where} ORDER BY role_requests.id DESC"""
            ).fetchall()
            return [dict(row) for row in rows]

    def decide_role_request(self, request_id: int, actor_id: int, decision: str, reason: str) -> None:
        decision = decision.strip().upper()
        if decision not in {"APPROVED", "REJECTED"} or not reason.strip():
            raise ValueError("Entscheidung und Begründung sind erforderlich.")
        with self.connection() as db:
            actor = self.get_user(actor_id, db=db)
            request = db.execute("SELECT * FROM role_requests WHERE id=? AND status='PENDING'", (request_id,)).fetchone()
            if not request:
                raise ValueError("Offener Rollenantrag nicht gefunden.")
            if request["requested_role"] == "admin" and not actor["is_owner"]:
                raise ValueError("Nur der Eigentümer darf Administratorrechte vergeben.")
            db.execute(
                "UPDATE role_requests SET status=?,decided_by=?,decided_at=?,decision_reason=? WHERE id=?",
                (decision, actor_id, utc_now(), reason.strip()[:2000], request_id),
            )
            if decision == "APPROVED":
                db.execute("UPDATE users SET role=? WHERE id=?", (request["requested_role"], request["user_id"]))
                db.execute("DELETE FROM sessions WHERE user_id=?", (request["user_id"],))
            self._audit(db, actor_id, f"ROLE_{decision}", str(request_id), {"role": request["requested_role"], "user_id": request["user_id"]})

    def add_feedback(self, task_id: str, user_id: int, verdict: str, notes: str) -> None:
        if verdict not in {"USEFUL", "NEEDS_WORK", "REJECTED", "APPROVED_FOR_LEARNING"}:
            raise ValueError("Ungültige Bewertung.")
        with self.connection() as db:
            db.execute(
                "INSERT INTO task_feedback(task_id,user_id,verdict,notes,created_at) VALUES(?,?,?,?,?)",
                (task_id, user_id, verdict, notes[:4000], utc_now()),
            )
            self._audit(db, user_id, "TASK_FEEDBACK", task_id, {"verdict": verdict})

    def feedback_for(self, task_id: str) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                """SELECT task_feedback.*, users.username FROM task_feedback
                   JOIN users ON users.id=task_feedback.user_id
                   WHERE task_id=? ORDER BY task_feedback.id DESC""",
                (task_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def create_campaign(
        self, user_id: int, name: str, hypothesis: str, metrics: str, dataset_query: str
    ) -> int:
        if not name.strip() or not hypothesis.strip() or not metrics.strip():
            raise ValueError("Name, Hypothese und Zielmetriken sind erforderlich.")
        with self.connection() as db:
            cursor = db.execute(
                """INSERT INTO training_campaigns
                   (name,hypothesis,target_metrics,dataset_query,status,requested_by,created_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (name[:120], hypothesis[:4000], metrics[:2000], dataset_query[:2000], "DRAFT", user_id, utc_now()),
            )
            campaign_id = int(cursor.lastrowid)
            self._audit(db, user_id, "TRAINING_CAMPAIGN_CREATED", str(campaign_id), {"name": name[:120]})
            return campaign_id

    def list_campaigns(self) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                """SELECT training_campaigns.*, users.username AS requested_by_name
                   FROM training_campaigns JOIN users ON users.id=training_campaigns.requested_by
                   ORDER BY training_campaigns.id DESC"""
            ).fetchall()
            return [dict(row) for row in rows]

    def create_change_request(
        self, user_id: int, title: str, category: str, reason: str,
        proposed_change: str, resource_impact: str, rollback_plan: str,
    ) -> int:
        category = category.strip().upper()
        fields = [title.strip(), reason.strip(), proposed_change.strip(), resource_impact.strip(), rollback_plan.strip()]
        if category not in CHANGE_CATEGORIES:
            raise ValueError("Ungültige Änderungskategorie.")
        if any(not value for value in fields):
            raise ValueError("Alle Felder des Änderungsantrags sind erforderlich.")
        with self.connection() as db:
            cursor = db.execute(
                """INSERT INTO change_requests
                   (title,category,reason,proposed_change,resource_impact,rollback_plan,status,requested_by,created_at)
                   VALUES(?,?,?,?,?,?,'PENDING',?,?)""",
                (fields[0][:160], category, fields[1][:4000], fields[2][:8000], fields[3][:4000], fields[4][:4000], user_id, utc_now()),
            )
            change_id = int(cursor.lastrowid)
            self._audit(db, user_id, "CHANGE_REQUESTED", str(change_id), {"category": category, "title": fields[0][:160]})
            return change_id

    def list_change_requests(self) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                """SELECT change_requests.*, requester.username AS requested_by_name,
                          decider.username AS decided_by_name,
                          (SELECT COUNT(*) FROM change_votes WHERE change_id=change_requests.id AND vote='SUPPORT') AS support_count,
                          (SELECT COUNT(*) FROM change_votes WHERE change_id=change_requests.id AND vote='OBJECT') AS object_count
                   FROM change_requests
                   JOIN users requester ON requester.id=change_requests.requested_by
                   LEFT JOIN users decider ON decider.id=change_requests.decided_by
                   ORDER BY change_requests.id DESC"""
            ).fetchall()
            return [dict(row) for row in rows]

    def get_change_request(self, change_id: int) -> dict[str, Any]:
        with self.connection() as db:
            row = db.execute(
                """SELECT change_requests.*, requester.username AS requested_by_name,
                          decider.username AS decided_by_name
                   FROM change_requests JOIN users requester ON requester.id=change_requests.requested_by
                   LEFT JOIN users decider ON decider.id=change_requests.decided_by
                   WHERE change_requests.id=?""", (change_id,),
            ).fetchone()
            if not row:
                raise ValueError("Änderungsantrag nicht gefunden.")
            return dict(row)

    def votes_for_change(self, change_id: int) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                """SELECT change_votes.*, users.username FROM change_votes
                   JOIN users ON users.id=change_votes.user_id WHERE change_id=? ORDER BY created_at""", (change_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def vote_change(self, change_id: int, user_id: int, vote: str, reason: str) -> None:
        vote = vote.strip().upper()
        if vote not in {"SUPPORT", "OBJECT", "ABSTAIN"} or not reason.strip():
            raise ValueError("Abstimmung und Begründung sind erforderlich.")
        with self.connection() as db:
            request = db.execute("SELECT status FROM change_requests WHERE id=?", (change_id,)).fetchone()
            if not request or request["status"] != "PENDING":
                raise ValueError("Nur offene Anträge können bewertet werden.")
            db.execute(
                """INSERT INTO change_votes(change_id,user_id,vote,reason,created_at) VALUES(?,?,?,?,?)
                   ON CONFLICT(change_id,user_id) DO UPDATE SET vote=excluded.vote,reason=excluded.reason,created_at=excluded.created_at""",
                (change_id, user_id, vote, reason[:2000], utc_now()),
            )
            self._audit(db, user_id, "CHANGE_VOTE", str(change_id), {"vote": vote})

    def decide_change(self, change_id: int, admin_id: int, decision: str, reason: str) -> None:
        decision = decision.strip().upper()
        if decision not in {"APPROVED", "REJECTED"} or not reason.strip():
            raise ValueError("Entscheidung und Begründung sind erforderlich.")
        with self.connection() as db:
            request = db.execute("SELECT * FROM change_requests WHERE id=?", (change_id,)).fetchone()
            if not request or request["status"] != "PENDING":
                raise ValueError("Der Antrag ist nicht offen.")
            if decision == "APPROVED" and request["category"] in CRITICAL_CATEGORIES and int(request["requested_by"]) == admin_id:
                raise ValueError("Kritische eigene Anträge benötigen die Freigabe eines zweiten Administrators.")
            db.execute(
                """UPDATE change_requests SET status=?,decided_by=?,decided_at=?,decision_reason=? WHERE id=?""",
                (decision, admin_id, utc_now(), reason[:4000], change_id),
            )
            self._audit(db, admin_id, f"CHANGE_{decision}", str(change_id), {"reason": reason[:4000]})

    def create_api_key(self, user_id: int, name: str, scopes: set[str], days: int = 30) -> str:
        if not name.strip() or not scopes or not scopes.issubset(API_SCOPES):
            raise ValueError("Name und zulässige API-Berechtigungen sind erforderlich.")
        if days < 1 or days > 365:
            raise ValueError("API-Schlüssel dürfen 1 bis 365 Tage gültig sein.")
        raw = "timec_" + new_token()
        now = datetime.now(timezone.utc)
        with self.connection() as db:
            owner = db.execute("SELECT role,active FROM users WHERE id=?", (user_id,)).fetchone()
            if not owner or not owner["active"]:
                raise ValueError("Aktives Benutzerkonto nicht gefunden.")
            if "tasks:submit" in scopes and owner["role"] == "viewer":
                raise ValueError("Viewer dürfen keine Task-Schlüssel erstellen.")
            db.execute(
                """INSERT INTO api_keys(user_id,name,prefix,token_hash,scopes,created_at,expires_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (user_id, name.strip()[:120], raw[:14], token_hash(raw), " ".join(sorted(scopes)), now.isoformat(), (now + timedelta(days=days)).isoformat()),
            )
            self._audit(db, user_id, "API_KEY_CREATED", name.strip()[:120], {"scopes": sorted(scopes), "days": days})
        return raw

    def list_api_keys(self, user_id: int) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                """SELECT id,name,prefix,scopes,created_at,expires_at,last_used_at,revoked_at
                   FROM api_keys WHERE user_id=? ORDER BY id DESC""", (user_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def revoke_api_key(self, user_id: int, key_id: int) -> None:
        with self.connection() as db:
            cursor = db.execute("UPDATE api_keys SET revoked_at=? WHERE id=? AND user_id=? AND revoked_at IS NULL", (utc_now(), key_id, user_id))
            if cursor.rowcount != 1:
                raise ValueError("Aktiver API-Schlüssel nicht gefunden.")
            self._audit(db, user_id, "API_KEY_REVOKED", str(key_id), {})

    def list_all_api_keys(self) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                """SELECT api_keys.id,api_keys.user_id,users.username,api_keys.name,api_keys.prefix,api_keys.scopes,
                          api_keys.created_at,api_keys.expires_at,api_keys.last_used_at,api_keys.revoked_at
                   FROM api_keys JOIN users ON users.id=api_keys.user_id ORDER BY api_keys.id DESC"""
            ).fetchall()
            return [dict(row) for row in rows]

    def admin_revoke_api_key(self, actor_id: int, key_id: int) -> None:
        with self.connection() as db:
            row = db.execute("SELECT name,user_id,revoked_at FROM api_keys WHERE id=?", (key_id,)).fetchone()
            if not row or row["revoked_at"]:
                raise ValueError("Aktiver API-Schlüssel nicht gefunden.")
            db.execute("UPDATE api_keys SET revoked_at=? WHERE id=?", (utc_now(), key_id))
            self._audit(db, actor_id, "API_KEY_ADMIN_REVOKED", str(key_id), {"owner_user_id": row["user_id"], "name": row["name"]})

    def authenticate_api_key(self, raw: str, required_scope: str) -> dict[str, Any] | None:
        if required_scope not in API_SCOPES:
            return None
        with self.connection() as db:
            row = db.execute(
                """SELECT api_keys.*, users.username,users.display_name,users.role,users.active
                   FROM api_keys JOIN users ON users.id=api_keys.user_id WHERE token_hash=?""", (token_hash(raw),),
            ).fetchone()
            if not row or not row["active"] or row["revoked_at"] or datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
                return None
            if required_scope not in set(str(row["scopes"]).split()):
                return None
            db.execute("UPDATE api_keys SET last_used_at=? WHERE id=?", (utc_now(), row["id"]))
            self._audit(db, int(row["user_id"]), "API_KEY_USED", str(row["id"]), {"scope": required_scope})
            return dict(row)

    def audit_events(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                """SELECT audit_events.*, users.username FROM audit_events
                   LEFT JOIN users ON users.id=audit_events.actor_user_id
                   ORDER BY audit_events.id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def audit(self, actor_id: int | None, event: str, subject: str, details: dict[str, Any]) -> None:
        with self.connection() as db:
            self._audit(db, actor_id, event, subject, details)

    @staticmethod
    def _audit(
        db: sqlite3.Connection, actor_id: int | None, event: str, subject: str, details: dict[str, Any]
    ) -> None:
        db.execute(
            "INSERT INTO audit_events(created_at,actor_user_id,event,subject,details_json) VALUES(?,?,?,?,?)",
            (utc_now(), actor_id, event, subject[:240], json.dumps(details, sort_keys=True)),
        )
