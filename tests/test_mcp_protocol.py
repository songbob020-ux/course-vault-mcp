from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_exposes_safe_errors_and_no_publish_or_approval_tool(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "vault").mkdir()
            (root / "config").mkdir()
            config = root / "config" / "course-vault.toml"
            config.write_text(
                f'''schema_version = 1
project_id = "protocol-test"
title = "Protocol Test"
state_dir = "{root / 'state'}"

[collector]
kind = "legacy_manifest"
project_root = "{root / 'project'}"
collector_root = "{root / 'collector'}"
cache_root = "{root / 'cache'}"
base_url = "http://127.0.0.1:9"
allowed_source_hosts = ["courses.example.com"]
max_segment_chars = 6000

[vault]
root = "{root / 'vault'}"
lesson_subdir = "Courses/Test"

[policy]
allow_bounded_source_segments = true
require_human_review = true
max_note_bytes = 262144
''',
                encoding="utf-8",
            )
            environment = dict(os.environ)
            environment["COURSE_VAULT_CONFIG"] = str(config)
            parameters = StdioServerParameters(
                command=sys.executable,
                args=["-m", "course_vault_mcp.server"],
                env=environment,
            )
            async with stdio_client(parameters) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    names = {tool.name for tool in tools.tools}
                    self.assertIn("preview_lesson_in_obsidian", names)
                    self.assertNotIn("approve_lesson_draft", names)
                    self.assertNotIn("sync_lesson_to_obsidian", names)
                    by_name = {tool.name: tool for tool in tools.tools}
                    self.assertTrue(
                        by_name["preview_lesson_in_obsidian"].annotations.read_only_hint
                    )
                    self.assertFalse(
                        by_name["save_lesson_draft"].annotations.read_only_hint
                    )
                    error = await session.call_tool(
                        "get_review_packet", {"lesson_id": "bad/id"}
                    )
                    self.assertTrue(error.is_error)
                    rendered = "\n".join(
                        getattr(item, "text", "") for item in error.content
                    )
                    self.assertIn("invalid lesson_id", rendered)


if __name__ == "__main__":
    unittest.main()
