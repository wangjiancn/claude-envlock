"""Ask the user whether to continue when something doesn't match. Default answer: Block.

Order: macOS popup → terminal prompt on /dev/tty → block. Every decision is appended to
<root>/decisions.log (mode 0600).
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

MAX_LINES = 8
DIALOG_TIMEOUT = 120
OSASCRIPT = '/usr/bin/osascript'
DIALOG = ('display dialog (item 1 of argv) with title "Claude Envlock" buttons {"Block", "Continue"} '
          'default button "Block" cancel button "Block" with icon caution giving up after %d' % DIALOG_TIMEOUT)


def build_message(problems):
    shown = ['• ' + p for p in problems[:MAX_LINES]]
    if len(problems) > MAX_LINES:
        shown.append('• …and {} more (run claude-check)'.format(len(problems) - MAX_LINES))
    return ('Claude Envlock found differences from claude.env:\n\n' + '\n'.join(shown)
            + '\n\nContinue launching Claude anyway?')


def ask_dialog(message):
    """True = Continue, False = Block/timeout, None = no GUI available."""
    if sys.platform != 'darwin' or not Path(OSASCRIPT).exists():
        return None
    # The message goes in as an argument, never spliced into the script, so it can't inject AppleScript.
    cmd = [OSASCRIPT, '-e', 'on run argv', '-e', DIALOG, '-e', 'return button returned of result',
           '-e', 'end run', message]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=DIALOG_TIMEOUT + 10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode == 0:
        return result.stdout.strip() == 'Continue'
    return False if '-128' in result.stderr else None  # -128 = user pressed Block


def ask_tty(message):
    try:
        with open('/dev/tty', 'r+') as tty:
            tty.write('\n[claude-envlock] ' + message + "\nType 'continue' to proceed, anything else blocks: ")
            tty.flush()
            return tty.readline().strip().lower() == 'continue'
    except OSError:
        return False


def record(root, problems, decision):
    path = Path(root) / 'decisions.log'
    entry = json.dumps({'time': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'decision': decision,
                        'problems': problems}, ensure_ascii=False)
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'a') as handle:
            handle.write(entry + '\n')
    except OSError:
        pass  # Logging must never turn a Block into a Continue, or crash the launcher.


def confirm(cfg, problems):
    """Return normally to continue; raise RuntimeError to block."""
    if cfg.on_mismatch == 'block':
        record(cfg.root, problems, 'blocked-by-policy')
        raise RuntimeError('Blocked (CLAUDE_ENVLOCK_ON_MISMATCH=block): ' + '; '.join(problems))
    message = build_message(problems)
    answer = ask_dialog(message)
    if answer is None:
        answer = ask_tty(message)
    record(cfg.root, problems, 'continued' if answer else 'blocked')
    if not answer:
        raise RuntimeError('Blocked: ' + '; '.join(problems))
