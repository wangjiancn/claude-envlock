#!/usr/bin/python3
"""Ask the managed Claude CLI to run smoke_probe.py, then verify the real tool-call evidence.

Uses your existing Claude login and model, so each run costs a little quota
(budget cap: $1, timeout: 120 s). The raw session log stays private in ~/.claude-env (mode 0600).
"""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

TIMEOUT = 120


def read_events(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def verify(path, expected_command):
    calls, outputs, results = [], [], []
    for event in read_events(path):
        content = event.get('message', {}).get('content', [])
        if event.get('type') == 'assistant':
            calls += [c for c in content if c.get('type') == 'tool_use']
        elif event.get('type') == 'user':
            outputs += [c for c in content if c.get('type') == 'tool_result']
        elif event.get('type') == 'result':
            results.append(event)
    if len(calls) != 1 or calls[0].get('name') != 'Bash' or calls[0].get('input', {}).get('command') != expected_command:
        raise RuntimeError('Expected exactly one Bash call running the probe; check the private log.')
    matching = [o for o in outputs if o.get('tool_use_id') == calls[0].get('id') and not o.get('is_error')]
    if len(matching) != 1:
        raise RuntimeError('No successful tool result for the probe call.')
    content = matching[0].get('content', '')
    if isinstance(content, list):
        content = ''.join(c.get('text', '') for c in content if c.get('type') == 'text')
    data = json.loads(content)
    if not data.get('pass') or not data.get('checks') or not all(v is True for v in data['checks'].values()):
        raise RuntimeError('Probe reported failing checks: ' + json.dumps(data.get('checks')))
    if not results or results[-1].get('is_error') or results[-1].get('subtype') != 'success':
        raise RuntimeError('Claude CLI session did not finish successfully.')
    return {'pass': True, 'checks': data['checks'], 'timezone': data.get('timezone'),
            'total_cost_usd': results[-1].get('total_cost_usd')}


def private_file(path):
    if path.is_symlink():
        raise RuntimeError('Refusing to write a log through a symlink: {}'.format(path))
    os.close(os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600))
    path.chmod(0o600)
    return path


def run_claude(root, command, log, err):
    prompt = ('Run exactly this one read-only Bash command, then briefly report its actual result: '
              + command + ' . Do not run any other command, read other files, edit files, inspect '
              'credentials, or launch agents. If it fails, report the failure without retrying.')
    cmd = [str(root / 'bin/claude'), '-p', prompt, '--output-format', 'stream-json', '--verbose',
           # --safe-mode disables hooks/plugins; no MCP servers; no Chrome integration.
           '--no-session-persistence', '--safe-mode', '--strict-mcp-config', '--mcp-config',
           '{"mcpServers":{}}', '--no-chrome', '--tools', 'Bash', '--allowedTools', 'Bash(' + command + ')',
           '--permission-mode', 'dontAsk', '--max-budget-usd', '1']
    with private_file(log).open('w') as out, private_file(err).open('w') as error:
        proc = subprocess.Popen(cmd, stdout=out, stderr=error)
        try:
            code = proc.wait(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            raise RuntimeError('Timed out after {} s; the model process was stopped.'.format(TIMEOUT))
    if code:
        raise RuntimeError('Claude CLI exited with {}; see the private log {}'.format(code, log))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-only', action='store_true', help='re-verify the last log without calling the model')
    args = parser.parse_args()
    root = Path.home() / '.claude-env'
    probe = Path(__file__).resolve().parent / 'smoke_probe.py'
    command = '/usr/bin/python3 ' + shlex.quote(str(probe))
    log, err = root / 'cli-smoke-last.jsonl', root / 'cli-smoke-last.stderr'
    if not args.report_only:
        run_claude(root, command, log, err)
    print(json.dumps(verify(log, command), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('Smoke test failed: {}'.format(exc), file=sys.stderr)
        sys.exit(1)
