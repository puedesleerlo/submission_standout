"""Append-only local storage. The SQL boundary is deliberately confined here."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from uuid import uuid4


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def record_id(prefix):
    return f"{prefix}_{uuid4().hex[:16]}"


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS records (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, project_id TEXT NOT NULL,
                    created_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS records_project ON records(project_id, kind, created_at);
                CREATE TABLE IF NOT EXISTS request_keys (
                    project_id TEXT NOT NULL, request_key TEXT NOT NULL,
                    request_hash TEXT NOT NULL, run_id TEXT NOT NULL,
                    PRIMARY KEY(project_id, request_key)
                );
            """)

    @contextmanager
    def connect(self, write=False):
        conn = sqlite3.connect(self.path, timeout=20)
        conn.row_factory = sqlite3.Row
        try:
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def add(self, conn, kind, project_id, payload, identity=None):
        value = {**payload, "id": identity or record_id(kind), "created_at": timestamp()}
        conn.execute("INSERT INTO records VALUES (?, ?, ?, ?, ?)", (
            value["id"], kind, project_id, value["created_at"], json.dumps(value)
        ))
        return value

    def get(self, conn, kind, identity, project_id=None):
        row = conn.execute("SELECT project_id, payload FROM records WHERE id=? AND kind=?", (identity, kind)).fetchone()
        if row is None or (project_id is not None and row["project_id"] != project_id):
            raise KeyError(identity)
        return json.loads(row["payload"])

    def list(self, conn, kind, project_id=None):
        sql, args = "SELECT payload FROM records WHERE kind=?", [kind]
        if project_id is not None:
            sql += " AND project_id=?"
            args.append(project_id)
        return [json.loads(row["payload"]) for row in conn.execute(sql + " ORDER BY created_at, id", args)]

    def event(self, conn, project_id, action, details, actor="observer"):
        return self.add(conn, "event", project_id, {"action": action, "actor": actor, "details": details})
