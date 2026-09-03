from __future__ import annotations

import multiprocessing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from course_vault_mcp.database import WorkflowDB


def initialize_database_worker(path: str, barrier, results) -> None:
    try:
        barrier.wait(timeout=10)
        WorkflowDB(Path(path), "demo")
    except BaseException as exc:
        results.put(f"{type(exc).__name__}: {exc}")
    else:
        results.put("ok")


class DatabaseTests(unittest.TestCase):
    def test_state_machine_and_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = WorkflowDB(Path(directory) / "workflow.sqlite3", "demo")
            db.upsert_lesson(
                {
                    "lesson_id": "L-001",
                    "title": "Synthetic lesson",
                    "source_url": "https://courses.example.com/l1",
                    "status": "captured",
                }
            )
            db.transition("L-001", "drafted", "test", "draft written")
            with self.assertRaises(ValueError):
                db.transition("L-001", "reviewed", "test", "unbound approval")
            self.assertEqual(db.get_lesson("L-001")["status"], "drafted")
            self.assertGreaterEqual(len(db.recent_events()), 2)

    def test_collector_refresh_does_not_downgrade_knowledge_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = WorkflowDB(Path(directory) / "workflow.sqlite3", "demo")
            lesson = {
                "lesson_id": "L-001",
                "title": "Synthetic lesson",
                "source_url": "https://courses.example.com/l1",
                "status": "captured",
            }
            db.upsert_lesson(lesson)
            db.transition("L-001", "drafted", "test", "draft written")
            db.upsert_lesson(lesson)
            self.assertEqual(db.get_lesson("L-001")["status"], "drafted")

    def test_known_legacy_fingerprint_rekeys_pristine_capture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = WorkflowDB(Path(directory) / "workflow.sqlite3", "demo")
            old_hash = "a" * 64
            new_hash = "b" * 64
            lesson = {
                "lesson_id": "L-001",
                "title": "Synthetic lesson",
                "source_url": "https://courses.example.com/l1",
                "status": "captured",
                "source_hash": old_hash,
            }
            db.upsert_lesson(lesson)
            db.record_source_read(
                {
                    "lesson_id": "L-001",
                    "language": "en",
                    "track_sha256": "c" * 64,
                    "cursor": "0:0",
                    "next_cursor": None,
                    "characters": 100,
                    "packet_sha256": "d" * 64,
                },
                old_hash,
            )

            updated = db.upsert_lesson(
                {
                    **lesson,
                    "source_hash": new_hash,
                    "legacy_source_hash": old_hash,
                }
            )
            self.assertEqual(updated["status"], "captured")
            self.assertEqual(updated["source_hash"], new_hash)
            self.assertTrue(
                db.has_complete_source_read("L-001", old_hash, "en", "c" * 64)
            )
            self.assertFalse(
                db.has_complete_source_read("L-001", new_hash, "en", "c" * 64)
            )
            event = db.recent_events()[0]
            self.assertEqual((event["from_state"], event["to_state"]), ("captured", "captured"))
            self.assertIn("fingerprint algorithm migrated", event["reason"])

    def test_fingerprint_migration_never_bypasses_downstream_evidence(self) -> None:
        for evidence_kind in ("artifact", "source_ref", "approval"):
            with self.subTest(evidence_kind=evidence_kind), tempfile.TemporaryDirectory() as directory:
                db = WorkflowDB(Path(directory) / "workflow.sqlite3", "demo")
                old_hash = "a" * 64
                lesson = {
                    "lesson_id": "L-001",
                    "title": "Synthetic lesson",
                    "source_url": "https://courses.example.com/l1",
                    "status": "captured",
                    "source_hash": old_hash,
                }
                db.upsert_lesson(lesson)
                if evidence_kind == "artifact":
                    db.add_artifact("L-001", "lesson_draft", "draft.md", "c" * 64, "draft")
                elif evidence_kind == "source_ref":
                    db.replace_source_refs("L-001", ["L-001 00:00–00:01"], old_hash)
                else:
                    db.add_approval("L-001", "c" * 64, old_hash, "Reviewed")

                updated = db.upsert_lesson(
                    {
                        **lesson,
                        "source_hash": "b" * 64,
                        "legacy_source_hash": old_hash,
                    }
                )
                self.assertEqual(updated["status"], "needs_attention")

    def test_unrecognized_hash_change_still_requires_attention(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = WorkflowDB(Path(directory) / "workflow.sqlite3", "demo")
            lesson = {
                "lesson_id": "L-001",
                "title": "Synthetic lesson",
                "source_url": "https://courses.example.com/l1",
                "status": "captured",
                "source_hash": "a" * 64,
            }
            db.upsert_lesson(lesson)
            updated = db.upsert_lesson(
                {
                    **lesson,
                    "source_hash": "b" * 64,
                    "legacy_source_hash": "c" * 64,
                }
            )
            self.assertEqual(updated["status"], "needs_attention")

    def test_collector_cannot_set_semantic_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = WorkflowDB(Path(directory) / "workflow.sqlite3", "demo")
            with self.assertRaisesRegex(ValueError, "collector cannot"):
                db.upsert_lesson(
                    {
                        "lesson_id": "L-001",
                        "title": "Synthetic lesson",
                        "source_url": "https://courses.example.com/l1",
                        "status": "reviewed",
                    }
                )

    def test_database_rejects_different_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workflow.sqlite3"
            WorkflowDB(path, "project-a")
            with self.assertRaisesRegex(ValueError, "different project_id"):
                WorkflowDB(path, "project-b")

    def test_v2_database_adds_track_hash_to_source_reads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workflow.sqlite3"
            connection = sqlite3.connect(path)
            connection.executescript(
                """
                CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT INTO metadata(key, value) VALUES('schema_version', '2');
                INSERT INTO metadata(key, value) VALUES('project_id', 'demo');
                CREATE TABLE source_reads (
                    source_read_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lesson_id TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    language TEXT NOT NULL,
                    cursor TEXT NOT NULL,
                    next_cursor TEXT,
                    characters INTEGER NOT NULL,
                    packet_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                INSERT INTO source_reads(
                    lesson_id, source_hash, language, cursor, next_cursor,
                    characters, packet_sha256, created_at
                ) VALUES(
                    'L-001', 'old-source', 'en', '0:0', NULL,
                    10, 'old-packet', '2026-01-01T00:00:00Z'
                );
                """
            )
            connection.commit()
            connection.close()

            WorkflowDB(path, "demo")
            connection = sqlite3.connect(path)
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(source_reads)").fetchall()
            }
            connection.close()
            self.assertIn("track_sha256", columns)
            migrated = WorkflowDB(path, "demo")
            self.assertFalse(
                migrated.has_complete_source_read(
                    "L-001", "old-source", "en", "current-track"
                )
            )

    def test_concurrent_initializers_serialize_schema_migration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workflow.sqlite3"
            connection = sqlite3.connect(path)
            connection.executescript(
                """
                CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT INTO metadata(key, value) VALUES('schema_version', '2');
                INSERT INTO metadata(key, value) VALUES('project_id', 'demo');
                CREATE TABLE source_reads (
                    source_read_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lesson_id TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    language TEXT NOT NULL,
                    cursor TEXT NOT NULL,
                    next_cursor TEXT,
                    characters INTEGER NOT NULL,
                    packet_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            connection.commit()
            connection.close()

            context = multiprocessing.get_context("fork")
            worker_count = 4
            barrier = context.Barrier(worker_count)
            results = context.Queue()
            workers = [
                context.Process(
                    target=initialize_database_worker,
                    args=(str(path), barrier, results),
                )
                for _ in range(worker_count)
            ]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=15)
                self.assertFalse(worker.is_alive(), "database initializer hung")
                self.assertEqual(worker.exitcode, 0)
            outcomes = sorted(results.get(timeout=2) for _ in range(worker_count))
            self.assertEqual(outcomes, ["ok"] * worker_count)

            connection = sqlite3.connect(path)
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(source_reads)").fetchall()
            }
            connection.close()
            self.assertIn("track_sha256", columns)


if __name__ == "__main__":
    unittest.main()
