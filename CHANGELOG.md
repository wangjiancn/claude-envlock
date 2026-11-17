# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [SemVer](https://semver.org/).

## [2.0.0] - 2026-11-17

First public release, renamed from the private `claude-safe` to **claude-envlock**.

### Changed
- The runtime is split into the `claude_envlock` package (`config`, `proxy`, `launchers`, `cli`, `rollback`).
  It is deployed to `~/.claude-env/lib`. Each command in `bin/` is a small `python3 -IB` shim.
- `--timezone` is now opt-in (no default). Once set, it is remembered across re-installs.
  `--no-timezone` clears it.
- `--port` and the other settings default to the values in `claude.env`.
- Messages and docs are now in English. A Chinese README and acceptance guide are included.

### Added
- **`~/.claude-env/claude.env` as the single source of truth.** Edit it and run `./install.sh` to apply.
  Scripts can `source` it. Extra variables in it are passed to Claude everywhere.
- **Drift check on every launch.** Hashes of owned files, plus the managed keys in Claude, VS Code,
  and shell settings. Unapplied `claude.env` edits count as drift.
- **Exit-IP allowlist** (`CLAUDE_ENVLOCK_ALLOWED_EXIT_IPS`, `--exit-ips`), verified through
  `claude.ai/cdn-cgi/trace`, so it follows the same proxy rule as Claude.
- **Block / Continue popup** on drift or a disallowed exit IP, with a terminal fallback, a 120 s
  timeout that blocks, and `decisions.log`. `CLAUDE_ENVLOCK_ON_MISMATCH="block"` (or `--on-mismatch block`)
  always blocks.
- `claude-check` reports the proxy, exit IP, and drift, and exits 1 on any problem.
- `--claude PATH` (repeatable) and `--chrome PATH` installer options. Auto-detection now also
  covers Intel Homebrew (`/usr/local/bin/claude`).
- Stricter IDE binary check: the first path component under `~/.vscode/extensions` must be
  `anthropic.claude-code-*`.
- Self-contained test suite (no dependence on the host's Claude install) and macOS CI.
- Architecture, security-model, and testing docs; CONTRIBUTING and SECURITY policies.

### Upgrade notes
- Upgrading in place from 1.x (`claude-safe`) works: the manifest format and `~/.claude-env` are unchanged.
  Run `./install.sh --dry-run` first. The installer automatically:
  - replaces the old `# >>> Claude Safe managed entry >>>` shell block (no duplicate block);
  - reads old `CLAUDE_SAFE_*` names in `claude.env` and rewrites them as `CLAUDE_ENVLOCK_*`;
  - removes `/Applications/Claude Safe.app` (if unchanged) and creates `Claude Envlock.app`.
- The recursion guard variable is now `CLAUDE_ENVLOCK_ACTIVE`.

## [1.0.0] - 2026-11-13

Initial private version.
