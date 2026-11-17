# claude-envlock

**Unofficial. An isolated, locked-down launch environment for Claude Code on macOS.**

Fail-closed proxy gate · exit-IP allowlist · drift detection · one `claude.env` as the source of truth.

[![CI](https://github.com/wangjiancn/claude-envlock/actions/workflows/ci.yml/badge.svg)](https://github.com/wangjiancn/claude-envlock/actions/workflows/ci.yml)

[English](README.md) · [简体中文](README.zh-CN.md)

If you reach Claude through a local HTTP proxy (Clash, Surge, a corporate proxy, …), a misconfigured
terminal or a proxy that is quietly down can send traffic out the wrong way. `claude-envlock` wraps each
Claude entry point so it **checks the proxy before starting, and refuses to start if the check fails**.

| Entry point | What claude-envlock does |
| --- | --- |
| `claude` in Terminal | Gate check → force proxy env → `exec` the real CLI |
| VS Code (official Claude Code extension) | Same gate via `claudeCode.claudeProcessWrapper` |
| `claude-web` / **Claude Envlock.app** | Gate check → dedicated Chrome profile with a forced proxy (hostnames go to the proxy, no local DNS), WebRTC and QUIC hardening |

On top of that, one file, `~/.claude-env/claude.env`, is the **single source of truth**
for Claude's environment. If anything drifts from it, or your proxy's exit IP isn't on your
allowlist, launches stop with a **Block / Continue** popup.

It does **not** touch your proxy nodes, routing rules, system proxy, system language, system timezone,
fonts, or default browser. No pip or npm dependencies: it runs on the macOS system Python.

> Not affiliated with or endorsed by Anthropic. Use it in line with Anthropic's
> [Usage Policy](https://www.anthropic.com/legal/aup) and
> [supported regions](https://www.anthropic.com/supported-countries). This is a network-hygiene tool. It does not hide who you are.

## How it works

```
claude ──► gate: CONNECT claude.ai:443 via 127.0.0.1:<port> ──► verify origin TLS cert ──► exec real claude
               │                                                   (no HTTP request, no cookies, no tokens)
               └── any failure ──► print reason, exit 1, never run the real CLI
```

Before launch, every wrapper also:

- sets `HTTP(S)_PROXY` (both cases) to the local proxy, and removes `ALL_PROXY` and external `NO_PROXY` entries;
- sets `BROWSER` to `claude-web`, so OAuth links open in the dedicated Chrome profile;
- turns off non-essential Claude Code traffic, telemetry, and error reporting;
- optionally pins `TZ` for Claude processes only (see [Timezone](#optional-pin-a-timezone-for-claude-processes));
- checks for drift from `claude.env` and, if you set an allowlist, checks the exit IP (see below).

More details: [docs/architecture.md](docs/architecture.md) · [docs/security-model.md](docs/security-model.md)

## Requirements

- macOS (tested on Apple Silicon) with `/usr/bin/python3` (3.9+, ships with the Xcode Command Line Tools)
- A local HTTP proxy listening on `127.0.0.1` (default port `7890`)
- Claude Code CLI (Homebrew, npm, or native installer), **or** let the installer install it for you (`--install-claude`).
  Optional: VS Code + the official extension, Google Chrome
- zsh (the macOS default shell)

## Install

```sh
git clone https://github.com/wangjiancn/claude-envlock.git
cd claude-envlock
./install.sh --dry-run          # show what would change; writes nothing
./install.sh --port 7890        # install
```

**New Mac without Claude Code?** Install Claude Code and set up the environment in one step:

```sh
./install.sh --install-claude --port 7890            # stable channel
./install.sh --install-claude latest --port 7890     # or: latest / a version like 2.1.311
```

This checks the proxy first, then downloads Anthropic's official installer
(`https://claude.ai/install.sh`) **through the proxy** and runs it. Redirects may only go to `claude.ai` /
`downloads.claude.ai`, and the official installer verifies the binary's SHA-256. Claude Code lands in
`~/.local/bin/claude`, and claude-envlock wraps it. If Claude Code is already installed, this step is
skipped (update it with `claude update`). Rollback doesn't uninstall Claude Code.

Then **open a new terminal**, and in VS Code run **Developer: Reload Window**. Processes that are already
running don't pick up the new settings.

### Installer options

| Option | Meaning |
| --- | --- |
| `--port N` | Local proxy port. First-install default: `7890` |
| `--timezone Area/City` | Pin `TZ` for Claude CLI / IDE processes only. Off by default |
| `--no-timezone` | Stop pinning `TZ` |
| `--exit-ips "IP CIDR …"` | Exit-IP allowlist (`""` turns it off) |
| `--on-mismatch prompt\|block` | What happens on drift or a disallowed exit IP |
| `--install-claude [CHANNEL]` | If Claude Code is missing, install it with the official installer, through the proxy. `stable` (default), `latest`, or a version |
| `--claude PATH` | The original Claude CLI to wrap (repeatable). Default: auto-detects `/opt/homebrew/bin`, `/usr/local/bin`, `~/.local/bin` |
| `--chrome PATH` | Chrome executable. Default: `/Applications/Google Chrome.app/...` |
| `--app-dir PATH` | Where to create `Claude Envlock.app`. Default: `/Applications` |
| `--merge-unmanaged-settings` | Keep settings Claude wrote into `~/.claude/settings.json` itself (for example `tui`) |
| `--dry-run` | Report only |

Each flag edits `~/.claude-env/claude.env`. A flag you leave out keeps the value the file already has.

Re-running the installer is safe. It is idempotent, keeps comments in VS Code's JSONC, and never adds a
second shell block. Your own edits **outside** the marked block in `.zshrc` / `.zprofile` are kept.
If a managed file was edited after deployment, it **stops and names the file** instead of overwriting it.

## Usage

```sh
claude-check              # proxy, TLS, exit IP, drift: full report, no prompt
claude-check --country    # plus a third-party country lookup (diagnostic only)
claude                    # gated Claude CLI (first CLI found)
claude-npm --version      # gated Homebrew/npm CLI
claude-native --version   # gated native-installer CLI
claude-web                # dedicated Chrome → https://claude.ai/
claude-web 'https://…'    # dedicated Chrome → any HTTPS URL (e.g. an OAuth link)
```

You can also open **Claude Envlock.app** from Finder, Spotlight, or the Dock. Your everyday browser and
the dedicated profile keep separate sessions.

> Quit the dedicated Chrome before you change `--port`. A running instance keeps its old flags.

## `claude.env`: one file for Claude's environment

```sh
# ~/.claude-env/claude.env
export CLAUDE_ENVLOCK_PORT="7890"
export CLAUDE_ENVLOCK_TIMEZONE=""                                  # empty = system timezone
export CLAUDE_ENVLOCK_ALLOWED_EXIT_IPS="203.0.113.10 198.51.100.0/24"
export CLAUDE_ENVLOCK_ON_MISMATCH="prompt"                         # or "block"

# ---- Extra variables passed to Claude (add your own) ----
export ANTHROPIC_MODEL="claude-opus-5-5"

# ---- Generated from the settings above. Do not edit ----
export HTTP_PROXY="http://127.0.0.1:7890"
...
```

- **Change something:** edit the file, then run `./install.sh`. The installer writes the change to
  Claude's settings, VS Code, the launchers, and the shell block, all in one transaction.
- **Use it in scripts:** `source ~/.claude-env/claude.env` gives any script the same proxy and
  variables that Claude gets. The format is a strict subset of shell syntax, so it is safe to source.
- **Extra variables** you add are passed to the CLI, the VS Code extension, and
  `~/.claude/settings.json`. Remove a line and apply, and the variable is removed everywhere.
- The generated lines are rewritten each time you apply. If you edit one by hand, the installer
  refuses and tells you which setting to change instead.

### Drift check (every launch)

Before Claude starts, claude-envlock compares the live setup with `claude.env`:

| What | How |
| --- | --- |
| Launchers, runtime code, `config.json`, `claude.env`, the app | Exact SHA-256 match with what was installed |
| `~/.claude/settings.json` | Only the managed `env` values (Claude may write its own settings freely) |
| VS Code settings | Only `claudeProcessWrapper` and the managed `environmentVariables` |
| `.zshrc` / `.zprofile` | The managed block is present and unchanged |

`claude.env` edited but not applied counts as drift too.

### Exit-IP allowlist

If `CLAUDE_ENVLOCK_ALLOWED_EXIT_IPS` is set, each launch makes one cookie-free request to
`https://claude.ai/cdn-cgi/trace` through the proxy (about 1 second) and reads the `ip=` field.
Because the request goes to `claude.ai` itself, your proxy routes it with **the same rule as real
Claude traffic**, unlike third-party IP lookup sites. Single IPs and CIDR ranges, IPv4 and IPv6,
all work. `claude-check` shows your current exit IP, so you know what to allow.

### When something doesn't match

- **Proxy down or TLS invalid:** always blocked. There is no prompt.
- **Drift or a disallowed exit IP:** a macOS popup lists what's wrong, with **Block** (the default)
  and **Continue**. Continue launches this one time; it doesn't accept the change. To make a change
  permanent, apply it with `./install.sh`. If no GUI is available (for example over SSH), it asks in
  the terminal. If neither works, it blocks. If nobody answers within 120 seconds, it blocks.
- `CLAUDE_ENVLOCK_ON_MISMATCH="block"` always blocks, with no popup.
- Every decision is logged to `~/.claude-env/decisions.log` (`0600`).
- `claude-check` never prompts. It prints every check and exits 1 on any problem, so you can use it in scripts.

### Optional: pin a timezone for Claude processes

```sh
./install.sh --timezone Asia/Jakarta
```

This sets `TZ` for the Claude CLI, its subprocesses, and the VS Code extension's process. It is
written to `~/.claude/settings.json` and to VS Code's `claudeCode.environmentVariables`. One use case:
seeing usage reset times in your home timezone while traveling. Your shell, macOS, and the
dedicated Chrome keep the real system timezone. The value is remembered across re-installs; remove it
with `--no-timezone`.

## Uninstall / roll back

```sh
~/.claude-env/bin/claude-rollback --check   # dry run
~/.claude-env/bin/claude-rollback           # restore original files
```

Quit the dedicated Chrome first. Rollback is all-or-nothing. If any managed file changed after
deployment, nothing is restored and the changed files are listed. It restores your original shell,
Claude, and VS Code configs and removes the launchers and the app. The Chrome profile and the
backups stay in `~/.claude-env`.

## Files it manages

| Path | Purpose |
| --- | --- |
| `~/.claude-env/bin/*` | Launcher shims (`0700`) |
| `~/.claude-env/lib/claude_envlock/` | Runtime code |
| `~/.claude-env/claude.env` | **Source of truth** (you edit this). Safe to `source` |
| `~/.claude-env/config.json` | Generated runtime config |
| `~/.claude-env/decisions.log` | Block/Continue decisions (`0600`) |
| `~/.claude-env/backups/manifest.json` | Original bytes of every managed file (`0600`). **Contains your configs; don't share it.** |
| `~/.claude-env/chrome-profile/` | Dedicated Chrome profile (your logins). **Don't share it.** |
| `~/.claude/settings.json` | `env` block |
| `~/Library/Application Support/Code/User/settings.json` | `claudeCode.claudeProcessWrapper`, `claudeCode.environmentVariables` |
| `~/.zprofile`, `~/.zshrc` | One marked block: `PATH` + aliases |
| `/Applications/Claude Envlock.app` | Dock/Spotlight launcher |

## What it does *not* protect

Read [docs/security-model.md](docs/security-model.md) before you rely on this. In short:

- It is **not** a system-wide network sandbox. Running the original binary by its absolute path,
  other IDEs or forks, Claude Desktop, and your everyday browser are not covered.
- It can't see inside your proxy. Whether the proxy falls back to `DIRECT`, and which exit node it
  uses, depends on your proxy configuration.
- The drift check catches accidents and stray edits, **not malware**. A program running as you
  can edit both the files and the manifest.
- The exit IP is checked at launch only. Your proxy can still switch nodes mid-session.
- No browser-fingerprint changes. No promises about account safety.

## Development

```sh
make test                 # or: /usr/bin/python3 -m unittest -v
make smoke                # real Claude run (uses quota, $1 cap) — see docs/testing.md
```

Project layout:

```
src/claude_envlock/   runtime (deployed) + installer and JSONC editor (repo only)
tests/             unit + end-to-end tests with an isolated HOME and a fake proxy
tools/             real-CLI smoke test (probe + verifier)
docs/              architecture, security model, testing/acceptance
```

See [CONTRIBUTING.md](CONTRIBUTING.md). To report a vulnerability, see [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE)
