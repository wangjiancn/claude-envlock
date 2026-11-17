import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from claude_envlock import launchers

from .support import closed_port, deploy_runtime, make_config, write_executable


class CliTests(unittest.TestCase):
    def test_cli_never_execs_when_preflight_fails(self):
        with mock.patch.object(launchers, 'resolve_cli', return_value='/fake/claude'), \
                mock.patch.object(launchers, 'preflight', side_effect=RuntimeError('blocked')), \
                mock.patch.object(launchers.os, 'execve') as execute:
            with self.assertRaises(RuntimeError):
                launchers.run_cli(make_config(), ['--version'])
            execute.assert_not_called()

    def test_cli_preserves_arguments_and_sets_proxy_and_timezone(self):
        cfg = make_config(cli_timezone='Asia/Jakarta')
        with mock.patch.object(launchers, 'resolve_cli', return_value='/fake/claude'), \
                mock.patch.object(launchers, 'preflight'), mock.patch.object(launchers.os, 'execve') as execute:
            launchers.run_cli(cfg, ['prompt with spaces', '--x', '中文'])
        target, argv, env = execute.call_args.args
        self.assertEqual(argv, ['/fake/claude', 'prompt with spaces', '--x', '中文'])
        self.assertEqual(env['HTTPS_PROXY'], 'http://127.0.0.1:7890')
        self.assertEqual(env['TZ'], 'Asia/Jakarta')
        self.assertEqual(env['CLAUDE_ENVLOCK_ACTIVE'], '1')

    def test_timezone_override_does_not_mutate_base(self):
        base = {'TZ': 'Asia/Shanghai', 'KEEP': 'yes'}
        env = launchers.cli_environment(make_config(cli_timezone='Asia/Jakarta'), base)
        self.assertEqual(env['TZ'], 'Asia/Jakarta')
        self.assertEqual(base['TZ'], 'Asia/Shanghai')
        self.assertEqual(env['KEEP'], 'yes')

    def test_default_timezone_overrides_inherited_value(self):
        env = launchers.cli_environment(make_config(), {'TZ': 'Asia/Shanghai'})
        self.assertEqual(env['TZ'], 'Asia/Jakarta')

    def test_resolve_cli_rejects_recursion(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            shim = write_executable(root / 'bin' / 'claude', '#!/bin/sh\n')
            with self.assertRaises(RuntimeError):
                launchers.resolve_cli(make_config(root=root, cli_candidates=(str(shim),)))

    def test_unknown_variant_fails_clearly(self):
        with self.assertRaises(RuntimeError):
            launchers.resolve_cli(make_config(), 'npm')

    def test_deployed_shim_blocks_when_proxy_port_is_closed(self):
        # End to end through the real shim (#!/usr/bin/python3 -IB) and deployed lib.
        with tempfile.TemporaryDirectory() as folder, closed_port() as port:
            root = Path(folder).resolve()
            marker = root / 'executed'
            fake = write_executable(root / 'real-claude', '#!/bin/sh\ntouch "{}"\n'.format(marker))
            cfg = make_config(root=root, port=port, timeout=1, cli_candidates=(str(fake),))
            shim = deploy_runtime(root, cfg.to_json())
            result = subprocess.run([str(shim), '--version'], capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('[claude-envlock]', result.stderr)
            self.assertFalse(marker.exists())


class IdeTests(unittest.TestCase):
    def _extension_binary(self, home, folder='anthropic.claude-code-1.0.0'):
        return write_executable(home / '.vscode/extensions' / folder / 'resources/native-binary/claude',
                                '#!/bin/sh\nexit 0\n')

    def test_ide_binary_receives_timezone(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder).resolve()
            binary = self._extension_binary(home)
            with mock.patch.object(launchers.Path, 'home', return_value=home), \
                    mock.patch.object(launchers, 'preflight'), mock.patch.object(launchers.os, 'execve') as execute:
                launchers.run_cli(make_config(cli_timezone='Asia/Jakarta'), [str(binary), '--version'], ide=True)
            self.assertEqual(execute.call_args.args[2]['TZ'], 'Asia/Jakarta')

    def test_ide_rejects_untrusted_executable(self):
        with self.assertRaises(RuntimeError):
            launchers.run_cli(make_config(), ['/bin/echo', 'x'], ide=True)

    def test_ide_rejects_lookalike_extension(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder).resolve()
            binary = self._extension_binary(home, 'evil.anthropic.claude-code-1.0.0')
            with self.assertRaises(RuntimeError):
                launchers.verify_ide_binary(str(binary), home=home)


class WebTests(unittest.TestCase):
    def test_rejects_credentials_non_https_and_flags(self):
        for url in ['https://secret@host/', 'file:///tmp/a', 'http://public.example/', '--flag']:
            with self.assertRaises(ValueError):
                launchers.open_web(make_config(), [url])

    def test_allows_local_http_callback(self):
        self.assertEqual(launchers.validate_url('http://localhost:54545/cb'), 'http://localhost:54545/cb')

    def test_browser_does_not_inherit_cli_timezone(self):
        env = launchers.browser_environment(make_config(cli_timezone='Asia/Jakarta'),
                                            {'TZ': 'Asia/Jakarta', 'CLAUDE_ENVLOCK_ACTIVE': '1'})
        self.assertNotIn('TZ', env)
        self.assertEqual(env['HTTPS_PROXY'], 'http://127.0.0.1:7890')

    def test_chrome_flags_force_proxy_and_block_leaks(self):
        cmd = launchers.chrome_command(make_config(), 'https://claude.ai/')
        self.assertIn('--proxy-server=http://127.0.0.1:7890', cmd)
        self.assertIn('--force-webrtc-ip-handling-policy=disable_non_proxied_udp', cmd)
        self.assertIn('--disable-quic', cmd)
        # Chrome shows an "unsupported command-line flag" warning bar for these; never use them.
        unsupported = ('--host-resolver-rules', '--no-sandbox', '--disable-web-security', '--ignore-certificate-errors')
        self.assertFalse([x for x in cmd if x.startswith(unsupported)])


if __name__ == '__main__':
    unittest.main()
