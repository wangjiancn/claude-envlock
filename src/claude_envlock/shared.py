"""Shared settings files: claude-envlock owns only its own keys there, never the whole file.

Used for ~/.claude/settings.json ("claude") and VS Code's user settings.json ("vscode").

- Install always writes our keys and keeps everything else. It never refuses because someone else
  edited the file. If one of our keys was edited by hand, the edit is replaced, reported, and a copy
  of the file is saved in <root>/backups first.
- Rollback puts back only our keys (their values from before claude-envlock first wrote them). If the
  file is byte-for-byte what we last wrote and nobody else ever touched it, the original bytes are
  restored exactly.

Manifest record (kind "keys"):
  format           "claude" | "vscode"
  existed, mode    whether/how the file existed before the first install
  original         base64 of the file before the first install (None if it didn't exist)
  pristine         True while nobody but claude-envlock has changed the file since the first install
  installed_sha256 hash of what claude-envlock last wrote
  original_values  {key: value before we first wrote it, or None if it was absent}
"""
import base64
import json
from pathlib import Path

from . import jsonc
from .common import atomic_write, sha256

KIND = 'keys'
WRAPPER = 'claudeCode.claudeProcessWrapper'
VARIABLES = 'claudeCode.environmentVariables'


def _variables(data):
    variables = data.get(VARIABLES, [])
    if not isinstance(variables, list) or any(not isinstance(x, dict) or 'name' not in x for x in variables):
        raise ValueError('VS Code "{}" has an unexpected format.'.format(VARIABLES))
    return variables


def parse(fmt, text):
    if fmt == 'claude':
        data = json.loads(text) if text.strip() else {}
        if not isinstance(data, dict) or not isinstance(data.get('env', {}), dict):
            raise ValueError('~/.claude/settings.json is not a valid settings object; not overwriting it.')
        return data
    data = jsonc.loads(text) if text.strip() else {}
    if not isinstance(data, dict):
        raise ValueError('VS Code settings.json is not a JSON object; not overwriting it.')
    _variables(data)
    return data


def read(fmt, text, keys):
    """{key: current value, or None if absent} for the given keys."""
    data = parse(fmt, text)
    if fmt == 'claude':
        env = data.get('env', {})
        return {k: env.get(k) for k in keys}
    values = {x['name']: x.get('value') for x in _variables(data)}
    values[WRAPPER] = data.get(WRAPPER)
    return {k: values.get(k) for k in keys}


def write(fmt, text, values):
    """Return `text` with each key set to its value (None = remove). Everything else is kept."""
    if read(fmt, text, values) == values:
        return text
    data = parse(fmt, text)
    if fmt == 'claude':
        env = dict(data.get('env', {}))
        for key, value in values.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        if env:
            data['env'] = env
        else:
            data.pop('env', None)
        return json.dumps(data, ensure_ascii=False, indent=2) + '\n'

    changes, removals = {}, []
    if WRAPPER in values:
        if values[WRAPPER] is not None:
            changes[WRAPPER] = values[WRAPPER]
        elif WRAPPER in data:
            removals.append(WRAPPER)
    names = {k: v for k, v in values.items() if k != WRAPPER}
    if names:
        variables, seen = [], set()
        for item in _variables(data):
            name = item['name']
            if name not in names:
                variables.append(item)
            elif name not in seen:  # update in place; duplicates of our names collapse into one
                seen.add(name)
                if names[name] is not None:
                    variables.append(dict(item, value=names[name]))
        variables += [{'name': k, 'value': v} for k, v in names.items() if v is not None and k not in seen]
        if variables:
            changes[VARIABLES] = variables
        elif VARIABLES in data:
            removals.append(VARIABLES)
    new = jsonc.update(text if text.strip() else '{}\n', changes) if changes else text
    if removals:
        new = jsonc.remove(new, removals)
    expected = dict(data)
    expected.update(changes)
    for key in removals:
        expected.pop(key)
    if jsonc.loads(new) != expected:
        raise ValueError('VS Code JSONC edit failed verification; nothing written.')
    return new


def label(fmt, key):
    if fmt == 'claude':
        return 'env.' + key
    return key if key == WRAPPER else 'environment variable ' + key


def show(value):
    return '(unset)' if value is None else value


def plan_update(path, fmt, record, desired, previous):
    """Work out the new file text and manifest record.

    desired:  {key: value} claude-envlock wants now.
    previous: {key: value} claude-envlock wrote last time ({} on a first install).
    Returns (new_text, record, replaced) where `replaced` lists hand edits being overwritten.
    """
    path = Path(path)
    if path.is_symlink():
        raise RuntimeError('Refusing to replace a symlink: {}'.format(path))
    old = path.read_bytes() if path.exists() else None
    text = old.decode() if old is not None else ''
    if record is None:
        record = {'kind': KIND, 'format': fmt, 'existed': old is not None,
                  'mode': (path.stat().st_mode & 0o777) if old is not None else None,
                  'original': base64.b64encode(old).decode() if old is not None else None,
                  'pristine': True, 'original_values': {}}
    elif record.get('kind') != KIND:
        # Whole-file record from an older release: recover our keys' original values from the saved copy.
        original = base64.b64decode(record['original']).decode() if record['existed'] else ''
        record = {'kind': KIND, 'format': fmt, 'existed': record['existed'], 'mode': record['mode'],
                  'original': record['original'],
                  'pristine': old is not None and sha256(old) == record['installed_sha256'],
                  'original_values': read(fmt, original, previous)}
    else:
        record = json.loads(json.dumps(record))
        record['pristine'] = bool(record['pristine'] and old is not None
                                  and sha256(old) == record['installed_sha256'])

    originals = record['original_values']
    current = read(fmt, text, set(desired) | set(originals) | set(previous))
    updates = {}
    for key in sorted((set(originals) | set(previous)) - set(desired)):
        value = originals.pop(key, None)
        if current[key] is not None and current[key] == previous.get(key):  # still our value: put the original back
            updates[key] = value
    for key in desired:
        if key not in originals:
            originals[key] = current[key]
    replaced = ['{}: {} -> {}'.format(label(fmt, k), show(current[k]), desired[k]) for k in desired
                if k in previous and current[k] not in (previous[k], desired[k])]
    updates.update(desired)
    new = write(fmt, text, updates)
    record['installed_sha256'] = sha256(new.encode())
    return new, record, replaced


def restore(path, record):
    """Roll back one shared file. Never refuses because of unrelated edits."""
    path = Path(path)
    old = path.read_bytes() if path.exists() else None
    if record['pristine'] and old is not None and sha256(old) == record['installed_sha256']:
        if record['existed']:
            atomic_write(path, base64.b64decode(record['original']), record['mode'])
        else:
            path.unlink()
        return
    text = old.decode() if old is not None else ''
    new = write(record['format'], text, record['original_values'])
    if not record['existed'] and parse(record['format'], new) == {}:
        path.unlink(missing_ok=True)
    elif old is None or new != text:
        mode = (path.stat().st_mode & 0o777) if old is not None else (record['mode'] or 0o600)
        atomic_write(path, new.encode(), mode)
