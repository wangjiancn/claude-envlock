# Contributing

Thanks for helping! This project is small on purpose. Please keep it that way.

## Ground rules

- **Standard library only**, compatible with Python **3.9** (the macOS system Python).
  No f-string `=` specifiers, no `match`, no `X | Y` type unions.
- **Fail closed.** A new code path must never start Claude or Chrome when the gate fails.
- **Never print secrets.** No raw network errors, URLs, environment dumps, or file contents in output.
- **Reversible installs.** Anything the installer writes must go through `Plan.stage()`, so it is
  backed up and rolled back.
- Separation of concerns: the runtime modules (`common`, `config`, `proxy`, `launchers`, `cli`, `rollback`)
  are deployed. `installer` and `jsonc` are not. Don't import installer code from the runtime.

## Workflow

```sh
make test              # must pass
./install.sh --dry-run # sanity check on your own machine (writes nothing)
```

- Add a test for every behavior change. Use `IsolatedHome` for anything that touches files, and
  cover both install **and** rollback.
- Update `CHANGELOG.md` under an `Unreleased` heading.
- If you change user-visible behavior, update `README.md`. If you change the guarantees, update
  `docs/security-model.md`.
- One logical change per pull request. Explain the *why* in the description.

## Reporting bugs

Include your macOS version, `/usr/bin/python3 --version`, how you installed Claude Code, and the
output of `./install.sh --dry-run`. **Redact** paths that contain your username if you prefer, and
never attach `~/.claude-env/backups` or `chrome-profile`.
