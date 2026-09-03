from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator

from .models import ALLOWED_TRANSITIONS, STATE_ORDER, WORKFLOW_STATES


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lessons (
    lesson_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    title TEXT NOT NULL,
    source_url TEXT NOT NULL,
    status TEXT NOT NULL,
    source_hash TEXT,
    captured_at TEXT,
    reviewed_at TEXT,
    card_path TEXT,
    last_error_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id INTEGER PRIMARY KEY AUTOINCREMENT,
    lesson_id TEXT NOT NULL REFERENCES lessons(lesson_id),
    kind TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(lesson_id, kind, sha256)
);
CREATE TABLE IF NOT EXISTS source_refs (
    source_ref_id INTEGER PRIMARY KEY AUTOINCREMENT,
    lesson_id TEXT NOT NULL REFERENCES lessons(lesson_id),
    source_kind TEXT NOT NULL,
    locator TEXT NOT NULL,
    source_hash TEXT,
    evidence_level TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(lesson_id, source_kind, locator, source_hash)
);
CREATE TABLE IF NOT EXISTS workflow_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    lesson_id TEXT REFERENCES lessons(lesson_id),
    from_state TEXT,
    to_state TEXT NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
    approval_id INTEGER PRIMARY KEY AUTOINCREMENT,
    lesson_id TEXT NOT NULL REFERENCES lessons(lesson_id),
    artifact_sha256 TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    reviewer_note TEXT NOT NULL,
    approved_at TEXT NOT NULL,
    revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS source_reads (
    source_read_id INTEGER PRIMARY KEY AUTOINCREMENT,
    lesson_id TEXT NOT NULL REFERENCES lessons(lesson_id),
    source_hash TEXT NOT NULL,
    language TEXT NOT NULL,
    track_sha256 TEXT NOT NULL,
    cursor TEXT NOT NULL,
    next_cursor TEXT,
    characters INTEGER NOT NULL,
    packet_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lessons_status ON lessons(status);
CREATE INDEX IF NOT EXISTS idx_artifacts_lesson ON artifacts(lesson_id, kind);
CREATE INDEX IF NOT EXISTS idx_events_lesson ON workflow_events(lesson_id, event_id);
CREATE INDEX IF NOT EXISTS idx_approvals_lesson ON approvals(lesson_id, approval_id);
CREATE INDEX IF NOT EXISTS idx_source_reads_lesson ON source_reads(lesson_id, source_read_id);
"""

SCHEMA_VERSION = "2"
COLLECTOR_STATES = {"discovered", "auth_required", "captured", "failed", "needs_attention"}


class WorkflowDB:
    def __init__(self, path: Path, project_id: str):
        self.path = path
        self.project_id = project_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )
                version_row = connection.execute(
                    "SELECT value FROM metadata WHERE key='schema_version'"
                ).fetchone()
                if version_row and str(version_row["value"]) not in {"1", SCHEMA_VERSION}:
                    raise ValueError("unsupported workflow database schema version")
                project_row = connection.execute(
                    "SELECT value FROM metadata WHERE key='project_id'"
                ).fetchone()
                if project_row and str(project_row["value"]) != project_id:
                    raise ValueError("workflow database belongs to a different project_id")
                if not project_row:
                    lessons_table = connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='lessons'"
                    ).fetchone()
                    if lessons_table:
                        legacy_projects = {
                            str(row["project_id"])
                            for row in connection.execute(
                                "SELECT DISTINCT project_id FROM lessons"
                            ).fetchall()
                            if row["project_id"]
                        }
                        if legacy_projects and legacy_projects != {project_id}:
                            raise ValueError("workflow database belongs to a different project_id")
                # executescript() commits an existing transaction implicitly.
                # Execute each simple schema statement separately so the
                # migration remains protected by BEGIN IMMEDIATE.
                for statement in SCHEMA.split(";"):
                    if statement.strip():
                        connection.execute(statement)
                source_read_columns = {
                    str(row["name"])
                    for row in connection.execute("PRAGMA table_info(source_reads)").fetchall()
                }
                if "track_sha256" not in source_read_columns:
                    connection.execute("ALTER TABLE source_reads ADD COLUMN track_sha256 TEXT")
                stored_projects = {
                    str(row["project_id"])
                    for row in connection.execute(
                        "SELECT DISTINCT project_id FROM lessons"
                    ).fetchall()
                    if row["project_id"]
                }
                if stored_projects and stored_projects != {project_id}:
                    raise ValueError("workflow database contains rows for a different project_id")
                connection.execute(
                    "INSERT OR REPLACE INTO metadata(key, value) VALUES('schema_version', ?)",
                    (SCHEMA_VERSION,),
                )
                connection.execute(
                    "INSERT OR IGNORE INTO metadata(key, value) VALUES('project_id', ?)",
                    (project_id,),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        try:
            self.path.chmod(0o600)
        except OSError:
            pass
        self._repair_preapproval_states()

    def _repair_preapproval_states(self) -> None:
        """Fail closed when opening a v1-alpha ledger that had no hash-bound approvals."""
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT lesson_id, status FROM lessons
                WHERE status IN ('reviewed', 'validated', 'synced')
                  AND NOT EXISTS (
                    SELECT 1 FROM approvals
                    WHERE approvals.lesson_id=lessons.lesson_id AND revoked_at IS NULL
                  )
                """
            ).fetchall()
            for row in rows:
                connection.execute(
                    "UPDATE lessons SET status='captured', updated_at=? WHERE lesson_id=?",
                    (utc_now(), row["lesson_id"]),
                )
                self._insert_event(
                    connection,
                    str(row["lesson_id"]),
                    str(row["status"]),
                    "captured",
                    "schema-migration",
                    "v1 semantic state lacked a hash-bound local approval; review required",
                )
            connection.commit()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            connection.execute("PRAGMA journal_mode = WAL")
        except sqlite3.OperationalError as exc:
            # A simultaneous first opener may be switching the database to
            # WAL. BEGIN IMMEDIATE below still serializes schema work, and a
            # later connection will observe or complete the WAL transition.
            if "locked" not in str(exc).lower():
                connection.close()
                raise
        try:
            yield connection
        finally:
            connection.close()

    def upsert_lesson(self, lesson: dict[str, Any], actor: str = "collector-sync") -> dict[str, Any]:
        incoming_status = str(lesson["status"])
        if incoming_status not in WORKFLOW_STATES:
            raise ValueError(f"unsupported workflow status: {incoming_status}")
        if actor == "collector-sync" and incoming_status not in COLLECTOR_STATES:
            raise ValueError("collector cannot set semantic review or publication state")
        now = utc_now()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM lessons WHERE lesson_id = ?", (lesson["lesson_id"],)
            ).fetchone()
            if existing:
                current_status = str(existing["status"])
                old_hash = existing["source_hash"]
                new_hash = lesson.get("source_hash")
                source_changed = bool(old_hash and new_hash and old_hash != new_hash)
                legacy_source_hash = lesson.get("legacy_source_hash")
                has_downstream_evidence = False
                if source_changed and current_status in {"discovered", "captured"}:
                    downstream = connection.execute(
                        """
                        SELECT
                            EXISTS(SELECT 1 FROM artifacts WHERE lesson_id=?) AS has_artifacts,
                            EXISTS(SELECT 1 FROM source_refs WHERE lesson_id=?) AS has_source_refs,
                            EXISTS(
                                SELECT 1 FROM approvals
                                WHERE lesson_id=? AND revoked_at IS NULL
                            ) AS has_active_approvals
                        """,
                        (lesson["lesson_id"], lesson["lesson_id"], lesson["lesson_id"]),
                    ).fetchone()
                    has_downstream_evidence = bool(
                        downstream
                        and (
                            downstream["has_artifacts"]
                            or downstream["has_source_refs"]
                            or downstream["has_active_approvals"]
                        )
                    )
                safe_fingerprint_migration = bool(
                    source_changed
                    and actor == "collector-sync"
                    and current_status in {"discovered", "captured"}
                    and legacy_source_hash
                    and old_hash == legacy_source_hash
                    and not has_downstream_evidence
                )
                guarded_source_change = source_changed and not safe_fingerprint_migration
                status = "needs_attention" if guarded_source_change else incoming_status
                if not guarded_source_change and current_status == "needs_attention":
                    status = current_status
                if not guarded_source_change and STATE_ORDER.get(current_status, 0) > STATE_ORDER.get(incoming_status, 0):
                    status = current_status
                connection.execute(
                    """
                    UPDATE lessons SET title=?, source_url=?, status=?, source_hash=?,
                        captured_at=?, reviewed_at=COALESCE(?, reviewed_at),
                        card_path=COALESCE(?, card_path), last_error_json=?, updated_at=?
                    WHERE lesson_id=?
                    """,
                    (
                        lesson["title"], lesson["source_url"], status,
                        lesson.get("source_hash"), lesson.get("captured_at"),
                        lesson.get("reviewed_at"), lesson.get("card_path"),
                        json.dumps(lesson.get("last_error"), ensure_ascii=False)
                        if lesson.get("last_error") else None,
                        now, lesson["lesson_id"],
                    ),
                )
                if guarded_source_change:
                    connection.execute(
                        "UPDATE artifacts SET status='stale' WHERE lesson_id=?",
                        (lesson["lesson_id"],),
                    )
                    connection.execute(
                        "UPDATE approvals SET revoked_at=? WHERE lesson_id=? AND revoked_at IS NULL",
                        (now, lesson["lesson_id"]),
                    )
                    connection.execute(
                        "DELETE FROM source_refs WHERE lesson_id=?",
                        (lesson["lesson_id"],),
                    )
                    self._insert_event(
                        connection,
                        lesson["lesson_id"],
                        current_status,
                        status,
                        actor,
                        "source hash changed; prior review and validation revoked",
                    )
                elif safe_fingerprint_migration:
                    self._insert_event(
                        connection,
                        lesson["lesson_id"],
                        current_status,
                        status,
                        actor,
                        (
                            "source hash fingerprint algorithm migrated before semantic work; "
                            "prior source reads no longer match"
                        ),
                    )
                elif status != current_status:
                    self._insert_event(connection, lesson["lesson_id"], current_status, status, actor, "collector state refresh")
            else:
                connection.execute(
                    """
                    INSERT INTO lessons(
                        lesson_id, project_id, title, source_url, status, source_hash,
                        captured_at, reviewed_at, card_path, last_error_json, created_at, updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        lesson["lesson_id"], self.project_id, lesson["title"],
                        lesson["source_url"], incoming_status, lesson.get("source_hash"),
                        lesson.get("captured_at"), lesson.get("reviewed_at"), lesson.get("card_path"),
                        json.dumps(lesson.get("last_error"), ensure_ascii=False)
                        if lesson.get("last_error") else None,
                        now, now,
                    ),
                )
                self._insert_event(connection, lesson["lesson_id"], None, incoming_status, actor, "lesson discovered")
            connection.commit()
        return self.get_lesson(str(lesson["lesson_id"]))

    def _insert_event(
        self,
        connection: sqlite3.Connection,
        lesson_id: str | None,
        from_state: str | None,
        to_state: str,
        actor: str,
        reason: str,
    ) -> None:
        connection.execute(
            "INSERT INTO workflow_events(lesson_id, from_state, to_state, actor, reason, created_at) VALUES(?,?,?,?,?,?)",
            (lesson_id, from_state, to_state, actor[:80], reason[:500], utc_now()),
        )

    def transition(self, lesson_id: str, to_state: str, actor: str, reason: str) -> dict[str, Any]:
        if to_state not in WORKFLOW_STATES:
            raise ValueError("invalid destination state")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status FROM lessons WHERE lesson_id=?", (lesson_id,)
            ).fetchone()
            if not row:
                raise ValueError("unknown lesson_id")
            current = str(row["status"])
            if current == to_state:
                connection.rollback()
                return self.get_lesson(lesson_id)
            if to_state not in ALLOWED_TRANSITIONS.get(current, set()):
                raise ValueError(f"invalid workflow transition: {current} -> {to_state}")
            forward_gate = (current, to_state) in {
                ("drafted", "reviewed"),
                ("reviewed", "validated"),
                ("validated", "synced"),
            }
            if forward_gate:
                lesson_row = connection.execute(
                    "SELECT source_hash FROM lessons WHERE lesson_id=?", (lesson_id,)
                ).fetchone()
                approval = connection.execute(
                    """
                    SELECT * FROM approvals
                    WHERE lesson_id=? AND revoked_at IS NULL
                    ORDER BY approval_id DESC LIMIT 1
                    """,
                    (lesson_id,),
                ).fetchone()
                required_artifact_status = "reviewed" if to_state == "reviewed" else "validated"
                artifact = connection.execute(
                    """
                    SELECT * FROM artifacts
                    WHERE lesson_id=? AND kind='lesson_draft'
                    ORDER BY artifact_id DESC LIMIT 1
                    """,
                    (lesson_id,),
                ).fetchone()
                if (
                    not lesson_row
                    or not lesson_row["source_hash"]
                    or not approval
                    or not artifact
                    or approval["source_hash"] != lesson_row["source_hash"]
                    or approval["artifact_sha256"] != artifact["sha256"]
                    or artifact["status"] != required_artifact_status
                ):
                    connection.rollback()
                    raise ValueError("workflow transition lacks a matching hash-bound approval artifact")
                if to_state == "synced":
                    vault_note = connection.execute(
                        """
                        SELECT sha256 FROM artifacts
                        WHERE lesson_id=? AND kind='vault_note' AND status='synced'
                        ORDER BY artifact_id DESC LIMIT 1
                        """,
                        (lesson_id,),
                    ).fetchone()
                    if not vault_note or vault_note["sha256"] != artifact["sha256"]:
                        connection.rollback()
                        raise ValueError("synced transition lacks a matching Vault receipt")
            updated = connection.execute(
                "UPDATE lessons SET status=?, updated_at=? WHERE lesson_id=? AND status=?",
                (to_state, utc_now(), lesson_id, current),
            )
            if updated.rowcount != 1:
                connection.rollback()
                raise ValueError("workflow state changed concurrently; retry")
            self._insert_event(connection, lesson_id, current, to_state, actor, reason)
            connection.commit()
        return self.get_lesson(lesson_id)

    def set_card_path(self, lesson_id: str, card_path: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE lessons SET card_path=?, updated_at=? WHERE lesson_id=?",
                (card_path, utc_now(), lesson_id),
            )
            connection.commit()

    def add_artifact(self, lesson_id: str, kind: str, path: str, sha256: str, status: str) -> dict[str, Any]:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO artifacts(lesson_id, kind, path, sha256, status, created_at)
                VALUES(?,?,?,?,?,?)
                """,
                (lesson_id, kind, path, sha256, status, utc_now()),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM artifacts WHERE lesson_id=? AND kind=? AND sha256=?",
                (lesson_id, kind, sha256),
            ).fetchone()
        if not row:
            raise RuntimeError("artifact registration failed")
        return dict(row)

    def mark_artifact_status(self, artifact_id: int, status: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE artifacts SET status=? WHERE artifact_id=?",
                (status, artifact_id),
            )
            connection.commit()

    def latest_artifact(self, lesson_id: str, kind: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM artifacts WHERE lesson_id=? AND kind=? ORDER BY artifact_id DESC LIMIT 1",
                (lesson_id, kind),
            ).fetchone()
        return dict(row) if row else None

    def replace_source_refs(self, lesson_id: str, refs: list[str], source_hash: str | None) -> None:
        if not source_hash:
            raise ValueError("source hash is required for source references")
        with self.connect() as connection:
            connection.execute("DELETE FROM source_refs WHERE lesson_id=?", (lesson_id,))
            for locator in refs:
                connection.execute(
                    """
                    INSERT INTO source_refs(lesson_id, source_kind, locator, source_hash, evidence_level, created_at)
                    VALUES(?,?,?,?,?,?)
                    """,
                    (lesson_id, "course", locator[:500], source_hash, "source-linked", utc_now()),
                )
            connection.commit()

    def add_approval(
        self,
        lesson_id: str,
        artifact_sha256: str,
        source_hash: str,
        reviewer_note: str,
    ) -> dict[str, Any]:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE approvals SET revoked_at=? WHERE lesson_id=? AND revoked_at IS NULL",
                (utc_now(), lesson_id),
            )
            cursor = connection.execute(
                """
                INSERT INTO approvals(lesson_id, artifact_sha256, source_hash, reviewer_note, approved_at)
                VALUES(?,?,?,?,?)
                """,
                (lesson_id, artifact_sha256, source_hash, reviewer_note[:500], utc_now()),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM approvals WHERE approval_id=?", (cursor.lastrowid,)
            ).fetchone()
        if not row:
            raise RuntimeError("approval registration failed")
        return dict(row)

    def active_approval(self, lesson_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM approvals
                WHERE lesson_id=? AND revoked_at IS NULL
                ORDER BY approval_id DESC LIMIT 1
                """,
                (lesson_id,),
            ).fetchone()
        return dict(row) if row else None

    def revoke_approval(self, lesson_id: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE approvals SET revoked_at=? WHERE lesson_id=? AND revoked_at IS NULL",
                (utc_now(), lesson_id),
            )
            connection.commit()

    def record_source_read(self, packet: dict[str, Any], source_hash: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO source_reads(
                    lesson_id, source_hash, language, track_sha256, cursor,
                    next_cursor, characters, packet_sha256, created_at
                ) VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    packet["lesson_id"], source_hash, packet["language"],
                    packet["track_sha256"],
                    packet.get("cursor") or "0:0", packet.get("next_cursor"),
                    int(packet["characters"]), packet["packet_sha256"], utc_now(),
                ),
            )
            connection.commit()

    def has_complete_source_read(
        self,
        lesson_id: str,
        source_hash: str,
        language: str,
        track_sha256: str,
    ) -> bool:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT cursor, next_cursor FROM source_reads
                WHERE lesson_id=? AND source_hash=? AND language=? AND track_sha256=?
                ORDER BY source_read_id
                """,
                (lesson_id, source_hash, language, track_sha256),
            ).fetchall()
        edges: dict[str, set[str | None]] = {}
        for row in rows:
            edges.setdefault(str(row["cursor"]), set()).add(
                str(row["next_cursor"]) if row["next_cursor"] is not None else None
            )
        frontier: list[str] = ["0:0"]
        visited: set[str] = set()
        while frontier:
            current = frontier.pop()
            if current in visited:
                continue
            visited.add(current)
            for next_cursor in edges.get(current, set()):
                if next_cursor is None:
                    return True
                if next_cursor not in visited:
                    frontier.append(next_cursor)
        return False

    def source_refs(self, lesson_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM source_refs WHERE lesson_id=? ORDER BY source_ref_id", (lesson_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def get_lesson(self, lesson_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM lessons WHERE lesson_id=?", (lesson_id,)
            ).fetchone()
        if not row:
            raise ValueError("unknown lesson_id")
        return dict(row)

    def list_lessons(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        with self.connect() as connection:
            if status:
                rows = connection.execute(
                    "SELECT * FROM lessons WHERE status=? ORDER BY lesson_id LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM lessons ORDER BY lesson_id LIMIT ?", (limit,)
                ).fetchall()
        return [dict(row) for row in rows]

    def status_counts(self) -> dict[str, int]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM lessons GROUP BY status ORDER BY status"
            ).fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}

    def recent_events(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM workflow_events ORDER BY event_id DESC LIMIT ?",
                (max(1, min(int(limit), 200)),),
            ).fetchall()
        return [dict(row) for row in rows]
