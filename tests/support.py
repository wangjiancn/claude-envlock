"""Test helpers: a fake local proxy and isolated HOME / deployment directories."""
import contextlib
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading

from claude_envlock.config import Config
from claude_envlock.installer import PACKAGE_DIR, RUNTIME_MODULES, SHIM

REPO = Path(__file__).resolve().parent.parent


class FakeProxy:
    """Accepts one CONNECT per connection, records it, replies with `status`."""

    def __init__(self, status=b'200 Connection established'):
        self.status = status
        self.requests = []

    def __enter__(self):
        self.sock = socket.socket()
        self.sock.bind(('127.0.0.1', 0))
        self.sock.listen()
        self.sock.settimeout(0.1)
        self.port = self.sock.getsockname()[1]
        self.stopped = False
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()
        return self

    def _serve(self):
        while not self.stopped:
            try:
                client, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with client:
                data = b''
                while b'\r\n\r\n' not in data:
                    block = client.recv(1024)
                    if not block:
                        break
                    data += block
                self.requests.append(data)
                client.sendall(b'HTTP/1.1 ' + self.status + b'\r\n\r\n')

    def __exit__(self, *exc):
        self.stopped = True
        self.sock.close()
        self.thread.join(2)


@contextlib.contextmanager
def closed_port():
    """A bound but non-listening port: connections are refused, with no race."""
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    try:
        yield sock.getsockname()[1]
    finally:
        sock.close()


def make_config(root='/nonexistent/claude-env', **overrides):
    values = dict(root=Path(root), port=7890)
    values.update(overrides)
    return Config(**values)


def write_executable(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o700)
    return path


def deploy_runtime(root, cfg_json):
    """Lay out <root>/lib + <root>/bin like the installer does, without touching HOME."""
    lib = root / 'lib' / 'claude_envlock'
    lib.mkdir(parents=True)
    for module in RUNTIME_MODULES:
        shutil.copy(str(PACKAGE_DIR / module), str(lib / module))
    (root / 'config.json').write_text(cfg_json)
    return write_executable(root / 'bin' / 'claude', SHIM)


class IsolatedHome:
    """Temporary HOME with a fake Claude CLI, for running the real installer end to end."""

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name).resolve()
        self.claude = write_executable(self.home / 'tools' / 'claude', '#!/bin/sh\nexit 0\n')
        self.root = self.home / '.claude-env'
        self.app = self.home / 'Applications' / 'Claude Envlock.app'
        self.claude_settings = self.home / '.claude' / 'settings.json'
        self.vscode_settings = self.home / 'Library/Application Support/Code/User/settings.json'
        self.env = dict(os.environ, HOME=str(self.home))
        return self

    def __exit__(self, *exc):
        self._tmp.cleanup()

    def install(self, *extra, claude=True, check_timezone=False):
        args = [sys.executable, '-I', str(REPO / 'install.py'), '--app-dir', str(self.app)]
        if claude:
            args += ['--claude', str(self.claude)]
        if not check_timezone:  # the real check needs the network; it is unit-tested separately
            args.append('--skip-timezone-check')
        return subprocess.run(args + list(extra), env=self.env, text=True, capture_output=True)

    def rollback(self, *extra):
        return subprocess.run([str(self.root / 'bin' / 'claude-rollback')] + list(extra),
                              env=self.env, text=True, capture_output=True)
