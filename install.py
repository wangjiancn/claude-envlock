#!/usr/bin/python3
"""Installer entry point. Usage: ./install.sh [--dry-run] [--port N] [--timezone Area/City] ..."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))
from claude_envlock.installer import main  # noqa: E402

if __name__ == '__main__':
    sys.exit(main())
