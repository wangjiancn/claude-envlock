#!/usr/bin/python3
"""Read-only probe meant to run *inside* Claude Code's Bash tool.

Prints only selected, non-secret environment values. Never dumps the environment or reads credentials.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

PROXY_VARS = ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy')
NO_PROXY_VARS = ('NO_PROXY', 'no_proxy')
NODE_TZ = 'process.stdout.write(Intl.DateTimeFormat().resolvedOptions().timeZone)'


def node_timezone():
    node = shutil.which('node')
    if not node:
        return None
    result = subprocess.run([node, '-e', NODE_TZ], capture_output=True, text=True, timeout=10)
    return result.stdout.strip() if result.returncode == 0 else None


def main():
    root = Path.home() / '.claude-env'
    config = json.loads((root / 'config.json').read_text())
    expected_proxy = 'http://{}:{}'.format(config['host'], config['port'])
    selected = {name: os.environ.get(name) for name in PROXY_VARS + NO_PROXY_VARS}
    gate = subprocess.run([str(root / 'bin/claude-check')], capture_output=True, text=True, timeout=20)
    checks = {
        'proxy_vars_match': all(selected[k] == expected_proxy for k in PROXY_VARS),
        'no_external_bypass': all(selected[k] == 'localhost,127.0.0.1,::1' for k in NO_PROXY_VARS),
        'no_socks_override': not os.environ.get('ALL_PROXY') and not os.environ.get('all_proxy'),
        'browser_wrapper_inherited': os.environ.get('BROWSER') == str(root / 'bin/claude-web'),
        'claude_on_path_is_managed': shutil.which('claude') == str(root / 'bin/claude'),
        'proxy_connect_and_tls_pass': gate.returncode == 0,
    }
    timezone = config.get('cli_timezone')
    actual = node_timezone()
    if timezone:
        checks['tz_env_matches'] = os.environ.get('TZ') == timezone
        checks['node_intl_timezone_matches'] = actual == timezone
    report = {'checks': checks, 'selected_proxy_environment': selected,
              'timezone': {'TZ': os.environ.get('TZ'), 'Intl': actual, 'expected': timezone},
              'gate_output': gate.stdout.strip(), 'pass': all(checks.values())}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
