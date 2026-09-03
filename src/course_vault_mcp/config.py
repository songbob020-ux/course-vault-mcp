from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import tomllib
from urllib.parse import urlparse


@dataclass(frozen=True)
class CollectorConfig:
    kind: str
    project_root: Path
    collector_root: Path
    cache_root: Path
    base_url: str
    allowed_source_hosts: tuple[str, ...]
    max_segment_chars: int


@dataclass(frozen=True)
class VaultConfig:
    root: Path
    lesson_subdir: str


@dataclass(frozen=True)
class PolicyConfig:
    allow_bounded_source_segments: bool
    require_human_review: bool
    max_note_bytes: int


@dataclass(frozen=True)
class AppConfig:
    schema_version: int
    project_id: str
    title: str
    state_dir: Path
    collector: CollectorConfig
    vault: VaultConfig
    policy: PolicyConfig
    config_path: Path


def _path(value: str, base: Path) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    return candidate.resolve()


def load_config(path: str | Path | None = None) -> AppConfig:
    raw_path = path or os.environ.get("COURSE_VAULT_CONFIG")
    if not raw_path:
        raise ValueError(
            "Set COURSE_VAULT_CONFIG to an absolute TOML config path, or pass --config."
        )
    config_path = Path(raw_path).expanduser().resolve()
    payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    base = config_path.parent

    schema_version = int(payload.get("schema_version", 0))
    if schema_version != 1:
        raise ValueError("unsupported config schema_version; expected 1")

    project_id = str(payload.get("project_id") or "").strip()
    title = str(payload.get("title") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", project_id) or not title:
        raise ValueError("project_id and title are required")
    if len(title) > 200 or any(char in title for char in "\r\n\x00"):
        raise ValueError("title must be a single line of at most 200 characters")

    collector_raw = payload.get("collector") or {}
    base_url = str(collector_raw.get("base_url") or "http://127.0.0.1:8765").rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("collector.base_url must be a local HTTP URL")
    allowed_hosts = tuple(str(value).strip().lower().rstrip(".") for value in collector_raw.get("allowed_source_hosts", []))
    if not allowed_hosts:
        raise ValueError("collector.allowed_source_hosts must not be empty")
    if any(not host or "*" in host or "/" in host or ":" in host for host in allowed_hosts):
        raise ValueError("collector.allowed_source_hosts must contain exact hostnames")
    max_segment_chars = int(collector_raw.get("max_segment_chars", 6000))
    if not 500 <= max_segment_chars <= 20000:
        raise ValueError("collector.max_segment_chars must be between 500 and 20000")

    collector = CollectorConfig(
        kind=str(collector_raw.get("kind") or "legacy_manifest"),
        project_root=_path(str(collector_raw["project_root"]), base),
        collector_root=_path(str(collector_raw["collector_root"]), base),
        cache_root=_path(str(collector_raw["cache_root"]), base),
        base_url=base_url,
        allowed_source_hosts=allowed_hosts,
        max_segment_chars=max_segment_chars,
    )

    vault_raw = payload.get("vault") or {}
    lesson_subdir = str(vault_raw.get("lesson_subdir") or "Courses").strip("/ ")
    if not lesson_subdir:
        raise ValueError("vault.lesson_subdir must not be empty")
    subdir_parts = PurePosixPath(lesson_subdir.replace("\\", "/")).parts
    if ".." in subdir_parts or any(part.lower() in {".git", ".obsidian", ".trash"} for part in subdir_parts):
        raise ValueError("vault.lesson_subdir targets an unsafe directory")
    vault = VaultConfig(
        root=_path(str(vault_raw["root"]), base),
        lesson_subdir=lesson_subdir,
    )

    policy_raw = payload.get("policy") or {}
    require_human_review = policy_raw.get("require_human_review", True)
    if require_human_review is not True:
        raise ValueError("policy.require_human_review must be true in v0.1")
    policy = PolicyConfig(
        allow_bounded_source_segments=bool(
            policy_raw.get("allow_bounded_source_segments", True)
        ),
        require_human_review=True,
        max_note_bytes=int(policy_raw.get("max_note_bytes", 262144)),
    )
    if not 4096 <= policy.max_note_bytes <= 2 * 1024 * 1024:
        raise ValueError("policy.max_note_bytes must be between 4096 and 2097152")

    state_dir = _path(str(payload.get("state_dir") or ".course-vault"), base)

    def within(candidate: Path, parent: Path) -> bool:
        return candidate == parent or parent in candidate.parents

    if within(state_dir, vault.root) or within(vault.root, state_dir):
        raise ValueError("state_dir and the Obsidian Vault must be topologically separate")
    if within(collector.cache_root, vault.root) or within(collector.collector_root, vault.root):
        raise ValueError("collector and caption cache must not be stored inside the Obsidian Vault")
    if within(state_dir, base):
        raise ValueError("state_dir must be outside the config/repository directory")

    return AppConfig(
        schema_version=schema_version,
        project_id=project_id,
        title=title,
        state_dir=state_dir,
        collector=collector,
        vault=vault,
        policy=policy,
        config_path=config_path,
    )
