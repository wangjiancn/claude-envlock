"""Install Claude Code with Anthropic's official native installer, only through the verified proxy.

Repo-only module (not deployed). Steps:
1. gate(): the proxy must tunnel to claude.ai:443 with a valid certificate, or nothing is downloaded.
2. Download https://claude.ai/install.sh through the proxy. Redirects may only land on
   claude.ai / downloads.claude.ai over HTTPS.
3. Run it with bash, with every download forced through the proxy. Anthropic's installer verifies the
   SHA-256 of the binary it downloads against its release manifest.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.parse
import urllib.request

from .common import USER_AGENT
from .config import Config
from .proxy import NoBypassProxy, gate, proxy_environment

OFFICIAL_INSTALLER = 'https://claude.ai/install.sh'
TRUSTED_HOSTS = ('claude.ai', 'downloads.claude.ai')
CHANNEL = re.compile(r'(stable|latest|\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?)\Z')
MAX_SCRIPT_BYTES = 1 << 20
DOWNLOAD_TIMEOUT = 30


def native_path(home):
    return Path(home) / '.local' / 'bin' / 'claude'


def download_installer(cfg):
    opener = urllib.request.build_opener(NoBypassProxy({'https': cfg.proxy_url, 'http': cfg.proxy_url}))
    opener.addheaders = [('User-Agent', USER_AGENT)]
    with opener.open(OFFICIAL_INSTALLER, timeout=DOWNLOAD_TIMEOUT) as response:
        final = urllib.parse.urlsplit(response.geturl())
        if final.scheme != 'https' or final.hostname not in TRUSTED_HOSTS:
            raise RuntimeError('Claude installer redirected to an untrusted location ({}); stopped.'
                               .format(final.hostname))
        data = response.read(MAX_SCRIPT_BYTES + 1)
    if len(data) > MAX_SCRIPT_BYTES or not data.startswith(b'#!/bin/bash'):
        raise RuntimeError('Downloaded Claude installer does not look like the official script; stopped.')
    return data


def installer_environment(cfg, base=None):
    """Proxy-forced env for the official installer; keep the normal PATH and browser."""
    base = dict(os.environ if base is None else base)
    env = proxy_environment(cfg, base)
    env['PATH'] = base.get('PATH', '/usr/bin:/bin:/usr/sbin:/sbin')
    if 'BROWSER' in base:
        env['BROWSER'] = base['BROWSER']
    else:
        env.pop('BROWSER', None)
    return env


def install_claude(port, home, channel='stable', root=None):
    """Install Claude Code (native) into ~/.local/bin and return the binary path."""
    if not CHANNEL.match(channel):
        raise ValueError('Claude channel must be "stable", "latest", or a version like 2.1.0.')
    cfg = Config(root=Path(root or Path(home) / '.claude-env'), port=port)
    gate(cfg)
    script = download_installer(cfg)
    with tempfile.TemporaryDirectory(prefix='claude-envlock-') as folder:
        path = Path(folder) / 'install.sh'
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(script)
        result = subprocess.run(['/bin/bash', str(path), channel], env=installer_environment(cfg), cwd=folder)
    if result.returncode != 0:
        raise RuntimeError('Official Claude Code installer failed (exit {}).'.format(result.returncode))
    binary = native_path(home)
    if not binary.is_file() or not os.access(str(binary), os.X_OK):
        raise RuntimeError('Installer finished, but {} was not found.'.format(binary))
    return str(binary)
