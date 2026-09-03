# Privacy and content policy

Course Vault MCP is designed for material the user is authorized to access.

## Never collected by the MCP

- usernames, passwords, MFA codes;
- browser cookies, storage state, profiles, or authorization headers;
- payment information;
- full video files or DRM-protected media.

## Private temporary data

Raw captions and selected review frames may exist only in the configured local
temporary cache. They are excluded from Git and are not written to Obsidian by
this package.

When a review packet is requested, the adapter reads the matching raw WebVTT
under a separate size limit, recomputes its hash, and regenerates segments in
memory. Raw WebVTT bytes are not stored in workflow state, logs, exceptions, or
tool responses; the tool returns only bounded semantic segments.

`get_review_packet` intentionally returns a bounded source excerpt to the MCP
Host. If that Host uses a cloud model, the excerpt may be processed by that
provider. Use a local model or disable `allow_bounded_source_segments` when the
source must not leave the machine.

## Durable data

The workflow database stores metadata, hashes, source locations, file paths,
statuses, and audit events. Obsidian receives original summaries and short source
locators, not transcripts or course media.

## GitHub export boundary

Do not commit private configuration, real collector manifests, member captions,
frames, Vault content, SQLite state, logs, or credentials—even to a private
repository. Keep code and private course workspaces physically separate.
