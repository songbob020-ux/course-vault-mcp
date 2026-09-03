from __future__ import annotations

from dataclasses import dataclass
from typing import Any


WORKFLOW_STATES = {
    "discovered",
    "auth_required",
    "captured",
    "drafted",
    "reviewed",
    "validated",
    "synced",
    "purged",
    "failed",
    "needs_attention",
}


STATE_ORDER = {
    "discovered": 0,
    "auth_required": 0,
    "failed": 0,
    "needs_attention": 0,
    "captured": 1,
    "drafted": 2,
    "reviewed": 3,
    "validated": 4,
    "synced": 5,
    "purged": 6,
}


ALLOWED_TRANSITIONS = {
    "discovered": {"auth_required", "captured", "failed", "needs_attention"},
    "auth_required": {"discovered", "captured", "failed", "needs_attention"},
    "failed": {"discovered", "captured", "needs_attention"},
    "needs_attention": {"discovered", "captured", "failed"},
    "captured": {"drafted", "failed", "needs_attention"},
    "drafted": {"reviewed", "captured"},
    "reviewed": {"validated", "drafted"},
    "validated": {"synced", "reviewed"},
    "synced": {"purged", "validated"},
    "purged": {"captured"},
}


@dataclass(frozen=True)
class LessonSource:
    lesson_id: str
    title: str
    source_url: str
    status: str
    source_hash: str | None = None
    legacy_source_hash: str | None = None
    captured_at: str | None = None
    reviewed_at: str | None = None
    card_path: str | None = None
    last_error: dict[str, Any] | None = None
