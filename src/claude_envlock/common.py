"""Shared constants and small filesystem helpers."""
import hashlib
import os
from pathlib import Path

APP_NAME = 'Claude Envlock'
LOOPBACK = '127.0.0.1'
NO_PROXY_VALUE = 'localhost,127.0.0.1,::1'
PROXY_VARS = ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy')
NO_PROXY_VARS = ('NO_PROXY', 'no_proxy')
SOCKS_VARS = ('ALL_PROXY', 'all_proxy')
PRIVACY_VARS = {
    'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1',
    'DISABLE_TELEMETRY': '1',
    'DISABLE_ERROR_REPORTING': '1',
}
GATE_HOST = 'claude.ai'
GATE_PORT = 443
DEFAULT_PORT = 7890
DEFAULT_CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
ACTIVE_FLAG = 'CLAUDE_ENVLOCK_ACTIVE'
# claude.ai rejects the default Python-urllib agent (403); identify the tool honestly instead.
USER_AGENT = 'claude-envlock (+https://github.com/wangjiancn/claude-envlock)'

# Commands placed in <root>/bin. Each one is the same shim; cli.main dispatches on its name.
LAUNCHERS = ('claude', 'claude-npm', 'claude-native', 'claude-check', 'claude-gate',
             'claude-web', 'claude-ide-wrapper', 'claude-rollback')


def default_root():
    return Path.home() / '.claude-env'


def manifest_path(root):
    return Path(root) / 'backups' / 'manifest.json'


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def atomic_write(path, data, mode):
    """Write bytes via a temp file + rename so readers never see a partial file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.claude-envlock-tmp')
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(str(tmp), mode)
        os.replace(str(tmp), str(path))
    finally:
        if tmp.exists():
            tmp.unlink()


# ---------------------------------------------------------------- shell rc block (shared by installer + integrity)

SHELL_BEGIN = '# >>> Claude Envlock managed entry >>>'
SHELL_END = '# <<< Claude Envlock managed entry <<<'
SHELL_FILES = ('.zprofile', '.zshrc')
SHELL_ALIASES = ('claude', 'claude-npm', 'claude-native', 'claude-check', 'claude-web')


def shell_lines(filename):
    lines = ['export PATH="$HOME/.claude-env/bin:$PATH"']
    if filename == '.zshrc':
        lines += ['alias {0}=\'"$HOME/.claude-env/bin/{0}"\''.format(n) for n in SHELL_ALIASES]
    return lines


def render_shell_block(filename):
    return SHELL_BEGIN + '\n' + '\n'.join(shell_lines(filename)) + '\n' + SHELL_END


def short_path(path):
    text, home = str(path), str(Path.home())
    return '~' + text[len(home):] if text.startswith(home + '/') else text
