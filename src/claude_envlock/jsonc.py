"""Minimal top-level JSONC edits; preserve comments and unrelated text."""
import json


def loads(text):
    parts = []
    i = 0
    while i < len(text):
        if text[i] == '"':
            end = string_end(text, i)
            parts.append(text[i:end])
            i = end
        elif text.startswith('//', i) or text.startswith('/*', i):
            i = skip(text, i)
            parts.append(' ')
        elif text[i] == ',' and text[skip(text, i + 1):skip(text, i + 1) + 1] in (']', '}'):
            i += 1
        else:
            parts.append(text[i])
            i += 1
    return json.loads(''.join(parts))


def skip(s, i):
    while i < len(s):
        if s[i].isspace():
            i += 1
        elif s.startswith('//', i):
            j = s.find('\n', i)
            i = len(s) if j < 0 else j + 1
        elif s.startswith('/*', i):
            j = s.find('*/', i + 2)
            if j < 0:
                raise ValueError('Unterminated JSONC comment')
            i = j + 2
        else:
            break
    return i


def string_end(s, i):
    quote = s[i]
    i += 1
    while i < len(s):
        if s[i] == '\\':
            i += 2
        elif s[i] == quote:
            return i + 1
        else:
            i += 1
    raise ValueError('Unterminated JSONC string')


def value_end(s, i):
    if s[i] in '\"\'':
        return string_end(s, i)
    if s[i] not in '[{':
        j = i
        while j < len(s) and s[j] not in ',}\r\n' and not s.startswith('//', j) and not s.startswith('/*', j):
            j += 1
        return len(s[:j].rstrip())
    depth = 0
    while i < len(s):
        i = skip(s, i)
        if i >= len(s):
            break
        if s[i] in '\"\'':
            i = string_end(s, i)
            continue
        if s[i] in '[{':
            depth += 1
        elif s[i] in ']}':
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError('Unterminated JSONC value')


def update(text, changes):
    start = skip(text, 0)
    if text[start:start + 1] != '{':
        raise ValueError('Expected settings object')
    i = start + 1
    edits = []
    remaining = dict(changes)
    seen = set()
    while True:
        i = skip(text, i)
        if text[i:i + 1] == '}':
            break
        end = string_end(text, i)
        key = json.loads(text[i:end])
        if key in seen:
            raise ValueError('Duplicate settings key: ' + key)
        seen.add(key)
        i = skip(text, end)
        if text[i] != ':':
            raise ValueError('Expected colon')
        begin = skip(text, i + 1)
        end = value_end(text, begin)
        if key in remaining:
            edits.append((begin, end, json.dumps(remaining.pop(key), ensure_ascii=False)))
        i = skip(text, end)
        if text[i] == ',':
            i += 1
        elif text[i] != '}':
            raise ValueError('Expected comma')
    if remaining:
        added = ',\n'.join('  ' + json.dumps(k) + ': ' + json.dumps(v, ensure_ascii=False) for k, v in remaining.items())
        edits.append((start + 1, start + 1, '\n' + added + (',' if seen else '') + '\n'))
    for a, b, value in sorted(edits, reverse=True):
        text = text[:a] + value + text[b:]
    return text
