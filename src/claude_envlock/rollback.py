"""Restore original files, but only if no managed file changed after deployment.

Chrome profile, backups and logs are kept.
"""
import base64
import json
import os
from pathlib import Path
import sys

from .common import manifest_path, sha256

USAGE = 'Usage: claude-rollback [--check]'


def conflicts(manifest):
    found = []
    for name, record in manifest['files'].items():
        path = Path(name)
        if path.is_symlink() or not path.is_file() or sha256(path.read_bytes()) != record['installed_sha256']:
            found.append(name)
    return found


def restore(path, record):
    if record['existed']:
        tmp = path.with_name(path.name + '.claude-envlock-restore')
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, record['mode'])
        with os.fdopen(fd, 'wb') as handle:
            handle.write(base64.b64decode(record['original']))
        os.chmod(str(tmp), record['mode'])
        os.replace(str(tmp), str(path))
    else:
        path.unlink()


def remove_empty_dirs(paths):
    for path in paths:
        try:
            path.rmdir()
        except OSError:
            pass


def main(root, args):
    root = Path(root)
    if args not in ([], ['--check']):
        print(USAGE, file=sys.stderr)
        return 2
    path = manifest_path(root)
    if not path.exists():
        print('No active deployment found.')
        return 0
    manifest = json.loads(path.read_text())
    lock = root / 'chrome-profile' / 'SingletonLock'
    if lock.exists() or lock.is_symlink():
        print('Quit the dedicated Chrome first, then roll back.', file=sys.stderr)
        return 1
    changed = conflicts(manifest)
    if changed:
        print('These files changed after deployment. Nothing was rolled back, to keep your edits:\n'
              + '\n'.join(changed), file=sys.stderr)
        return 1
    if args == ['--check']:
        print('Rollback pre-check passed; original files can be restored.')
        return 0
    for name, record in manifest['files'].items():
        restore(Path(name), record)
    path.rename(path.with_name('manifest.rolled-back.json'))
    app = Path(manifest['app_dir']) if manifest.get('app_dir') else None
    lib = root / 'lib' / 'claude_envlock'
    remove_empty_dirs([lib / '__pycache__', lib, root / 'lib']
                      + ([app / 'Contents' / 'MacOS', app / 'Contents', app] if app else []))
    print('Original configuration restored. Chrome profile and backups are kept in {}.'.format(root))
    print('Open a new terminal and run "Developer: Reload Window" in VS Code.')
    return 0
