"""Launch Claude CLI, the VS Code extension binary, and the dedicated Chrome profile.

Every launcher runs the proxy gate first. If the gate fails, nothing is executed.
"""
import os
from pathlib import Path
import subprocess
import urllib.parse

from . import integrity, prompt
from .common import ACTIVE_FLAG
from .proxy import exit_ip_problems, gate, proxy_environment

LOCAL_HOSTS = ('localhost', '127.0.0.1', '::1')
IDE_EXTENSION_PREFIX = 'anthropic.claude-code-'


def preflight(cfg):
    """Run before every launch.

    A proxy failure always blocks. Config drift or a disallowed exit IP asks the user
    (Block/Continue), or blocks outright if CLAUDE_ENVLOCK_ON_MISMATCH="block".
    """
    problems = integrity.verify(cfg)
    gate(cfg)
    problems += exit_ip_problems(cfg)
    if problems:
        prompt.confirm(cfg, problems)


def cli_environment(cfg, base=None):
    env = proxy_environment(cfg, base)
    env.update(cfg.extra_env)
    if cfg.cli_timezone:
        env['TZ'] = cfg.cli_timezone
    return env


def browser_environment(cfg, base=None):
    env = proxy_environment(cfg, base)
    # OAuth may start the browser from a CLI whose TZ was overridden.
    # Keep the browser on the real system timezone.
    env.pop('TZ', None)
    return env


def resolve_cli(cfg, kind='default'):
    """Return the first executable original Claude CLI. Never returns one of our own shims."""
    if kind == 'default':
        candidates = cfg.cli_candidates
    elif kind in cfg.cli_variants:
        candidates = (cfg.cli_variants[kind],)
    else:
        raise RuntimeError('No "{}" Claude CLI is configured. Re-run the installer.'.format(kind))
    root = cfg.root.resolve()
    for candidate in candidates:
        path = Path(candidate)
        if path.is_file() and os.access(str(path), os.X_OK):
            resolved = path.resolve()
            if resolved == root or root in resolved.parents:
                raise RuntimeError('Configured Claude CLI points back to claude-envlock (recursion).')
            return str(path)
    raise RuntimeError('Original Claude CLI not found. Re-run the installer; the gate is never bypassed.')


def verify_ide_binary(target, home=None):
    """Accept only the `claude` binary shipped inside the official VS Code extension."""
    path = Path(target).resolve()
    extensions = ((home or Path.home()) / '.vscode' / 'extensions').resolve()
    try:
        relative = path.relative_to(extensions)
    except ValueError:
        relative = None
    if (relative is None or not relative.parts[0].startswith(IDE_EXTENSION_PREFIX)
            or path.name != 'claude' or not path.is_file() or not os.access(str(path), os.X_OK)):
        raise RuntimeError('IDE binary is not inside the official Claude Code extension; blocked.')
    return str(path)


def run_cli(cfg, args, kind='default', ide=False):
    if os.environ.get(ACTIVE_FLAG) == '1':
        raise RuntimeError('Wrapper recursion detected; blocked.')
    if ide:
        if not args:
            raise RuntimeError('The IDE did not pass the extension\'s Claude binary.')
        target, args = verify_ide_binary(args[0]), list(args[1:])
    else:
        target = resolve_cli(cfg, kind)
    preflight(cfg)
    env = cli_environment(cfg)
    env[ACTIVE_FLAG] = '1'
    os.execve(target, [target] + list(args), env)


def validate_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Only http(s) URLs without embedded credentials are accepted.')
    if parsed.scheme == 'http' and parsed.hostname not in LOCAL_HOSTS:
        raise ValueError('External URLs must use HTTPS.')
    return url


def chrome_command(cfg, url):
    return [
        cfg.chrome,
        '--user-data-dir=' + str(cfg.chrome_profile),
        # With a fixed HTTP proxy, Chrome sends hostnames to the proxy (CONNECT host:443) and does not
        # query DNS itself. (Verified with Chrome's net log; see docs/security-model.md.) So no
        # --host-resolver-rules: it's redundant, and Chrome shows an "unsupported flag" warning bar for it.
        '--proxy-server=' + cfg.proxy_url,
        '--force-webrtc-ip-handling-policy=disable_non_proxied_udp',
        '--disable-quic',
        '--no-first-run',
        '--no-default-browser-check',
        url,
    ]


def open_web(cfg, args):
    if len(args) > 1:
        raise ValueError('Usage: claude-web [https://URL]')
    url = validate_url(args[0] if args else 'https://claude.ai/')
    preflight(cfg)
    if not Path(cfg.chrome).is_file():
        raise RuntimeError('Google Chrome not found at {}.'.format(cfg.chrome))
    cfg.chrome_profile.mkdir(mode=0o700, exist_ok=True)
    # Flags apply on cold start only; a running instance keeps its original flags.
    subprocess.Popen(chrome_command(cfg, url), env=browser_environment(cfg),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
