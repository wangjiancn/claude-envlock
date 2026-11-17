#!/bin/zsh
# Install or upgrade claude-envlock. Uses the macOS system Python; no pip/npm dependencies.
set -eu
exec /usr/bin/python3 -IB "${0:A:h}/install.py" "$@"
