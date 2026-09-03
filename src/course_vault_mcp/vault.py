from __future__ import annotations

import hashlib
import os
from pathlib import Path
import secrets
import stat
import tempfile
from typing import Any

from .security import safe_markdown_path, validate_note_content


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def atomic_create(path: Path, content: str) -> None:
    """Atomically publish a new file without ever replacing an existing target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError as exc:
            raise ValueError("VAULT_CONFLICT: target appeared after preview") from exc
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            # Some platforms do not support fsync on directory descriptors.
            pass
    finally:
        temporary.unlink(missing_ok=True)


def _directory_flags() -> int:
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise RuntimeError("secure Vault publication requires O_NOFOLLOW and O_DIRECTORY")
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _open_parent_beneath(
    root: Path,
    relative_path: str,
    *,
    create_directories: bool,
) -> tuple[int, str, Path] | None:
    """Open the target parent through dirfds without following any symlink."""
    validated = safe_markdown_path(root, relative_path)
    resolved_root = root.resolve()
    relative = validated.relative_to(resolved_root)
    directory_parts = relative.parts[:-1]
    target_name = relative.parts[-1]
    flags = _directory_flags()
    try:
        current_fd = os.open(resolved_root, flags)
    except OSError as exc:
        raise ValueError("configured Vault root is missing or unsafe") from exc
    try:
        for part in directory_parts:
            try:
                child_fd = os.open(part, flags, dir_fd=current_fd)
            except FileNotFoundError:
                if not create_directories:
                    os.close(current_fd)
                    return None
                try:
                    os.mkdir(part, mode=0o700, dir_fd=current_fd)
                except FileExistsError:
                    pass
                try:
                    child_fd = os.open(part, flags, dir_fd=current_fd)
                except OSError as exc:
                    raise ValueError("Vault note parent is missing or unsafe") from exc
            except OSError as exc:
                raise ValueError("Vault note parent is missing or unsafe") from exc
            os.close(current_fd)
            current_fd = child_fd
        return current_fd, target_name, validated
    except Exception:
        try:
            os.close(current_fd)
        except OSError:
            pass
        raise


def _read_beneath(root: Path, relative_path: str, max_bytes: int) -> tuple[bytes | None, Path]:
    opened = _open_parent_beneath(root, relative_path, create_directories=False)
    if opened is None:
        return None, safe_markdown_path(root, relative_path)
    parent_fd, target_name, validated = opened
    descriptor: int | None = None
    try:
        flags = os.O_RDONLY | os.O_NOFOLLOW
        try:
            descriptor = os.open(target_name, flags, dir_fd=parent_fd)
        except FileNotFoundError:
            return None, validated
        except OSError as exc:
            raise ValueError("Vault note target is not a safe regular file") from exc
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("Vault note target is not a safe regular file")
        if metadata.st_size > max_bytes:
            raise ValueError("existing Vault note exceeds the configured size limit")
        data = bytearray()
        while len(data) <= max_bytes:
            chunk = os.read(descriptor, min(65536, max_bytes + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        if len(data) > max_bytes:
            raise ValueError("existing Vault note exceeds the configured size limit")
        return bytes(data), validated
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent_fd)


def _atomic_create_beneath(root: Path, relative_path: str, content: str) -> tuple[Path, bytes]:
    """Create and verify one file beneath root using only no-follow dirfd calls."""
    opened = _open_parent_beneath(root, relative_path, create_directories=True)
    if opened is None:  # pragma: no cover - create_directories=True cannot return None
        raise RuntimeError("failed to open Vault note parent")
    parent_fd, target_name, validated = opened
    temporary_name = f".{target_name}.{secrets.token_hex(12)}.tmp"
    descriptor: int | None = None
    created = False
    encoded = content.encode("utf-8")
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        descriptor = os.open(temporary_name, flags, 0o600, dir_fd=parent_fd)
        remaining = memoryview(encoded)
        while remaining:
            written_count = os.write(descriptor, remaining)
            if written_count <= 0:  # pragma: no cover - defensive OS failure guard
                raise OSError("short write while creating Vault note")
            remaining = remaining[written_count:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        try:
            os.link(
                temporary_name,
                target_name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
            created = True
        except FileExistsError as exc:
            raise ValueError("VAULT_CONFLICT: target appeared after preview") from exc

        read_fd = os.open(target_name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
        try:
            metadata = os.fstat(read_fd)
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("created Vault note is not a regular file")
            if metadata.st_size > len(encoded):
                raise ValueError("created Vault note changed during verification")
            written = bytearray()
            while len(written) <= len(encoded):
                chunk = os.read(read_fd, min(65536, len(encoded) + 1 - len(written)))
                if not chunk:
                    break
                written.extend(chunk)
            if len(written) > len(encoded):
                raise ValueError("created Vault note changed during verification")
        finally:
            os.close(read_fd)
        os.fsync(parent_fd)
        return validated, bytes(written)
    finally:
        try:
            if descriptor is not None:
                os.close(descriptor)
            try:
                os.unlink(temporary_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
            except OSError:
                if not created:
                    raise
        finally:
            os.close(parent_fd)


class VaultWriter:
    def __init__(self, root: Path, backup_root: Path, max_note_bytes: int):
        self.root = root.resolve()
        self.backup_root = backup_root.resolve()
        self.max_note_bytes = max_note_bytes

    def preview(self, relative_path: str, content: str) -> dict[str, Any]:
        validate_note_content(content, self.max_note_bytes)
        encoded = content.encode("utf-8")
        before, target = _read_beneath(self.root, relative_path, self.max_note_bytes)
        return {
            "target": str(target),
            "exists": target.exists(),
            "changed": before != encoded,
            "before_sha256": sha256_bytes(before) if before is not None else None,
            "after_sha256": sha256_bytes(encoded),
            "bytes": len(encoded),
        }

    def write(
        self,
        relative_path: str,
        content: str,
    ) -> dict[str, Any]:
        preview = self.preview(relative_path, content)
        before, target = _read_beneath(self.root, relative_path, self.max_note_bytes)
        current_before_sha256 = sha256_bytes(before) if before is not None else None
        if str(target) != preview["target"] or current_before_sha256 != preview["before_sha256"]:
            raise ValueError("VAULT_CONFLICT: target path changed after preview")
        encoded = content.encode("utf-8")
        if before is not None and before == encoded:
            return {**preview, "written": False, "verified": True}
        if before is not None:
            raise ValueError(
                "VAULT_CONFLICT: v0.1 never overwrites an existing note; publish a revision and merge manually"
            )
        target, written = _atomic_create_beneath(self.root, relative_path, content)
        if sha256_bytes(written) != preview["after_sha256"]:
            raise RuntimeError("vault write verification failed")
        return {**preview, "target": str(target), "written": True, "verified": True}
