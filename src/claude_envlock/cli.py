"""Entry-point dispatcher. Every command in <root>/bin is the same shim; its name picks the action."""
from pathlib import Path
import subprocess
import sys

from . import integrity
from .config import Config
from .launchers import open_web, run_cli
from .proxy import country_diagnostics, exit_trace, gate

CLI_KINDS = {'claude': 'default', 'claude-npm': 'npm', 'claude-native': 'native'}
CHECK_USAGE = 'Usage: claude-check [--country]'


def check(cfg, args):
    """Report everything preflight checks, without prompting. Exit 1 on any problem (script-friendly)."""
    if args not in ([], ['--country']):
        raise ValueError(CHECK_USAGE)
    gate(cfg)
    print('OK    proxy {} tunnels to claude.ai:443 with a valid TLS certificate'.format(cfg.proxy_url))
    problems = []
    try:
        trace = exit_trace(cfg)
    except Exception as exc:
        trace = None
        line = 'Could not read the exit IP via claude.ai ({})'.format(type(exc).__name__)
        print(('FAIL  ' if cfg.allowed_exit_ips else 'INFO  ') + line)
        if cfg.allowed_exit_ips:
            problems.append(line)
    if trace:
        if not cfg.allowed_exit_ips:
            status = 'INFO ', 'allowlist not set'
        elif cfg.exit_ip_allowed(trace['ip']):
            status = 'OK   ', 'allowed'
        else:
            status = 'FAIL ', 'NOT in CLAUDE_ENVLOCK_ALLOWED_EXIT_IPS'
            problems.append('exit IP not allowed')
        print('{} exit IP via claude.ai: {} ({}) - {}'.format(status[0], trace['ip'], trace['loc'], status[1]))
    drift = integrity.verify(cfg)
    for item in drift:
        print('FAIL  ' + item)
    if not drift:
        print('OK    live config matches claude.env')
    if args == ['--country']:
        result = country_diagnostics(cfg)
        print('INFO  third-party lookups (may route differently from Claude): '
              + ', '.join('{}={}'.format(k, v) for k, v in result.items()))
    if problems or drift:
        raise RuntimeError('{} problem(s) found.'.format(len(problems) + len(drift)))


def _alert(message):
    if sys.platform == 'darwin':
        script = 'display alert "Claude Envlock" message "{}" as critical'.format(message)
        subprocess.run(['/usr/bin/osascript', '-e', script],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main(root, argv=None):
    argv = sys.argv if argv is None else argv
    name, args = Path(argv[0]).name, list(argv[1:])
    if name == 'claude-rollback':
        from .rollback import main as rollback
        return rollback(root, args)
    try:
        cfg = Config.load(root)
        if name in ('claude-check', 'claude-gate'):
            check(cfg, args)
        elif name == 'claude-web':
            open_web(cfg, args)
        elif name == 'claude-ide-wrapper':
            run_cli(cfg, args, ide=True)
        elif name in CLI_KINDS:
            run_cli(cfg, args, CLI_KINDS[name])
        else:
            raise ValueError('Unknown entry point: ' + name)
    except Exception as exc:
        # Never print raw network errors or URLs: OAuth URLs can carry secrets.
        if isinstance(exc, (ValueError, RuntimeError)):
            message = str(exc)
        else:
            message = 'Proxy or configuration unavailable ({}); blocked. Run claude-check.'.format(
                type(exc).__name__)
        print('[claude-envlock] ' + message, file=sys.stderr)
        if name == 'claude-web' and not message.startswith('Blocked'):
            _alert('Proxy or launch check failed. Run claude-check in Terminal for details.')
        return 1
    return 0
