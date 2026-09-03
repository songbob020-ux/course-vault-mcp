from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import course_vault_mcp.vault as vault_module
from course_vault_mcp.security import (
    safe_markdown_path,
    sanitize_source_url,
    validate_note_content,
)
from course_vault_mcp.vault import VaultWriter


class SecurityTests(unittest.TestCase):
    def test_source_url_is_allowlisted_and_stripped(self) -> None:
        value = sanitize_source_url(
            "https://courses.example.com/lesson/1?signature=secret#player",
            ("courses.example.com",),
        )
        self.assertEqual(value, "https://courses.example.com/lesson/1")

    def test_source_url_rejects_unlisted_host(self) -> None:
        with self.assertRaises(ValueError):
            sanitize_source_url("https://evil.example/lesson", ("courses.example.com",))

    def test_vault_path_rejects_traversal_and_protected_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                safe_markdown_path(root, "../outside.md")
            with self.assertRaises(ValueError):
                safe_markdown_path(root, ".obsidian/plugins.md")
            self.assertEqual(
                safe_markdown_path(root, "Courses/L1.md"),
                (root / "Courses" / "L1.md").resolve(),
            )

    def test_vault_path_rejects_symlink_into_protected_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".obsidian").mkdir()
            (root / "Courses").mkdir()
            (root / "Courses" / "alias").symlink_to(root / ".obsidian", target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symbolic links"):
                safe_markdown_path(root, "Courses/alias/plugins.md")

    def test_vault_write_rejects_parent_symlink_swap_after_safe_path_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "vault"
            protected = root / ".obsidian"
            courses = root / "Courses"
            protected.mkdir(parents=True)
            courses.mkdir()
            writer = VaultWriter(root, Path(directory) / "backups", 10000)
            real_safe_path = vault_module.safe_markdown_path
            call_count = 0

            def swap_after_validation(vault_root: Path, relative_path: str) -> Path:
                nonlocal call_count
                validated = real_safe_path(vault_root, relative_path)
                call_count += 1
                # write() performs two safe reads first. During the secure create,
                # replace the already-validated parent immediately after the
                # path check, reproducing the former check/use race.
                if call_count == 3:
                    courses.rename(root / "Courses.original")
                    courses.symlink_to(protected, target_is_directory=True)
                return validated

            with patch.object(vault_module, "safe_markdown_path", swap_after_validation):
                with self.assertRaisesRegex(ValueError, "unsafe"):
                    writer.write("Courses/L1.md", "# Safe summary\n")

            self.assertFalse((protected / "L1.md").exists())
            self.assertFalse((root / "Courses.original" / "L1.md").exists())

    def test_note_rejects_raw_caption_and_credentials(self) -> None:
        with self.assertRaises(ValueError):
            validate_note_content("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello", 10000)
        with self.assertRaises(ValueError):
            validate_note_content("Cookie: session=secret", 10000)
        validate_note_content("# Original summary\n\nA short source-linked conclusion.", 10000)


if __name__ == "__main__":
    unittest.main()
