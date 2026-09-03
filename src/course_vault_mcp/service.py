from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import os
from pathlib import Path
import re
import stat
import threading
from typing import Any

from .adapters import LegacyCollectorAdapter
from .config import AppConfig
from .database import WorkflowDB
from .security import validate_lesson_id, validate_note_content, validate_source_refs
from .templates import render_lesson_card
from .vault import VaultWriter, atomic_create


class CourseVaultService:
    def __init__(self, config: AppConfig):
        self.config = config
        self.config.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.config.state_dir.chmod(0o700)
        except OSError:
            pass
        if not self.config.vault.root.is_dir():
            raise ValueError("configured Obsidian Vault root does not exist or is not a directory")
        self.db = WorkflowDB(self.config.state_dir / "workflow.sqlite3", config.project_id)
        if config.collector.kind != "legacy_manifest":
            raise ValueError(f"unsupported collector adapter: {config.collector.kind}")
        self.adapter = LegacyCollectorAdapter(config.collector)
        self.vault = VaultWriter(
            config.vault.root,
            config.state_dir / "vault-backups",
            config.policy.max_note_bytes,
        )
        self._mutation_lock = threading.RLock()
        self._process_lock_path = self.config.state_dir / ".workflow.lock"

    @contextmanager
    def _exclusive(self):
        """Serialize state and Vault mutations across MCP and local CLI processes."""
        with self._mutation_lock:
            descriptor = os.open(
                self._process_lock_path,
                os.O_CREAT | os.O_RDWR,
                0o600,
            )
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                yield
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)

    @staticmethod
    def _bounded_strings(
        values: list[str],
        name: str,
        *,
        max_items: int = 100,
        max_chars: int = 1000,
    ) -> list[str]:
        if len(values) > max_items:
            raise ValueError(f"{name} exceeds the {max_items}-item limit")
        cleaned: list[str] = []
        for value in values:
            item = str(value).strip()
            if len(item) > max_chars:
                raise ValueError(f"{name} contains an overlong item")
            if item:
                cleaned.append(item)
        return cleaned

    @staticmethod
    def _local_reason(value: str, field: str) -> str:
        reason = value.strip()
        if not reason:
            raise ValueError(f"{field} is required")
        if len(reason) > 500 or any(char in reason for char in "\x00"):
            raise ValueError(f"{field} must be at most 500 characters")
        validate_note_content(reason, 2048)
        return reason

    def refresh(self) -> dict[str, Any]:
        with self._exclusive():
            lessons = self.adapter.list_lessons()
            for item in lessons:
                self.db.upsert_lesson(
                    {
                        "lesson_id": item.lesson_id,
                        "title": item.title,
                        "source_url": item.source_url,
                        "status": item.status,
                        "source_hash": item.source_hash,
                        "legacy_source_hash": item.legacy_source_hash,
                        "captured_at": item.captured_at,
                        "reviewed_at": item.reviewed_at,
                        "card_path": item.card_path,
                        "last_error": item.last_error,
                    }
                )
        return {
            "project_id": self.config.project_id,
            "imported": len(lessons),
            "workflow_counts": self.db.status_counts(),
            "collector": self.adapter.status(),
        }

    def status(self) -> dict[str, Any]:
        return {
            "project_id": self.config.project_id,
            "title": self.config.title,
            "workflow_counts": self.db.status_counts(),
            "collector": self.adapter.status(),
            "vault": {
                "configured": True,
                "exists": self.config.vault.root.is_dir(),
                "lesson_subdir": self.config.vault.lesson_subdir,
            },
            "policy": {
                "bounded_source_segments": self.config.policy.allow_bounded_source_segments,
                "human_review_required": self.config.policy.require_human_review,
                "raw_credentials_accepted": False,
                "cache_purge_exposed_by_mcp": False,
            },
        }

    def list_lessons(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return [self._public_lesson(item) for item in self.db.list_lessons(status=status, limit=limit)]

    def recent_events(self, limit: int = 50) -> list[dict[str, Any]]:
        events = self.db.recent_events(limit=limit)
        return [
            {
                "event_id": item["event_id"],
                "lesson_id": item["lesson_id"],
                "from_state": item["from_state"],
                "to_state": item["to_state"],
                "actor": item["actor"],
                "created_at": item["created_at"],
            }
            for item in events
        ]

    @staticmethod
    def _public_lesson(item: dict[str, Any]) -> dict[str, Any]:
        value = dict(item)
        value["legacy_card_available"] = bool(value.pop("card_path", None))
        value["collector_reviewed_at"] = value.pop("reviewed_at", None)
        value.pop("last_error_json", None)
        return value

    def next_action(self) -> dict[str, Any]:
        priority = [
            ("auth_required", "User must sign in to the course website in Chrome; never send credentials to MCP."),
            ("needs_attention", "Inspect the bounded collector error and retry explicitly."),
            ("failed", "Inspect failure; do not loop indefinitely."),
            ("captured", "Create a source-linked draft, or import a compatible legacy card into staging."),
            ("drafted", "Human reviews the draft against source references."),
            ("reviewed", "Run deterministic note and evidence validation."),
            ("validated", "Preview and then explicitly publish to the configured Obsidian subdirectory."),
        ]
        for status, action in priority:
            items = self.db.list_lessons(status=status, limit=500)
            if items:
                if status in {"captured", "reviewed"}:
                    incompatible_legacy: dict[str, Any] | None = None
                    for item in items:
                        artifact = self.db.latest_artifact(str(item["lesson_id"]), "lesson_draft")
                        if not artifact:
                            if status == "reviewed":
                                return {
                                    "lesson": self._public_lesson(item),
                                    "recommended_action": "Review state has no bound artifact; request revision or create a new draft.",
                                }
                            if item.get("card_path"):
                                try:
                                    self.preview_legacy_card_import(str(item["lesson_id"]))
                                except ValueError:
                                    if incompatible_legacy is None:
                                        incompatible_legacy = item
                                    continue
                                return {
                                    "lesson": self._public_lesson(item),
                                    "recommended_action": "Preview and import the legacy card into staging; local approval is still required.",
                                }
                    if status == "captured":
                        if incompatible_legacy is not None:
                            return {
                                "lesson": self._public_lesson(incompatible_legacy),
                                "recommended_action": (
                                    "Legacy card is not automatically importable; add compatible "
                                    "timestamped source references or create a new source-linked draft."
                                ),
                            }
                        return {"lesson": self._public_lesson(items[0]), "recommended_action": action}
                return {"lesson": self._public_lesson(items[0]), "recommended_action": action}
        return {"lesson": None, "recommended_action": "No actionable lesson; refresh collector state."}

    def review_packet(
        self,
        lesson_id: str,
        max_chars: int | None = None,
        cursor: str | None = None,
        language: str | None = None,
    ) -> dict[str, Any]:
        with self._exclusive():
            if not self.config.policy.allow_bounded_source_segments:
                raise ValueError("bounded source-segment exposure is disabled by policy")
            lesson_id = validate_lesson_id(lesson_id)
            lesson = self.db.get_lesson(lesson_id)
            if lesson["status"] not in {"captured", "drafted", "reviewed", "validated", "synced"}:
                raise ValueError("lesson has not reached captured state")
            packet = self.adapter.review_packet(
                lesson_id,
                max_chars=max_chars,
                cursor=cursor,
                language=language,
            )
            source_hash = str(lesson.get("source_hash") or "")
            if not source_hash:
                raise ValueError("lesson has no source hash; refresh or recapture before review")
            if packet.get("source_hash") != source_hash:
                raise ValueError("collector source hash changed; refresh before reading source segments")
            self.db.record_source_read(packet, source_hash)
            return packet

    def _draft_path(self, lesson_id: str, digest: str) -> Path:
        return self.config.state_dir / "drafts" / lesson_id / f"{digest}.md"

    def _write_content_addressed_draft(self, lesson_id: str, content: str) -> tuple[Path, str]:
        validate_note_content(content, self.config.policy.max_note_bytes)
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        draft_path = self._draft_path(lesson_id, digest)
        if draft_path.exists():
            if draft_path.is_symlink() or draft_path.read_text(encoding="utf-8") != content:
                raise ValueError("content-addressed draft path has conflicting content")
        else:
            atomic_create(draft_path, content)
        try:
            draft_path.chmod(0o600)
        except OSError:
            pass
        return draft_path, digest

    def _verified_draft(
        self,
        lesson: dict[str, Any],
        *,
        required_artifact_status: str | None = None,
        require_approval: bool = False,
    ) -> tuple[dict[str, Any], Path, str]:
        lesson_id = str(lesson["lesson_id"])
        artifact = self.db.latest_artifact(lesson_id, "lesson_draft")
        if not artifact:
            raise ValueError("lesson draft artifact is missing")
        path = Path(str(artifact["path"]))
        if path.is_symlink():
            raise ValueError("draft path must not be a symbolic link")
        path = path.resolve()
        expected_root = (self.config.state_dir / "drafts").resolve()
        if expected_root not in path.parents or not path.is_file():
            raise ValueError("draft path is missing or outside the staging directory")
        content = path.read_text(encoding="utf-8")
        validate_note_content(content, self.config.policy.max_note_bytes)
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if digest != artifact["sha256"]:
            raise ValueError("draft changed after registration; save or import a new draft")
        if required_artifact_status and artifact["status"] != required_artifact_status:
            raise ValueError(f"draft artifact is not {required_artifact_status}")
        if require_approval:
            approval = self.db.active_approval(lesson_id)
            if not approval:
                raise ValueError("a local hash-bound human approval is required")
            if approval["artifact_sha256"] != digest or approval["source_hash"] != lesson.get("source_hash"):
                raise ValueError("approval does not match the current draft and source hashes")
        return artifact, path, content

    def save_draft(
        self,
        lesson_id: str,
        summary: str,
        key_concepts: list[str],
        decision_rules: list[str],
        counterexamples: list[str],
        open_questions: list[str],
        source_refs: list[str],
        tags: list[str],
        source_language: str = "en",
        transcript_coverage_complete: bool = False,
        visual_evidence: str = "missing",
    ) -> dict[str, Any]:
        with self._exclusive():
            lesson_id = validate_lesson_id(lesson_id)
            lesson = self.db.get_lesson(lesson_id)
            if lesson["status"] not in {"captured", "drafted"}:
                raise ValueError("drafting requires captured or drafted state")
            summary = summary.strip()
            if not summary:
                raise ValueError("summary is required")
            if len(summary) > 20000:
                raise ValueError("summary exceeds the 20000-character limit")
            key_concepts = self._bounded_strings(key_concepts, "key_concepts")
            decision_rules = self._bounded_strings(decision_rules, "decision_rules")
            counterexamples = self._bounded_strings(counterexamples, "counterexamples")
            open_questions = self._bounded_strings(open_questions, "open_questions")
            tags = self._bounded_strings(tags, "tags", max_items=50, max_chars=100)
            source_refs = self._bounded_strings(
                source_refs, "source_refs", max_items=200, max_chars=200
            )
            source_refs = validate_source_refs(lesson_id, source_refs)
            if not lesson.get("source_hash"):
                raise ValueError("lesson has no source hash; refresh or recapture before drafting")
            source_language = source_language.strip()
            if not source_language or len(source_language) > 32:
                raise ValueError("source_language must be 1 to 32 characters")
            if visual_evidence not in {"missing", "reviewed", "not_applicable"}:
                raise ValueError("visual_evidence must be missing, reviewed, or not_applicable")
            if transcript_coverage_complete:
                track_sha256, current_source_hash = self.adapter.source_track_hash(
                    lesson_id, source_language
                )
                if current_source_hash != str(lesson["source_hash"]):
                    raise ValueError("collector source hash changed; refresh before drafting")
                if not self.db.has_complete_source_read(
                    lesson_id,
                    str(lesson["source_hash"]),
                    source_language,
                    track_sha256,
                ):
                    raise ValueError(
                        "complete transcript coverage has not been recorded for this source and language"
                    )
            content = render_lesson_card(
                project_id=self.config.project_id,
                lesson_id=lesson_id,
                title=str(lesson["title"]),
                source_url=str(lesson["source_url"]),
                summary=summary,
                key_concepts=key_concepts,
                decision_rules=decision_rules,
                counterexamples=counterexamples,
                open_questions=open_questions,
                source_refs=source_refs,
                tags=tags,
                source_hash=lesson.get("source_hash"),
                source_language=source_language,
                transcript_coverage_complete=transcript_coverage_complete,
                visual_evidence=visual_evidence,
            )
            draft_path, digest = self._write_content_addressed_draft(lesson_id, content)
            self.db.revoke_approval(lesson_id)
            self.db.add_artifact(lesson_id, "lesson_draft", str(draft_path), digest, "draft")
            self.db.replace_source_refs(lesson_id, source_refs, lesson.get("source_hash"))
            if lesson["status"] == "captured":
                self.db.transition(lesson_id, "drafted", "mcp-host", "source-linked draft saved")
        return {
            "lesson_id": lesson_id,
            "status": "drafted",
            "staging_key": f"{lesson_id}/{draft_path.name}",
            "sha256": digest,
        }

    _LEGACY_RANGE_RE = re.compile(
        r"(?<!\d)((?:\d{1,2}:)?\d{2}:\d{2}(?:[.,]\d{1,3})?)\s*[–—-]\s*"
        r"((?:\d{1,2}:)?\d{2}:\d{2}(?:[.,]\d{1,3})?)(?!\d)"
    )

    def _legacy_card(self, lesson_id: str) -> tuple[dict[str, Any], Path, str, list[str]]:
        lesson_id = validate_lesson_id(lesson_id)
        lesson = self.db.get_lesson(lesson_id)
        root = (self.config.collector.project_root / "lessons").resolve()
        supplied_path = Path(str(lesson.get("card_path") or root / f"{lesson_id}.md"))
        if ".." in supplied_path.parts:
            raise ValueError("legacy card path traversal is not allowed")
        raw_path = supplied_path
        if not raw_path.is_absolute():
            raw_path = root / raw_path
        # macOS exposes canonical /private/var paths through the /var alias.
        # Accept an alias for the configured root while rejecting symlinks in
        # every untrusted path component below it.
        try:
            lexical_root = next(
                (
                    candidate
                    for candidate in (raw_path, *raw_path.parents)
                    if candidate.resolve() == root
                ),
                None,
            )
        except (OSError, RuntimeError) as exc:
            raise ValueError("legacy card is outside project_root/lessons") from exc
        if lexical_root is None:
            raise ValueError("legacy card is outside project_root/lessons")
        lexical_relative = raw_path.relative_to(lexical_root)
        current = lexical_root
        for part in lexical_relative.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("legacy card must not use symbolic links")
        try:
            path = raw_path.resolve()
            path.relative_to(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ValueError("legacy card is outside project_root/lessons") from exc
        if root not in path.parents or not path.is_file():
            raise ValueError("legacy card is missing or outside project_root/lessons")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise ValueError("legacy card is missing or unsafe") from exc
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("legacy card is not a regular file")
            if metadata.st_size > self.config.policy.max_note_bytes:
                raise ValueError("legacy card exceeds configured maximum note size")
            with os.fdopen(descriptor, "rb", closefd=False) as handle:
                raw_content = handle.read(self.config.policy.max_note_bytes + 1)
        finally:
            os.close(descriptor)
        if len(raw_content) > self.config.policy.max_note_bytes:
            raise ValueError("legacy card exceeds configured maximum note size")
        try:
            content = raw_content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("legacy card must be UTF-8 Markdown") from exc
        validate_note_content(content, self.config.policy.max_note_bytes)
        refs: list[str] = []
        for start, end in self._LEGACY_RANGE_RE.findall(content):
            candidate = f"{lesson_id} {start}–{end}"
            try:
                refs.extend(validate_source_refs(lesson_id, [candidate]))
            except ValueError:
                # Broad duration summaries are metadata, not precise evidence
                # locators. Keep only independently valid, bounded ranges.
                continue
        refs = self._bounded_strings(
            list(dict.fromkeys(refs)), "legacy source references", max_items=200, max_chars=200
        )
        refs = validate_source_refs(lesson_id, refs)
        return lesson, path, content, refs

    def preview_legacy_card_import(self, lesson_id: str) -> dict[str, Any]:
        lesson, _path, content, refs = self._legacy_card(lesson_id)
        if lesson["status"] not in {"captured", "drafted"}:
            raise ValueError("legacy import requires captured or drafted state")
        return {
            "lesson_id": lesson_id,
            "source_kind": "legacy_reviewed_card",
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "bytes": len(content.encode("utf-8")),
            "source_ref_count": len(refs),
            "source_refs": refs,
            "will_require_local_approval": True,
        }

    def audit_legacy_cards(self, limit: int = 500) -> dict[str, Any]:
        """Read-only compatibility audit; never returns card bodies or local paths."""
        candidates = self.db.list_lessons(limit=limit)
        eligible: list[str] = []
        errors: list[dict[str, str]] = []
        skipped = 0
        for item in candidates:
            if not item.get("card_path"):
                skipped += 1
                continue
            lesson_id = str(item["lesson_id"])
            try:
                self.preview_legacy_card_import(lesson_id)
                eligible.append(lesson_id)
            except ValueError as exc:
                errors.append({"lesson_id": lesson_id, "error": str(exc)})
        return {
            "checked": len(candidates),
            "eligible": len(eligible),
            "ineligible": len(errors),
            "without_card": skipped,
            "eligible_sample": eligible[:20],
            "errors": errors[:20],
            "truncated_errors": max(0, len(errors) - 20),
        }

    def import_legacy_card(self, lesson_id: str) -> dict[str, Any]:
        with self._exclusive():
            lesson, _path, content, refs = self._legacy_card(lesson_id)
            if lesson["status"] not in {"captured", "drafted"}:
                raise ValueError("legacy import requires captured or drafted state")
            if not lesson.get("source_hash"):
                raise ValueError("legacy card cannot be bound because source hash is missing")
            draft_path, digest = self._write_content_addressed_draft(lesson_id, content)
            self.db.revoke_approval(lesson_id)
            self.db.add_artifact(lesson_id, "lesson_draft", str(draft_path), digest, "draft")
            self.db.replace_source_refs(lesson_id, refs, str(lesson["source_hash"]))
            if lesson["status"] == "captured":
                self.db.transition(
                    lesson_id,
                    "drafted",
                    "legacy-migration",
                    "legacy card copied into content-addressed staging; local approval required",
                )
            return {
                "lesson_id": lesson_id,
                "status": "drafted",
                "sha256": digest,
                "source_ref_count": len(refs),
                "requires_local_approval": True,
            }

    def approve_draft(self, lesson_id: str, reviewer_note: str) -> dict[str, Any]:
        lesson_id = validate_lesson_id(lesson_id)
        reviewer_note = self._local_reason(reviewer_note, "reviewer_note")
        with self._exclusive():
            lesson = self.db.get_lesson(lesson_id)
            if lesson["status"] != "drafted":
                raise ValueError("local approval requires drafted state")
            artifact, _path, _content = self._verified_draft(lesson)
            source_hash = str(lesson.get("source_hash") or "")
            if not source_hash:
                raise ValueError("source hash is missing")
            refs = self.db.source_refs(lesson_id)
            if not refs or any(ref.get("source_hash") != source_hash for ref in refs):
                raise ValueError("source references are missing or stale")
            self.db.add_approval(
                lesson_id,
                str(artifact["sha256"]),
                source_hash,
                reviewer_note,
            )
            self.db.mark_artifact_status(int(artifact["artifact_id"]), "reviewed")
            return self.db.transition(
                lesson_id,
                "reviewed",
                "local-human-review",
                "local source review approved",
            )

    def acknowledge_source_change(self, lesson_id: str, note: str) -> dict[str, Any]:
        """Local-only acknowledgement after recapture/inspection of changed source."""
        lesson_id = validate_lesson_id(lesson_id)
        note = self._local_reason(note, "acknowledgement note")
        with self._exclusive():
            lesson = self.db.get_lesson(lesson_id)
            if lesson["status"] != "needs_attention":
                raise ValueError("source-change acknowledgement requires needs_attention state")
            return self.db.transition(
                lesson_id,
                "captured",
                "local-source-review",
                note,
            )

    def request_revision(self, lesson_id: str, reason: str) -> dict[str, Any]:
        """Move a reviewed/validated/synced lesson back to draft under local control."""
        lesson_id = validate_lesson_id(lesson_id)
        reason = self._local_reason(reason, "revision reason")
        with self._exclusive():
            lesson = self.db.get_lesson(lesson_id)
            status = str(lesson["status"])
            if status not in {"reviewed", "validated", "synced"}:
                raise ValueError("revision requires reviewed, validated, or synced state")
            artifact = self.db.latest_artifact(lesson_id, "lesson_draft")
            if not artifact:
                raise ValueError("lesson draft artifact is missing")
            if status == "synced":
                self.db.transition(lesson_id, "validated", "local-revision", reason)
                status = "validated"
            if status == "validated":
                self.db.transition(lesson_id, "reviewed", "local-revision", reason)
            self.db.revoke_approval(lesson_id)
            self.db.mark_artifact_status(int(artifact["artifact_id"]), "draft")
            return self.db.transition(lesson_id, "drafted", "local-revision", reason)

    def validate_draft(self, lesson_id: str) -> dict[str, Any]:
        with self._exclusive():
            lesson_id = validate_lesson_id(lesson_id)
            lesson = self.db.get_lesson(lesson_id)
            if lesson["status"] != "reviewed":
                raise ValueError("deterministic validation requires reviewed state")
            artifact, _path, content = self._verified_draft(
                lesson,
                required_artifact_status="reviewed",
                require_approval=True,
            )
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            refs = self.db.source_refs(lesson_id)
            current_hash = lesson.get("source_hash")
            locators = [str(ref.get("locator") or "") for ref in refs]
            validate_source_refs(lesson_id, locators)
            if not current_hash or any(ref.get("source_hash") != current_hash for ref in refs):
                raise ValueError("source references do not match the current source hash")
            self.db.mark_artifact_status(int(artifact["artifact_id"]), "validated")
            transitioned = self.db.transition(
                lesson_id,
                "validated",
                "validator",
                "privacy, source hash, draft hash, path, and reference syntax checks passed",
            )
        return {
            "lesson": self._public_lesson(transitioned),
            "draft_sha256": digest,
            "source_ref_count": len(refs),
            "checks": ["privacy", "size", "staging_path", "sha256", "source_refs"],
        }

    def preview_sync(self, lesson_id: str, include_local_path: bool = False) -> dict[str, Any]:
        with self._exclusive():
            lesson_id = validate_lesson_id(lesson_id)
            lesson = self.db.get_lesson(lesson_id)
            if lesson["status"] != "validated":
                raise ValueError("Obsidian preview requires validated state")
            _artifact, _path, content = self._verified_draft(
                lesson,
                required_artifact_status="validated",
                require_approval=True,
            )
            relative_path = f"{self.config.vault.lesson_subdir}/{lesson_id}.md"
            preview = self.vault.preview(relative_path, content)
            preview["relative_path"] = relative_path
            if not include_local_path:
                preview.pop("target", None)
            return preview

    def sync(self, lesson_id: str) -> dict[str, Any]:
        lesson_id = validate_lesson_id(lesson_id)
        with self._exclusive():
            lesson = self.db.get_lesson(lesson_id)
            if lesson["status"] != "validated":
                raise ValueError("Obsidian publish requires validated state")
            artifact, _path, content = self._verified_draft(
                lesson,
                required_artifact_status="validated",
                require_approval=True,
            )
            relative_path = f"{self.config.vault.lesson_subdir}/{lesson_id}.md"
            preview = self.vault.preview(relative_path, content)
            receipt = self.vault.write(relative_path, content)
            # Re-check the exact approved artifact after the Vault write.  Any
            # concurrent staging mutation prevents a false synced receipt.
            current = self.db.latest_artifact(lesson_id, "lesson_draft")
            if not current or current["artifact_id"] != artifact["artifact_id"]:
                raise ValueError("draft artifact changed during publication")
            self._verified_draft(
                lesson,
                required_artifact_status="validated",
                require_approval=True,
            )
            self.db.add_artifact(
                lesson_id,
                "vault_note",
                str(receipt["target"]),
                str(receipt["after_sha256"]),
                "synced",
            )
            self.db.transition(lesson_id, "synced", "local-obsidian-publisher", "atomic write and hash verification passed")
            return {"lesson_id": lesson_id, "preview": preview, "receipt": receipt, "status": "synced"}
