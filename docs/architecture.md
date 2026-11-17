# Architecture

## Design goals

1. **Fail closed.** If the proxy can't be verified, the real program never starts.
2. **Leave no surprises.** Every file the installer touches is backed up byte-for-byte, and rollback
   restores it exactly. Unrelated settings, comments, and shell content are preserved.
3. **Zero dependencies.** Standard library only, Python 3.9 (the macOS system Python).
4. **Small, auditable runtime.** The code that runs on every `claude` launch is a few hundred lines.

## Repository layout

```
install.sh / install.py      entry points → claude_envlock.installer
src/claude_envlock/
  __init__.py                version
  common.py                  constants, sha256, atomic_write
  config.py                  Config dataclass ⇄ ~/.claude-env/config.json (validated)
  proxy.py                   proxy_environment(), gate(), country_diagnostics()
  launchers.py               preflight(), run_cli() (terminal + IDE), open_web() (Chrome)
  integrity.py               drift detection against the manifest + claude.env
  prompt.py                  Block/Continue popup → /dev/tty fallback → block; decisions.log
  envfile.py                 claude.env parse/render (strict shell subset)          [repo only]
  cli.py                     main(root, argv): dispatches on argv[0]
  rollback.py                conflict check + restore
  installer.py               Plan (transaction) + staging steps      [repo only]
  bootstrap.py               --install-claude: official installer via the proxy      [repo only]
  jsonc.py                   comment-preserving JSONC read/edit (also used by integrity)
tests/                       unittest; isolated HOME, fake proxy, real shim execution
tools/                       real-CLI smoke test
```

## Deployed layout

```
~/.claude-env/
  bin/claude, claude-npm, claude-native, claude-check, claude-gate,
      claude-web, claude-ide-wrapper, claude-rollback      ← identical shims
  lib/claude_envlock/*.py                                      ← runtime modules only
  claude.env                                                ← source of truth (user-edited)
  config.json                                               ← generated
  backups/manifest.json
  decisions.log
  chrome-profile/
```

Each shim is:

```python
#!/usr/bin/python3 -IB
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'lib'))
from claude_envlock.cli import main
sys.exit(main(ROOT, sys.argv))
```

`-I` (isolated mode) ignores `PYTHONPATH`, `PYTHONHOME`, and user site-packages, so nothing in the
caller's environment can inject code into the gate. `-B` stops `__pycache__` from being written, so
rollback leaves no stray files.

## Runtime flow

```
cli.main(root, argv)
 ├─ claude-rollback      → rollback.main()           (works without config.json)
 ├─ Config.load(root)    → validate host == 127.0.0.1, port, timezone
 ├─ claude-check         → gate() [+ country_diagnostics()]
 ├─ claude / -npm / -native
 │    resolve_cli()  → first executable candidate that does not resolve into ~/.claude-env
 │    preflight():
 │      problems  = integrity.verify()     hashes of owned files + managed keys of shared files
 │      gate()                             CONNECT + TLS; failure = hard block (no prompt)
 │      problems += exit_ip_problems()     only if an allowlist is set
 │      problems → prompt.confirm()        Block (default) / Continue; or hard block by policy
 │    os.execve(real, args, cli_environment())          (replaces the process; no wrapper left)
 ├─ claude-ide-wrapper
 │    verify_ide_binary(argv[1]) → must be ~/.vscode/extensions/anthropic.claude-code-*/…/claude
 │    preflight() → execve
 └─ claude-web
      validate_url() → https only (http only for loopback), no userinfo, no flags
      preflight() → Popen(Chrome --user-data-dir --proxy-server
                     --force-webrtc-ip-handling-policy --disable-quic, env=browser_environment())
```

Any `ValueError`/`RuntimeError` message is printed as is. Any other exception is reduced to its type
name, because raw network errors can echo URLs, and OAuth URLs carry secrets.

## Source of truth: `claude.env`

```
claude.env ──(./install.sh)──► config.json, Claude settings env, VS Code env + wrapper, shell block, launchers
     ▲                                                   │
     └──────── integrity.verify() on every launch ◄─────┘
```

- The installer reads `CLAUDE_ENVLOCK_*` settings and extra variables from `claude.env`. CLI flags
  override individual values. Older installs without `claude.env` migrate from `config.json`.
- The installer re-renders `claude.env` in canonical form. It is staged with `user_editable=True`,
  so editing it is the normal way to request a change, not a conflict.
- Generated lines (`HTTP_PROXY`, `TZ`, …) are rewritten each time. A generated line that matches
  neither the previous nor the new value was hand-edited, so the installer refuses to apply.
- Keys that leave the managed env (for example an extra variable you deleted) are removed from
  Claude and VS Code settings, but only if they still hold the value we wrote.

## Installer transaction

`installer.run()` builds a `Plan`:

1. Resolve settings from `claude.env` (+ flags), so values stay the same across upgrades.
2. `stage(path, content, mode)` for every desired file. For each file:
   - refuse symlinks;
   - if it's already managed and its current hash ≠ the recorded `installed_sha256` → **conflict, stop**
     (unless `--merge-unmanaged-settings` applies, for `~/.claude/settings.json` only);
   - skip it if it's already identical;
   - the first time it's touched, record `existed`, `mode`, and the original bytes (base64).
3. `--dry-run` stops here.
4. `apply()`: write the manifest first, then write each file atomically (temp file + `fsync` + `rename`).
   If anything fails, restore the snapshots and the previous manifest.

The manifest format (`version: 1`) is stable and shared with `rollback.py`, so older deployments
upgrade in place.

## Extending

- **Another IDE** (Cursor, VS Code Insiders): add its settings path in a `stage_*` function, and
  add its extensions directory to `verify_ide_binary`.
- **Another browser**: add a `*_command()` builder next to `chrome_command()`.
- **Another shell**: extend `stage_shell()`; keep exactly one marked block per file.

Every new behavior needs a test in `tests/`. Anything that writes files needs an `IsolatedHome` test
that covers both install and rollback.
