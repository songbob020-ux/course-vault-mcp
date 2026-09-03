# Security policy

## Supported version

`0.1.x` is an alpha intended for localhost and stdio use on macOS and Linux.
It depends on POSIX file locking and no-follow filesystem APIs; Windows is not
supported in v0.1.

## Threat model

The package assumes course pages and caption text are untrusted inputs. It limits
source hosts, strips URL queries, bounds source excerpts, restricts Vault paths,
rejects transcript-like or credential-like note content, detects overwrite
conflicts, and verifies writes by SHA-256.

v0.1 intentionally supports stdio only. Do not add remote transport, arbitrary URL fetch,
browser-cookie export, shell execution, or unrestricted filesystem tools.

## Reporting

Before publishing a repository, configure GitHub private vulnerability reporting.
Do not include real credentials, member content, signed media URLs, or private
paths in a security report.
