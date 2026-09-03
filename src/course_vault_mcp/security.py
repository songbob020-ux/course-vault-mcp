from __future__ import annotations

from pathlib import Path, PurePosixPath
import re
from urllib.parse import urlsplit, urlunsplit


LESSON_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
FORBIDDEN_NOTE_PATTERNS = (
    re.compile(r"(?im)^\s*WEBVTT\s*$"),
    re.compile(r'(?i)"?vtt_text"?\s*:'),
    re.compile(r'(?i)"?data_base64"?\s*:'),
    re.compile(r"(?im)^\s*(cookie|authorization|set-cookie)\s*:"),
    re.compile(r"!\[\["),
    re.compile(r"(?i)!\[[^\]]*\]\(\s*https?://"),
    re.compile(r"(?i)<img\b[^>]*\bsrc\s*=\s*[\"']?https?://"),
    re.compile(r"(?i)\b(?:file|obsidian):(?:/{0,2})"),
    re.compile(r"(?i)\b(?:javascript|data):"),
    re.compile(r"(?i)<\s*(?:script|iframe|object|embed|video|audio|form|link|meta)\b"),
)
TIMESTAMP_ARROW_RE = re.compile(
    r"(?m)^\s*(?:\d{2}:)?\d{2}:\d{2}[.,]\d{3}\s+-->\s+(?:\d{2}:)?\d{2}:\d{2}[.,]\d{3}"
)
SOURCE_REF_RE = re.compile(
    r"^(?P<lesson>[A-Za-z0-9][A-Za-z0-9._-]{0,79})\s+"
    r"(?P<start>(?:\d{1,2}:)?\d{2}:\d{2}(?:[.,]\d{1,3})?)\s*[–—-]\s*"
    r"(?P<end>(?:\d{1,2}:)?\d{2}:\d{2}(?:[.,]\d{1,3})?)$"
)


def validate_lesson_id(value: str) -> str:
    lesson_id = value.strip()
    if not LESSON_ID_RE.fullmatch(lesson_id):
        raise ValueError("invalid lesson_id")
    return lesson_id


def sanitize_source_url(value: str, allowed_hosts: tuple[str, ...]) -> str:
    parsed = urlsplit(value)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or hostname not in allowed_hosts:
        raise ValueError("source URL is outside the configured HTTPS host allowlist")
    if parsed.username or parsed.password:
        raise ValueError("source URL must not contain credentials")
    if parsed.port not in {None, 443}:
        raise ValueError("source URL must use the default HTTPS port")
    clean_netloc = hostname
    return urlunsplit(("https", clean_netloc, parsed.path or "/", "", ""))


def safe_markdown_path(root: Path, relative_path: str) -> Path:
    raw = PurePosixPath(relative_path.replace("\\", "/"))
    if raw.is_absolute() or ".." in raw.parts:
        raise ValueError("path traversal is not allowed")
    protected = {".git", ".obsidian", ".trash"}
    if not raw.parts or any(part.lower() in protected for part in raw.parts):
        raise ValueError("path targets a protected directory")
    if raw.suffix.lower() != ".md":
        raise ValueError("only Markdown note paths are allowed")
    resolved_root = root.expanduser().resolve()
    unresolved = resolved_root / Path(*raw.parts)
    # Reject symlinks in every existing component.  Resolving alone is not enough:
    # `Courses/alias -> .obsidian` would otherwise remain inside the Vault while
    # bypassing the protected-directory check above.
    current = resolved_root
    for part in raw.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("symbolic links are not allowed in Vault note paths")
    candidate = unresolved.resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise ValueError("resolved path escapes the configured root")
    resolved_relative = candidate.relative_to(resolved_root)
    if any(part.lower() in protected for part in resolved_relative.parts):
        raise ValueError("resolved path targets a protected directory")
    return candidate


def validate_prompt_topic(value: str) -> str:
    topic = value.strip()
    if not topic or len(topic) > 200 or any(char in topic for char in "\r\n\x00"):
        raise ValueError("topic must be a single line of 1 to 200 characters")
    return topic


def sanitize_title(value: str, fallback: str) -> str:
    title = " ".join(value.replace("\x00", " ").split())[:200]
    return title or fallback


def validate_note_content(content: str, max_bytes: int) -> None:
    encoded = content.encode("utf-8")
    if not content.strip():
        raise ValueError("note content is empty")
    if len(encoded) > max_bytes:
        raise ValueError("note exceeds configured maximum size")
    for pattern in FORBIDDEN_NOTE_PATTERNS:
        if pattern.search(content):
            raise ValueError("note appears to contain raw captions, media bytes, or credentials")
    if len(TIMESTAMP_ARROW_RE.findall(content)) >= 3:
        raise ValueError("note appears to contain a copied subtitle transcript")


def _timestamp_seconds(value: str) -> float:
    normalized = value.replace(",", ".")
    pieces = normalized.split(":")
    if len(pieces) == 2:
        hours = 0
        minutes, seconds = pieces
        if float(seconds) >= 60:
            raise ValueError("invalid source timestamp")
    elif len(pieces) == 3:
        hours, minutes, seconds = pieces
        if int(minutes) >= 60 or float(seconds) >= 60:
            raise ValueError("invalid source timestamp")
    else:
        raise ValueError("invalid source timestamp")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def validate_source_refs(lesson_id: str, refs: list[str]) -> list[str]:
    lesson_id = validate_lesson_id(lesson_id)
    cleaned: list[str] = []
    for raw in refs:
        value = raw.strip()
        match = SOURCE_REF_RE.fullmatch(value)
        if not match or match.group("lesson") != lesson_id:
            raise ValueError(
                "each source reference must be '<lesson_id> <start>–<end>'"
            )
        start = _timestamp_seconds(match.group("start"))
        end = _timestamp_seconds(match.group("end"))
        if start < 0 or end <= start or end - start > 30 * 60:
            raise ValueError("source reference time range is invalid or wider than 30 minutes")
        cleaned.append(value)
    if not cleaned:
        raise ValueError("at least one timestamped source reference is required")
    return list(dict.fromkeys(cleaned))
