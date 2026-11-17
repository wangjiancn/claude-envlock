# Security model

## What claude-envlock guarantees

For the **managed entry points** (`~/.claude-env/bin/*`, the VS Code extension through
`claudeProcessWrapper`, `Claude Envlock.app`):

| Guarantee | How |
| --- | --- |
| Nothing starts unless the local proxy tunnels to `claude.ai:443` **and** the origin presents a valid certificate | `proxy.gate()`. A `200` from the proxy alone is not enough. |
| The gate sends no credentials | Only `CONNECT` plus a TLS handshake. No HTTP request, cookie, token, or prompt. |
| Child processes use the proxy, with no external bypass | Both cases of `HTTP(S)_PROXY` set; `ALL_PROXY` removed; `NO_PROXY` = loopback only |
| The IDE wrapper only runs the official extension binary | Path must be under `~/.vscode/extensions/anthropic.claude-code-*/` and named `claude` |
| `claude-web` won't open dangerous URLs | HTTPS only (HTTP only for loopback OAuth callbacks); no `user:pass@`; no `--flags` |
| The dedicated Chrome doesn't resolve DNS locally, doesn't leak WebRTC UDP, and doesn't use QUIC | `--host-resolver-rules`, `--force-webrtc-ip-handling-policy=disable_non_proxied_udp`, `--disable-quic` |
| Environment variables can't inject code into the gate | Shims run `python3 -IB` |
| The live setup matches `claude.env`, or the user explicitly approves each launch | `integrity.verify()` on every launch → Block/Continue popup (or a hard block with `on_mismatch=block`) |
| The exit IP is on your allowlist, or the user explicitly approves | One cookie-free GET to `claude.ai/cdn-cgi/trace` through the proxy, so it follows the same proxy rule as Claude |
| A popup can't be turned into code execution | The message is passed to `osascript` as `argv`, never spliced into the script. Default button and timeout = Block |
| The install can be undone exactly | Byte-level backups; all-or-nothing rollback with conflict detection |

## What it does **not** guarantee

- **Not a network sandbox.** Unmanaged paths bypass it: running the original binary by its
  absolute path, other IDEs/forks, Claude Desktop, third-party clients, and links opened in your
  everyday browser.
- **No view into the proxy.** If your proxy has a `DIRECT` fallback, or routes `claude.ai`
  differently from what you expect, claude-envlock can't detect it. Check your proxy's connection log.
- **Drift detection is not tamper-proofing.** It catches accidents, stray tools, and unapplied edits.
  A program running as your user can rewrite both the managed files and the manifest.
- **Continue means continue.** If you click Continue, that launch runs despite the listed problems.
  Use `CLAUDE_ENVLOCK_ON_MISMATCH="block"` if you never want that option.
- **The trace endpoint is Cloudflare's, not Anthropic's API.** If claude.ai stops serving
  `/cdn-cgi/trace`, the exit IP can't be verified, and launches prompt (or block).
- **Only checked at launch.** If the proxy dies mid-session, the managed CLI's requests fail,
  because it uses an explicit proxy with no fallback. But nothing is re-checked continuously.
- **Country lookups are diagnostics, not evidence.** Third-party sites (Cloudflare, ipinfo) may take a
  different route from Claude itself.
- **No fingerprint changes.** System language, fonts, and the browser timezone are left alone on purpose.
- **No account-safety promises.**

## Sensitive data on disk

| Path | Contains | Mode |
| --- | --- | --- |
| `~/.claude-env/backups/manifest.json` | Original copies of your shell, Claude, and VS Code configs | `0600` |
| `~/.claude-env/chrome-profile/` | Your Claude web login | `0700` |
| `~/.claude-env/claude.env` | Settings and any extra variables you add. **Don't put API keys here** if you plan to share it | `0600` |
| `~/.claude-env/decisions.log` | Timestamps and problem lists from Block/Continue prompts | `0600` |
| `~/.claude-env/cli-smoke-last.jsonl` | Raw transcript of the last smoke test | `0600` |

Never commit, attach, or share these files.

## Reporting

See [SECURITY.md](../SECURITY.md).
