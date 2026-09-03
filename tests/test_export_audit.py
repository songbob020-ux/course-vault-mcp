from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

import importlib.util


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_public_export.py"
SPEC = importlib.util.spec_from_file_location("audit_public_export", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ExportAuditTests(unittest.TestCase):
    def test_rejects_caption_and_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source.vtt").write_text("WEBVTT\n", encoding="utf-8")
            auth_header = "Author" + "ization: Bearer " + "abcdefghijklmnopqrstuvwx"
            (root / "note.md").write_text(
                auth_header, encoding="utf-8"
            )
            reasons = {item["reason"] for item in MODULE.audit(root)}
            self.assertIn("denied file type", reasons)
            self.assertIn("authorization_value", reasons)

    def test_accepts_synthetic_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("# Synthetic course fixture\n", encoding="utf-8")
            self.assertEqual(MODULE.audit(root), [])

    def test_scans_staged_blob_instead_of_clean_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            target = root / "settings.json"
            secret_key = "pass" + "word"
            target.write_text(
                f'{{"{secret_key}":"staged-secret"}}\n', encoding="utf-8"
            )
            subprocess.run(["git", "add", "settings.json"], cwd=root, check=True)
            target.write_text('{"mode":"clean"}\n', encoding="utf-8")
            reasons = {item["reason"] for item in MODULE.audit(root)}
            self.assertIn("json_or_assignment_secret", reasons)


if __name__ == "__main__":
    unittest.main()
