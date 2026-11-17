"""--install-claude: official installer, only through the verified proxy."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from claude_envlock import bootstrap, installer

from .support import IsolatedHome, make_config, write_executable

SCRIPT = b'#!/bin/bash\necho official\n'


def fake_response(url, body=SCRIPT):
    response = mock.MagicMock()
    response.__enter__.return_value = response
    response.geturl.return_value = url
    response.read.return_value = body
    return response


def patch_opener(response):
    opener = mock.MagicMock()
    opener.open.return_value = response
    return mock.patch.object(bootstrap.urllib.request, 'build_opener', return_value=opener)


class DownloadTests(unittest.TestCase):
    def test_accepts_official_redirect(self):
        url = 'https://downloads.claude.ai/claude-code-releases/bootstrap.sh'
        with patch_opener(fake_response(url)):
            self.assertEqual(bootstrap.download_installer(make_config()), SCRIPT)

    def test_rejects_untrusted_redirect(self):
        for url in ('https://evil.example/install.sh', 'http://downloads.claude.ai/bootstrap.sh',
                    'https://claude.ai.evil.example/install.sh'):
            with patch_opener(fake_response(url)):
                with self.assertRaises(RuntimeError, msg=url):
                    bootstrap.download_installer(make_config())

    def test_rejects_non_script_content(self):
        with patch_opener(fake_response('https://claude.ai/install.sh', b'<html>captive portal</html>')):
            with self.assertRaises(RuntimeError):
                bootstrap.download_installer(make_config())

    def test_installer_env_forces_proxy_but_keeps_path(self):
        env = bootstrap.installer_environment(make_config(), {'PATH': '/usr/bin:/bin', 'ALL_PROXY': 'socks5://x:1'})
        self.assertEqual(env['HTTPS_PROXY'], 'http://127.0.0.1:7890')
        self.assertEqual(env['PATH'], '/usr/bin:/bin')
        self.assertNotIn('ALL_PROXY', env)
        self.assertNotIn('BROWSER', env)


class InstallClaudeTests(unittest.TestCase):
    def test_gate_failure_downloads_nothing(self):
        with mock.patch.object(bootstrap, 'gate', side_effect=OSError('refused')), \
                mock.patch.object(bootstrap, 'download_installer') as download:
            with self.assertRaises(OSError):
                bootstrap.install_claude(7890, '/tmp/nohome')
            download.assert_not_called()

    def test_rejects_bad_channel_before_network(self):
        with mock.patch.object(bootstrap, 'gate') as gate:
            with self.assertRaises(ValueError):
                bootstrap.install_claude(7890, '/tmp/nohome', channel='stable; rm -rf ~')
            gate.assert_not_called()

    def test_runs_official_script_with_channel_and_checks_binary(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)

            def fake_run(cmd, env, cwd):
                self.assertEqual(cmd[0], '/bin/bash')
                self.assertEqual(cmd[2], 'latest')
                self.assertEqual(Path(cmd[1]).read_bytes(), SCRIPT)
                self.assertEqual(env['https_proxy'], 'http://127.0.0.1:7890')
                write_executable(bootstrap.native_path(home), '#!/bin/sh\n')
                return subprocess.CompletedProcess(cmd, 0)

            with mock.patch.object(bootstrap, 'gate'), \
                    mock.patch.object(bootstrap, 'download_installer', return_value=SCRIPT), \
                    mock.patch.object(bootstrap.subprocess, 'run', side_effect=fake_run):
                path = bootstrap.install_claude(7890, home, 'latest')
            self.assertEqual(path, str(home / '.local/bin/claude'))

    def test_installer_failure_is_reported(self):
        with mock.patch.object(bootstrap, 'gate'), \
                mock.patch.object(bootstrap, 'download_installer', return_value=SCRIPT), \
                mock.patch.object(bootstrap.subprocess, 'run', return_value=subprocess.CompletedProcess([], 3)):
            with self.assertRaises(RuntimeError):
                bootstrap.install_claude(7890, '/tmp/nohome')


class InstallerFlagTests(unittest.TestCase):
    """Run installer.run() in-process with no Claude on the default paths."""

    def run_installer(self, h, *argv):
        homebrew = [str(h.home / 'no-brew/claude')]
        out = io.StringIO()
        with mock.patch.object(installer, 'default_cli_paths', return_value=(homebrew, str(h.home / '.local/bin/claude'))), \
                contextlib.redirect_stdout(out):
            code = installer.run(installer.parse_args(['--app-dir', str(h.app)] + list(argv)), home=h.home, root=h.root)
        return code, out.getvalue()

    def test_missing_claude_suggests_install_flag(self):
        with IsolatedHome() as h:
            with self.assertRaises(RuntimeError) as ctx:
                self.run_installer(h)
            self.assertIn('--install-claude', str(ctx.exception))
            self.assertFalse(h.root.exists())

    def test_installs_when_missing_then_wraps_it(self):
        with IsolatedHome() as h:
            def fake_install(port, home, channel, root):
                write_executable(bootstrap.native_path(home), '#!/bin/sh\n')
                return str(bootstrap.native_path(home))

            with mock.patch.object(installer, 'install_claude', side_effect=fake_install) as install:
                code, _ = self.run_installer(h, '--install-claude', '--port', '7891')
            self.assertEqual(code, 0)
            install.assert_called_once_with(7891, h.home, 'stable', h.root)
            config = json.loads((h.root / 'config.json').read_text())
            self.assertIn(str(h.home / '.local/bin/claude'), config['cli_candidates'])

    def test_skips_install_when_present(self):
        with IsolatedHome() as h:
            write_executable(h.home / '.local/bin/claude', '#!/bin/sh\n')
            with mock.patch.object(installer, 'install_claude') as install:
                code, out = self.run_installer(h, '--install-claude')
            self.assertEqual(code, 0)
            install.assert_not_called()
            self.assertIn('already installed', out)

    def test_dry_run_never_installs(self):
        with IsolatedHome() as h:
            with mock.patch.object(installer, 'install_claude') as install:
                code, out = self.run_installer(h, '--install-claude', '--dry-run')
            self.assertEqual(code, 0)
            install.assert_not_called()
            self.assertIn('Would install Claude Code', out)
            self.assertFalse(h.root.exists())

    def test_invalid_settings_stop_before_download(self):
        with IsolatedHome() as h:
            with mock.patch.object(installer, 'install_claude') as install:
                with self.assertRaises(ValueError):
                    self.run_installer(h, '--install-claude', '--timezone', 'Bad/Zone')
            install.assert_not_called()


class ShellEditTests(unittest.TestCase):
    def test_edits_outside_block_are_kept_through_reinstall_and_rollback(self):
        with IsolatedHome() as h:
            zshrc = h.home / '.zshrc'
            zshrc.write_text('# mine\n')
            self.assertEqual(h.install().returncode, 0)
            # e.g. Claude's own installer or the user appends a PATH line later.
            zshrc.write_text(zshrc.read_text() + 'export PATH="$HOME/.local/bin:$PATH"\n')
            result = h.install()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Keeping your edits', result.stdout)
            self.assertIn('.local/bin', zshrc.read_text())
            result = h.rollback()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(zshrc.read_text(), '# mine\nexport PATH="$HOME/.local/bin:$PATH"\n')

    def test_deleted_block_is_still_a_conflict(self):
        with IsolatedHome() as h:
            zshrc = h.home / '.zshrc'
            self.assertEqual(h.install().returncode, 0)
            zshrc.write_text('# block deleted\n')
            self.assertNotEqual(h.install().returncode, 0)


if __name__ == '__main__':
    unittest.main()
