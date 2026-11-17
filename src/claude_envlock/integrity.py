"""Startup drift detection: does the live setup still match what claude.env says?

- Files claude-envlock fully owns (launchers, runtime, config.json, claude.env, the app) are compared by hash.
- Shared files are compared only on the parts claude-envlock manages, so Claude writing its own
  settings (for example "tui") never triggers a prompt.
"""
import json
from pathlib import Path

from .common import SHELL_FILES, manifest_path, render_shell_block, sha256, short_path
from .jsonc import loads

ENV_FILE = 'claude.env'


def _owned(path, roots):
    resolved = path.resolve()
    return any(resolved == r or r in resolved.parents for r in roots)


def check_owned_files(cfg):
    path = manifest_path(cfg.root)
    if not path.exists():
        return ['No deployment record ({}). Re-run ./install.sh.'.format(short_path(path))]
    manifest = json.loads(path.read_text())
    roots = [cfg.root.resolve()] + ([Path(manifest['app_dir']).resolve()] if manifest.get('app_dir') else [])
    problems = []
    for name, record in manifest['files'].items():
        file = Path(name)
        if not _owned(file, roots):
            continue
        if file.is_symlink() or not file.is_file():
            problems.append('Missing: ' + short_path(file))
        elif sha256(file.read_bytes()) != record['installed_sha256']:
            problems.append('claude.env was edited but not applied (run ./install.sh)'
                            if file.name == ENV_FILE else 'Modified: ' + short_path(file))
    return problems


def check_claude_settings(cfg, home):
    path = home / '.claude' / 'settings.json'
    try:
        env = json.loads(path.read_text()).get('env', {})
    except (OSError, ValueError, AttributeError):
        return ['Unreadable: ' + short_path(path)]
    return ['{}: env.{} changed'.format(short_path(path), key)
            for key, value in cfg.managed_env().items() if env.get(key) != value]


def check_vscode_settings(cfg, home):
    path = home / 'Library' / 'Application Support' / 'Code' / 'User' / 'settings.json'
    try:
        data = loads(path.read_text())
    except (OSError, ValueError):
        return ['Unreadable: ' + short_path(path)]
    problems = []
    if data.get('claudeCode.claudeProcessWrapper') != str(cfg.bin_dir / 'claude-ide-wrapper'):
        problems.append('VS Code: claudeCode.claudeProcessWrapper changed')
    variables = data.get('claudeCode.environmentVariables', [])
    actual = {v.get('name'): v.get('value') for v in variables if isinstance(v, dict)} \
        if isinstance(variables, list) else {}
    problems += ['VS Code: environment variable {} changed'.format(key)
                 for key, value in cfg.managed_env().items() if actual.get(key) != value]
    return problems


def check_shell(home):
    problems = []
    for name in SHELL_FILES:
        path = home / name
        try:
            text = path.read_text()
        except OSError:
            text = ''
        if render_shell_block(name) not in text:
            problems.append('{}: managed block changed or removed'.format(short_path(path)))
    return problems


def verify(cfg, home=None):
    """Return a list of human-readable problems. Empty means everything matches."""
    home = Path(home or Path.home())
    return (check_owned_files(cfg) + check_claude_settings(cfg, home)
            + check_vscode_settings(cfg, home) + check_shell(home))
