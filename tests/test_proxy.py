from pathlib import Path
import ssl
import subprocess
import unittest
from unittest import mock

from claude_envlock import proxy
from claude_envlock.config import Config

from .support import FakeProxy, closed_port, make_config


class GateTests(unittest.TestCase):
    def test_sends_connect_only_and_verifies_claude_tls(self):
        with FakeProxy() as p, mock.patch.object(proxy.ssl, 'create_default_context') as context:
            proxy.gate(make_config(port=p.port, timeout=1))
            wrap = context.return_value.wrap_socket
            self.assertEqual(wrap.call_args.kwargs['server_hostname'], 'claude.ai')
        self.assertEqual(p.requests, [b'CONNECT claude.ai:443 HTTP/1.1\r\nHost: claude.ai:443\r\n\r\n'])

    def test_proxy_refusal_blocks(self):
        with FakeProxy(b'502 Bad Gateway') as p:
            with self.assertRaises(RuntimeError):
                proxy.gate(make_config(port=p.port, timeout=1))

    def test_tls_failure_blocks_even_after_connect_200(self):
        with FakeProxy() as p, mock.patch.object(proxy.ssl, 'create_default_context') as context:
            context.return_value.wrap_socket.side_effect = ssl.SSLError('invalid origin')
            with self.assertRaises(ssl.SSLError):
                proxy.gate(make_config(port=p.port, timeout=1))

    def test_closed_port_blocks(self):
        with closed_port() as port:
            with self.assertRaises(OSError):
                proxy.gate(make_config(port=port, timeout=1))


class EnvironmentTests(unittest.TestCase):
    def test_removes_external_bypass_and_socks(self):
        env = proxy.proxy_environment(make_config(), {
            'https_proxy': 'http://wrong:1', 'ALL_PROXY': 'socks5://wrong:2',
            'no_proxy': '*', 'NO_PROXY': '.anthropic.com', 'KEEP': 'yes'})
        self.assertEqual(env['https_proxy'], 'http://127.0.0.1:7890')
        self.assertEqual(env['HTTP_PROXY'], env['https_proxy'])
        self.assertNotIn('ALL_PROXY', env)
        self.assertEqual(env['NO_PROXY'], 'localhost,127.0.0.1,::1')
        self.assertEqual(env['KEEP'], 'yes')
        self.assertEqual(env['BROWSER'], '/nonexistent/claude-env/bin/claude-web')

    @unittest.skipUnless(Path('/usr/bin/curl').exists(), 'needs /usr/bin/curl')
    def test_explicit_client_fails_when_proxy_is_down(self):
        # No fallback to a direct connection once the proxy listener is gone.
        with closed_port() as port:
            env = proxy.proxy_environment(make_config(port=port))
            result = subprocess.run(['/usr/bin/curl', '--max-time', '2', '-sS', 'https://claude.ai/'],
                                    env=env, capture_output=True)
        self.assertNotEqual(result.returncode, 0)


class ConfigTests(unittest.TestCase):
    def test_rejects_non_loopback_host_and_bad_port(self):
        for overrides in ({'host': '0.0.0.0'}, {'port': 0}, {'port': 70000}, {'port': True}):
            with self.assertRaises(ValueError):
                make_config(**overrides)

    def test_rejects_unknown_empty_and_china_timezones(self):
        for name in ('Bad/Timezone', '', 'Asia/Shanghai', 'PRC', 'Asia/Urumqi', 'Asia/Hong_Kong', 'Asia/Macau'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                make_config(cli_timezone=name)

    def test_default_timezone(self):
        self.assertEqual(make_config().cli_timezone, 'Asia/Jakarta')
        self.assertEqual(make_config().managed_env()['TZ'], 'Asia/Jakarta')


class TimezoneMismatchTests(unittest.TestCase):
    def check(self, timezone, loc):
        trace = {'ip': '203.0.113.10', 'loc': loc}
        return proxy.timezone_mismatch(make_config(cli_timezone=timezone), trace)

    def test_matching_country_passes(self):
        self.assertIsNone(self.check('Asia/Jakarta', 'ID'))
        self.assertIsNone(self.check('Asia/Makassar', 'ID'))  # any zone of a multi-zone country
        self.assertIsNone(self.check('America/Chicago', 'US'))

    def test_other_country_is_reported(self):
        message = self.check('Asia/Jakarta', 'JP')
        self.assertIn('Asia/Tokyo', message)
        self.assertIn('203.0.x.x', message)
        self.assertNotIn('203.0.113.10', message)

    def test_unknown_country_is_reported(self):
        self.assertIn('no known timezone', self.check('Asia/Jakarta', 'XX'))

    def test_unreachable_trace_is_reported(self):
        with mock.patch.object(proxy, 'exit_trace', side_effect=OSError):
            self.assertIn('could not be checked', proxy.timezone_mismatch(make_config()))

    def test_json_round_trip(self):
        cfg = make_config(root='/tmp/x', cli_timezone='Asia/Jakarta', cli_candidates=('/a',))
        root = Path('/tmp/x')
        with mock.patch.object(Path, 'read_text', return_value=cfg.to_json()):
            self.assertEqual(Config.load(root), cfg)


if __name__ == '__main__':
    unittest.main()
