# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [SemVer](https://semver.org/).

## [Unreleased]

### Added
- `--install-claude [stable|latest|VERSION]`: on a machine without Claude Code, install it with
  Anthropic's official native installer, downloaded and run **through the verified proxy**.
  Redirects are pinned to `claude.ai` / `downloads.claude.ai`. Skipped if Claude Code is already installed.

### Changed
- **Timezone is now always set**, defaulting to `Asia/Jakarta`. `--no-timezone` is removed; an empty
  `CLAUDE_ENVLOCK_TIMEZONE` means the default.
- **China timezones are rejected** (`Asia/Shanghai`, `Asia/Urumqi`, `Asia/Hong_Kong`, `Asia/Macau`, and aliases).
- **The installer checks the timezone against the exit IP country** seen by `claude.ai/cdn-cgi/trace`, and
  stops before writing anything on a mismatch. `--skip-timezone-check` installs anyway. `claude-check` shows
  the same comparison as a `WARN` line.
- **Shared settings files are now owned key by key.** In `~/.claude/settings.json` and VS Code's
  `settings.json`, install and rollback touch only claude-envlock's keys and never refuse because of other
  edits. A hand edit to a managed key is replaced on install, printed, and the file is copied to
  `backups/`. Rollback keeps everything changed after the install. Older whole-file records are migrated
  automatically. `--merge-unmanaged-settings` is no longer needed (still accepted, does nothing).
- Edits outside the managed block in `.zshrc` / `.zprofile` no longer cause a conflict. They are kept
  and folded into the rollback backup.
- Requests to claude.ai now send a `claude-envlock` User-Agent (claude.ai returns 403 to the default
  `Python-urllib` agent).

### Fixed
- The dedicated Chrome no longer shows the "You are using an unsupported command-line flag:
  --host-resolver-rules…" warning bar. The flag was removed: with `--proxy-server`, Chrome already sends
  hostnames to the proxy and sends no DNS queries itself (verified with Chrome 157's net log).
- A fresh install under a symlinked home (for example `/tmp` → `/private/tmp`) reported drift and
  blocked launches. The installer now resolves the install root the same way the launchers do.

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
