# Testing and acceptance

## 1. Automated tests (run on every change)

```sh
make test        # = /usr/bin/python3 -m unittest -v
```

The tests need no network, no real proxy, and no real Claude install. They use:

- `FakeProxy`: a local socket that records the `CONNECT` and replies with a chosen status;
- `closed_port()`: a bound but non-listening port, for a race-free "connection refused";
- `IsolatedHome`: a temporary `HOME` with a fake `claude`, which runs the **real installer** and
  the **real deployed rollback shim** end to end.

CI runs them on macOS with Python 3.9 and 3.12 (`.github/workflows/ci.yml`).

## 2. Local checks after installing

```sh
./install.sh --dry-run                     # expect "Files to update: 0"
~/.claude-env/bin/claude-check             # expect every line OK/INFO, exit 0
~/.claude-env/bin/claude-rollback --check  # expect "pre-check passed"
whence -p claude                           # new terminal: ~/.claude-env/bin/claude
```

## 3. Real Claude smoke test (costs quota)

```sh
make smoke                         # or: /usr/bin/python3 tools/run_smoke.py
/usr/bin/python3 tools/run_smoke.py --report-only   # re-verify the last log, no model call
```

This test asks the managed Claude CLI to run `tools/smoke_probe.py` through its Bash tool. It runs
with hooks, plugins, and MCP disabled, Bash limited to that one command, a $1 budget cap, and a
120-second timeout. The verifier parses the real tool call and its JSON output. It does **not**
trust the model's summary. The checks:

| Check | Meaning |
| --- | --- |
| `proxy_vars_match` | All four `HTTP(S)_PROXY` vars = configured proxy |
| `no_external_bypass` | `NO_PROXY` = loopback only |
| `no_socks_override` | No `ALL_PROXY` |
| `browser_wrapper_inherited` | `BROWSER` = `claude-web` |
| `claude_on_path_is_managed` | `which claude` = managed shim |
| `proxy_connect_and_tls_pass` | `claude-check` exit 0 |
| `tz_env_matches`, `node_intl_timezone_matches` | Only if `--timezone` is set |

To test the VS Code extension, ask Claude **in the extension panel** to run
`/usr/bin/python3 <repo>/tools/smoke_probe.py` and paste the JSON.

## 4. Manual scenario checklist

These need a human, a real network, and a real proxy client.

| ID | Scenario | Pass when |
| --- | --- | --- |
| M1 | `claude-web`, Claude Envlock.app, Dock icon | All open the same dedicated profile; `chrome://version` shows the proxy and hardening flags |
| M2 | Proxy connection log | CLI, VS Code, and Chrome requests to `claude.ai` / `anthropic.com` show up under your expected rule and node |
| M3b | DNS (after Chrome updates) | Launch Chrome as `claude-web` does, plus `--log-net-log=/tmp/n.json`, and open a made-up `https://random-123.example.com/`. The proxy gets `CONNECT random-123.example.com:443`, and the net log has no `HOST_RESOLVER_SYSTEM_TASK` / `DNS_TRANSACTION` events |
| M3 | WebRTC | A STUN probe in the dedicated Chrome shows no non-proxied UDP candidates |
| M4 | Quit the proxy, then launch | `claude`, `claude-web`, and the IDE all refuse to start; the error names no secrets |
| M5 | Quit the proxy mid-session | Requests fail; nothing goes out directly |
| M6 | Wi-Fi switch / sleep–wake | Same as M4/M5 after resume |
| M7 | OAuth | The login link opens in the dedicated Chrome (otherwise use `claude-web '<link>'`) |
| M8a | Edit `claude.env` without applying, then run `claude` | Popup lists "claude.env was edited but not applied"; Block stops it; Continue launches; both logged in `decisions.log` |
| M8b | Set an allowlist that excludes your current exit IP | Popup shows the masked IP; with `--on-mismatch block` it stops without a popup |
| M8c | Same as M8a, but over SSH (no GUI) | Asks in the terminal; Enter (empty) blocks |
| M8 | Timezone (if set) | CLI usage panel shows the configured zone; `readlink /etc/localtime` and Chrome's `Intl` are unchanged |

Record each item as Pass / Fail / Not tested / N/A. "Not tested" is never "Pass". Redact emails,
account IDs, tokens, cookies, OAuth links, and subscription URLs from screenshots.

A detailed Chinese version of this procedure is in [zh-CN/acceptance.md](zh-CN/acceptance.md).
