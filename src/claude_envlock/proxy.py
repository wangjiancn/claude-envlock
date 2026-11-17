"""Proxy environment, the pre-launch gate, and the exit-IP check.

- gate(): sends only `CONNECT claude.ai:443` to the local proxy, then verifies the origin's TLS
  certificate. No HTTP request.
- exit_trace(): only when an exit-IP allowlist is set. One cookie-free GET to
  https://claude.ai/cdn-cgi/trace (Cloudflare's public diagnostics endpoint).
Neither ever sends a cookie, token, or prompt.
"""
import concurrent.futures
import ipaddress
import os
import socket
import ssl
import urllib.parse
import urllib.request

from .common import GATE_HOST, GATE_PORT, NO_PROXY_VALUE, NO_PROXY_VARS, PRIVACY_VARS, PROXY_VARS

MAX_HEADER_BYTES = 16384


def proxy_environment(cfg, base=None):
    """Return a copy of `base` that forces all HTTP(S) traffic through the local proxy."""
    env = dict(os.environ if base is None else base)
    for key in list(env):
        if key.lower() in ('http_proxy', 'https_proxy', 'all_proxy', 'no_proxy'):
            del env[key]
    env.update({key: cfg.proxy_url for key in PROXY_VARS})
    env.update({key: NO_PROXY_VALUE for key in NO_PROXY_VARS})
    env.update(PRIVACY_VARS)
    env['BROWSER'] = str(cfg.bin_dir / 'claude-web')
    env['PATH'] = str(cfg.bin_dir) + os.pathsep + env.get('PATH', '')
    return env


def _read_headers(sock):
    reply = b''
    while b'\r\n\r\n' not in reply:
        chunk = sock.recv(1024)
        if not chunk or len(reply) + len(chunk) > MAX_HEADER_BYTES:
            raise RuntimeError('Proxy CONNECT response was incomplete or too large.')
        reply += chunk
    return reply


def gate(cfg):
    """Raise unless the proxy tunnels to claude.ai:443 and the origin TLS handshake succeeds."""
    target = '{}:{}'.format(GATE_HOST, GATE_PORT).encode()
    with socket.create_connection((cfg.host, cfg.port), timeout=cfg.timeout) as sock:
        sock.settimeout(cfg.timeout)
        sock.sendall(b'CONNECT ' + target + b' HTTP/1.1\r\nHost: ' + target + b'\r\n\r\n')
        status = _read_headers(sock).split(b'\r\n', 1)[0].split()
        if len(status) < 2 or not status[0].startswith(b'HTTP/') or status[1] != b'200':
            raise RuntimeError('Proxy refused CONNECT to {}:{}.'.format(GATE_HOST, GATE_PORT))
        # Some proxies answer 200 before the upstream is reachable, so verify the origin's
        # certificate too. No HTTP request is sent over the tunnel.
        with ssl.create_default_context().wrap_socket(sock, server_hostname=GATE_HOST):
            pass


TRACE_URL = 'https://{}/cdn-cgi/trace'.format(GATE_HOST)


class _NoBypassProxy(urllib.request.ProxyHandler):
    # Ignore inherited proxy/bypass variables; always use the configured proxy.
    def proxy_open(self, req, proxy, kind):
        req.set_proxy(urllib.parse.urlsplit(proxy).netloc, kind)
        return None


def fetch_via_proxy(cfg, url, limit=65536):
    """GET `url` through the configured proxy. No cookie jar, so no cookies are ever sent."""
    opener = urllib.request.build_opener(_NoBypassProxy({'https': cfg.proxy_url}))
    with opener.open(url, timeout=cfg.timeout) as response:
        return response.read(limit).decode('utf-8')


def parse_trace(text):
    return dict(line.split('=', 1) for line in text.splitlines() if '=' in line)


def exit_trace(cfg):
    """Exit IP and country as seen by claude.ai's own edge.

    The request goes to claude.ai itself, so the proxy routes it with the same rule as real
    Claude traffic. That makes it far more reliable than third-party IP lookup sites.
    """
    trace = parse_trace(fetch_via_proxy(cfg, TRACE_URL, 4096))
    ipaddress.ip_address(trace.get('ip', ''))  # raises ValueError if missing or garbage
    return {'ip': trace['ip'], 'loc': trace.get('loc', '??')}


def mask_ip(ip):
    address = ipaddress.ip_address(ip)
    if address.version == 4:
        return '.'.join(ip.split('.')[:2] + ['x', 'x'])
    return ':'.join(address.exploded.split(':')[:3]) + ':…'


def exit_ip_problems(cfg):
    """[] if the allowlist is empty or the exit IP is allowed; otherwise one human-readable problem."""
    if not cfg.allowed_exit_ips:
        return []
    try:
        trace = exit_trace(cfg)
    except Exception as exc:
        return ['Could not verify the exit IP via claude.ai ({})'.format(type(exc).__name__)]
    if cfg.exit_ip_allowed(trace['ip']):
        return []
    return ['Exit IP {} ({}) is not in CLAUDE_ENVLOCK_ALLOWED_EXIT_IPS'.format(mask_ip(trace['ip']), trace['loc'])]


def country_diagnostics(cfg):
    """Best-effort third-party country lookups. Diagnostic only; never used as a gate."""
    sources = (('Cloudflare', 'https://www.cloudflare.com/cdn-cgi/trace', lambda t: parse_trace(t).get('loc', '')),
               ('ipinfo', 'https://ipinfo.io/country', str.strip))
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(sources)) as pool:
        tasks = {name: (pool.submit(fetch_via_proxy, cfg, url), parse) for name, url, parse in sources}
        for name, (task, parse) in tasks.items():
            try:
                value = parse(task.result())
                results[name] = value if len(value) == 2 and value.isalpha() else 'unknown'
            except Exception:
                results[name] = 'unavailable'
    return results
