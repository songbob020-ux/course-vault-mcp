#!/usr/bin/env python3
"""Fail closed when a GitHub package appears to contain private course material."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys


DENIED_SUFFIXES = {
    ".vtt", ".srt", ".ass", ".mp4", ".mkv", ".mov", ".webm",
    ".m3u8", ".ts", ".jpg", ".jpeg", ".png", ".webp", ".gif",
    ".sqlite", ".sqlite3", ".db",
}
DENIED_PATH_PARTS = {
    ".venv", "__pycache__", ".course-vault", "private-workspace",
    "browser-profile", "vault-backups",
}
DENIED_BASENAMES = {
    "auth.json", "cookies.json", "cookies.txt", "storage-state.json",
    "storage_state.json", "course-vault.toml", ".env",
}
ALLOWED_SUFFIXES = {".py", ".md", ".toml", ".yml", ".yaml", ".txt", ".json"}
ALLOWED_BASENAMES = {"LICENSE", ".gitignore"}
SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github_token": re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "openai_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "authorization_value": re.compile(r"(?im)^\s*Authorization\s*:\s*(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{12,}\s*$"),
    "cookie_value": re.compile(r"(?im)^\s*Cookie\s*:\s*[^\n]{12,}$"),
    "personal_mac_path": re.compile(r"/Users/[A-Za-z0-9._-]+/"),
    "json_or_assignment_secret": re.compile(
        r"(?i)[\"']?(?:password|passwd|cookie|authorization|access_token|refresh_token|client_secret|api_key)[\"']?"
        r"\s*[:=]\s*[\"'][^\"'\n]{4,}[\"']"
    ),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    "signed_url": re.compile(
        r"(?i)[?&](?:signature|sig|token|key-pair-id|policy|x-amz-signature)=[A-Za-z0-9%._~+/-]{16,}"
    ),
}
TIMESTAMP_ARROW = re.compile(
    r"(?m)^\s*(?:\d{2}:)?\d{2}:\d{2}[.,]\d{3}\s+-->\s+(?:\d{2}:)?\d{2}:\d{2}[.,]\d{3}"
)


def tracked_files(root: Path) -> list[Path]:
    try:
        output = subprocess.check_output(
            ["git", "ls-files", "-z"], cwd=root, stderr=subprocess.DEVNULL
        )
    except (OSError, subprocess.CalledProcessError):
        return [path for path in root.rglob("*") if path.is_file() and ".git" not in path.parts]
    return [root / value.decode("utf-8") for value in output.split(b"\0") if value]


def export_entries(root: Path) -> list[tuple[Path, bytes]]:
    """Read exactly the Git index that would be committed, not the working tree."""
    try:
        subprocess.check_output(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=root,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return [
            (path.relative_to(root), path.read_bytes())
            for path in root.rglob("*")
            if path.is_file() and ".git" not in path.parts
        ]
    try:
        output = subprocess.check_output(
            ["git", "ls-files", "-z"], cwd=root, stderr=subprocess.DEVNULL
        )
        names = [value.decode("utf-8") for value in output.split(b"\0") if value]
        entries: list[tuple[Path, bytes]] = []
        for name in names:
            data = subprocess.check_output(
                ["git", "show", f":{name}"], cwd=root, stderr=subprocess.DEVNULL
            )
            entries.append((Path(name), data))
        return entries
    except (OSError, subprocess.CalledProcessError):
        return [(Path(".git-index-read-error"), b"\xff")]


def _audit_entries(entries: list[tuple[Path, bytes]], prefix: str = "") -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for relative, data in entries:
        display = f"{prefix}{relative}"
        if relative.name.lower() in DENIED_BASENAMES:
            findings.append({"path": display, "reason": "private/runtime filename"})
            continue
        if relative.suffix.lower() in DENIED_SUFFIXES:
            findings.append({"path": display, "reason": "denied file type"})
            continue
        if relative.suffix.lower() not in ALLOWED_SUFFIXES and relative.name not in ALLOWED_BASENAMES:
            findings.append({"path": display, "reason": "file type is not on the public package allowlist"})
            continue
        if any(part in DENIED_PATH_PARTS for part in relative.parts):
            findings.append({"path": display, "reason": "private/runtime path"})
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            findings.append({"path": display, "reason": "unreviewed binary file"})
            continue
        if text.lstrip("\ufeff").startswith("WEBVTT") or len(TIMESTAMP_ARROW.findall(text)) >= 5:
            findings.append({"path": display, "reason": "transcript-like content"})
        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                findings.append({"path": display, "reason": name})
    return findings


def audit(root: Path) -> list[dict[str, str]]:
    entries = export_entries(root)
    findings = _audit_entries(entries)
    if (root / ".git").is_dir() and not entries:
        findings.append({"path": ".git/index", "reason": "Git index contains no files"})
    return findings


def audit_history(root: Path) -> list[dict[str, str]]:
    """Scan every named blob in local Git history before the first public push."""
    try:
        output = subprocess.check_output(
            ["git", "rev-list", "--objects", "--all"], cwd=root, stderr=subprocess.DEVNULL, text=True
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    entries: list[tuple[Path, bytes]] = []
    for line in output.splitlines():
        object_id, separator, name = line.partition(" ")
        if not separator or not name:
            continue
        try:
            kind = subprocess.check_output(
                ["git", "cat-file", "-t", object_id], cwd=root, stderr=subprocess.DEVNULL, text=True
            ).strip()
            if kind != "blob":
                continue
            size = int(
                subprocess.check_output(
                    ["git", "cat-file", "-s", object_id],
                    cwd=root,
                    stderr=subprocess.DEVNULL,
                    text=True,
                ).strip()
            )
            if size > 5 * 1024 * 1024:
                entries.append((Path(name), b"\xff"))
                continue
            data = subprocess.check_output(
                ["git", "cat-file", "-p", object_id], cwd=root, stderr=subprocess.DEVNULL
            )
        except subprocess.CalledProcessError:
            continue
        entries.append((Path(name), data))
    return _audit_entries(entries, prefix="history:")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    entries = export_entries(root)
    findings = audit(root) + audit_history(root)
    print(json.dumps({"ok": not findings, "files_checked": len(entries), "findings": findings}, indent=2))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
