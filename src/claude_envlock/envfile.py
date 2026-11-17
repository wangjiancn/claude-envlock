"""~/.claude-env/claude.env: the single source of truth.

The format is a strict subset of shell syntax, so scripts can `source` it:

    export KEY="value"      # or KEY=value with a safe bare value
    unset NAME [NAME ...]

The installer reads the CLAUDE_ENVLOCK_* settings and extra variables from it, then regenerates the
whole file (including the derived proxy lines) together with every other managed file.
"""
import re

from .common import DEFAULT_PORT, DEFAULT_TIMEZONE, SOCKS_VARS
from .config import RESERVED_ENV

FILENAME = 'claude.env'
SETTING_KEYS = ('CLAUDE_ENVLOCK_PORT', 'CLAUDE_ENVLOCK_TIMEZONE', 'CLAUDE_ENVLOCK_ALLOWED_EXIT_IPS',
                'CLAUDE_ENVLOCK_ON_MISMATCH')
ASSIGN = re.compile(r'(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(?:"([^"\\$`]*)"|([A-Za-z0-9_./:,@%+=-]*))'
                    r'\s*(?:#.*)?\Z')
UNSET = re.compile(r'unset(?:\s+[A-Za-z_][A-Za-z0-9_]*)+\s*\Z')

HEADER = """\
# claude-envlock: single source of truth for Claude's environment.
#
#   1. Edit the settings or extra variables below.
#   2. Apply: run ./install.sh from the claude-envlock repo.
#      Until you apply, every Claude launch shows a Block/Continue prompt.
#
# Scripts can load the same environment:   source ~/.claude-env/claude.env
"""


def parse(text):
    """Return {key: value}. Raise ValueError (with the line number) on anything unexpected."""
    values = {}
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith('#') or UNSET.match(line):
            continue
        match = ASSIGN.match(line)
        if not match:
            raise ValueError('{} line {}: expected KEY="value"'.format(FILENAME, number))
        key = match.group(1)
        if key in values:
            raise ValueError('{} line {}: duplicate key {}'.format(FILENAME, number, key))
        values[key] = match.group(2) if match.group(2) is not None else match.group(3)
    return values


LEGACY_PREFIX = 'CLAUDE_SAFE_'  # setting names used before the rename to claude-envlock


def settings_from_values(values):
    values = dict(values)
    for key in [k for k in values if k.startswith(LEGACY_PREFIX)]:
        values.setdefault('CLAUDE_ENVLOCK_' + key[len(LEGACY_PREFIX):], values.pop(key))
    unknown = [k for k in values if k.startswith('CLAUDE_ENVLOCK_') and k not in SETTING_KEYS]
    if unknown:
        raise ValueError('Unknown setting(s) in {}: {}'.format(FILENAME, ', '.join(unknown)))
    port = values.get('CLAUDE_ENVLOCK_PORT', str(DEFAULT_PORT))
    if not port.isdigit():
        raise ValueError('CLAUDE_ENVLOCK_PORT must be a number.')
    return {
        'port': int(port),
        'cli_timezone': values.get('CLAUDE_ENVLOCK_TIMEZONE') or DEFAULT_TIMEZONE,
        'allowed_exit_ips': tuple(x for x in re.split(r'[\s,]+', values.get('CLAUDE_ENVLOCK_ALLOWED_EXIT_IPS', ''))
                                  if x),
        'on_mismatch': values.get('CLAUDE_ENVLOCK_ON_MISMATCH') or 'prompt',
        'extra_env': {k: v for k, v in values.items()
                      if not k.startswith('CLAUDE_ENVLOCK_') and k not in RESERVED_ENV},
    }


def settings_from_config(cfg):
    return {'port': cfg.port, 'cli_timezone': cfg.cli_timezone, 'allowed_exit_ips': cfg.allowed_exit_ips,
            'on_mismatch': cfg.on_mismatch, 'extra_env': dict(cfg.extra_env)}


def hand_edited_generated_keys(values, previous_env, new_env):
    """Generated lines are rewritten on apply. Flag ones the user changed by hand, so edits aren't lost silently."""
    return [k for k, v in values.items()
            if k in RESERVED_ENV and v not in (previous_env.get(k), new_env.get(k))]


def render(cfg):
    def line(key, value):
        return 'export {}="{}"'.format(key, value)

    generated = {k: v for k, v in cfg.managed_env().items() if k not in cfg.extra_env and k not in SOCKS_VARS}
    parts = [
        HEADER,
        '# ---- Settings ----',
        '# Local HTTP proxy port (127.0.0.1).',
        line('CLAUDE_ENVLOCK_PORT', cfg.port),
        '# IANA timezone for Claude processes only (default {}; China timezones are not allowed).'.format(
            DEFAULT_TIMEZONE),
        line('CLAUDE_ENVLOCK_TIMEZONE', cfg.cli_timezone),
        '# Allowed exit IPs / CIDR ranges, space-separated, checked via claude.ai at launch. Empty = no check.',
        line('CLAUDE_ENVLOCK_ALLOWED_EXIT_IPS', ' '.join(cfg.allowed_exit_ips)),
        '# On a change or a disallowed exit IP: "prompt" (Block/Continue popup) or "block".',
        line('CLAUDE_ENVLOCK_ON_MISMATCH', cfg.on_mismatch),
        '',
        '# ---- Extra variables passed to Claude (add your own export lines here) ----',
    ]
    parts += [line(k, v) for k, v in sorted(cfg.extra_env.items())]
    parts += ['', '# ---- Generated from the settings above. Do not edit; rewritten on apply. ----']
    parts += [line(k, v) for k, v in generated.items()]
    parts += ['unset ' + ' '.join(SOCKS_VARS), '']
    return '\n'.join(str(p) for p in parts)
