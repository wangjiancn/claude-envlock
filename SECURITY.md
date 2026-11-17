# Security policy

## Reporting a vulnerability

Please **don't open a public issue** for security problems. Use GitHub's
[private vulnerability reporting](../../security/advisories/new) for this repository instead.

Helpful details: affected version, macOS and Python version, steps to reproduce, and impact.
Never include real tokens, cookies, OAuth links, or files from `~/.claude-env`.

You can expect an acknowledgement within 7 days.

## In scope

- A managed entry point starting Claude or Chrome even though the gate failed
- Bypassing the IDE binary check or the `claude-web` URL check
- Secrets leaking into stdout/stderr or world-readable files
- The installer or rollback corrupting or losing user files

## Out of scope

The limitations listed in [docs/security-model.md](docs/security-model.md) (unmanaged entry
points, proxy-internal routing, fingerprinting) are known and documented. They are not vulnerabilities.
