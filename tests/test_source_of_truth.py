"""claude.env as the single source of truth, drift detection, exit-IP allowlist, and the Block/Continue prompt."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from claude_envlock import envfile, integrity, launchers, prompt, proxy
from claude_envlock.config import Config
from claude_envlock.jsonc import loads

from .support import IsolatedHome, make_config


class EnvFileTests(unittest.TestCase):
    def test_render_parse_round_trip(self):
        cfg = make_config(cli_timezone='Asia/Jakarta', allowed_exit_ips=('203.0.113.10', '198.51.100.0/24'),
                          on_mismatch='block', extra_env={'ANTHROPIC_MODEL': 'claude-opus-5-5'})
        settings = envfile.settings_from_values(envfile.parse(envfile.render(cfg)))
        self.assertEqual(settings, envfile.settings_from_config(cfg))

    @unittest.skipUnless(Path('/bin/zsh').exists(), 'needs zsh')
    def test_shell_source_matches_python_parse(self):
        cfg = make_config(extra_env={'MY_FLAG': 'a b:c/d'}, allowed_exit_ips=('203.0.113.10',))
        with tempfile.NamedTemporaryFile('w', suffix='.env') as handle:
            handle.write(envfile.render(cfg))
            handle.flush()
            out = subprocess.run(['/bin/zsh', '-fc', 'ALL_PROXY=x; source "$1"; '
                                  'print -r -- "$HTTPS_PROXY|$MY_FLAG|$CLAUDE_ENVLOCK_ALLOWED_EXIT_IPS|${ALL_PROXY-unset}"',
                                  'zsh', handle.name], capture_output=True, text=True, check=True).stdout
        self.assertEqual(out.strip(), 'http://127.0.0.1:7890|a b:c/d|203.0.113.10|unset')

    def test_rejects_unsafe_or_malformed_lines(self):
        for text in ['export A="$(rm -rf ~)"', 'A=`id`', 'A="x" ; rm x', 'not a line', 'A=1\nA=2']:
            with self.assertRaises(ValueError, msg=text):
                envfile.parse(text)

    def test_rejects_unknown_setting_and_reserved_extra(self):
        with self.assertRaises(ValueError):
            envfile.settings_from_values({'CLAUDE_ENVLOCK_PROT': '1'})
        with self.assertRaises(ValueError):
            make_config(extra_env={'HTTPS_PROXY': 'http://evil:1'})

    def test_detects_hand_edited_generated_line(self):
        old, new = make_config().managed_env(), make_config(port=7891).managed_env()
        self.assertEqual(envfile.hand_edited_generated_keys({'HTTPS_PROXY': 'http://127.0.0.1:7890'}, old, new), [])
        self.assertEqual(envfile.hand_edited_generated_keys({'HTTPS_PROXY': 'http://1.2.3.4:1'}, old, new),
                         ['HTTPS_PROXY'])


class ExitIpTests(unittest.TestCase):
    def test_allowlist_matching(self):
        cfg = make_config(allowed_exit_ips=('203.0.113.10', '198.51.100.0/24', '2001:db8::/32'))
        self.assertTrue(cfg.exit_ip_allowed('203.0.113.10'))
        self.assertTrue(cfg.exit_ip_allowed('198.51.100.77'))
        self.assertTrue(cfg.exit_ip_allowed('2001:db8::1'))
        self.assertFalse(cfg.exit_ip_allowed('203.0.113.11'))

    def test_invalid_allowlist_entry_rejected(self):
        with self.assertRaises(ValueError):
            make_config(allowed_exit_ips=('not-an-ip',))

    def test_no_allowlist_means_no_request(self):
        with mock.patch.object(proxy, 'exit_trace') as trace:
            self.assertEqual(proxy.exit_ip_problems(make_config()), [])
            trace.assert_not_called()

    def test_disallowed_ip_is_reported_masked(self):
        cfg = make_config(allowed_exit_ips=('203.0.113.10',))
        with mock.patch.object(proxy, 'exit_trace', return_value={'ip': '192.0.2.55', 'loc': 'XX'}):
            problems = proxy.exit_ip_problems(cfg)
        self.assertEqual(len(problems), 1)
        self.assertIn('192.0.x.x', problems[0])
        self.assertNotIn('192.0.2.55', problems[0])

    def test_unverifiable_exit_ip_is_a_problem(self):
        cfg = make_config(allowed_exit_ips=('203.0.113.10',))
        with mock.patch.object(proxy, 'exit_trace', side_effect=OSError('down')):
            self.assertEqual(len(proxy.exit_ip_problems(cfg)), 1)

    def test_trace_parsing(self):
        cfg = make_config()
        with mock.patch.object(proxy, 'fetch_via_proxy', return_value='fl=1\nip=203.0.113.10\nloc=SG\n'):
            self.assertEqual(proxy.exit_trace(cfg), {'ip': '203.0.113.10', 'loc': 'SG'})
        with mock.patch.object(proxy, 'fetch_via_proxy', return_value='<html>blocked</html>'):
            with self.assertRaises(ValueError):
                proxy.exit_trace(cfg)


class PromptTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_block_policy_never_shows_dialog(self):
        with mock.patch.object(prompt, 'ask_dialog') as dialog:
            with self.assertRaises(RuntimeError):
                prompt.confirm(make_config(root=self.root, on_mismatch='block'), ['x'])
            dialog.assert_not_called()

    def test_continue_allows_and_is_logged(self):
        with mock.patch.object(prompt, 'ask_dialog', return_value=True):
            prompt.confirm(make_config(root=self.root), ['Modified: x'])
        log = self.root / 'decisions.log'
        self.assertEqual(json.loads(log.read_text())['decision'], 'continued')
        self.assertEqual(oct(log.stat().st_mode & 0o777), '0o600')

    def test_block_button_blocks(self):
        with mock.patch.object(prompt, 'ask_dialog', return_value=False):
            with self.assertRaises(RuntimeError):
                prompt.confirm(make_config(root=self.root), ['x'])

    def test_no_gui_falls_back_to_tty_then_blocks(self):
        with mock.patch.object(prompt, 'ask_dialog', return_value=None), \
                mock.patch.object(prompt, 'ask_tty', return_value=False) as tty:
            with self.assertRaises(RuntimeError):
                prompt.confirm(make_config(root=self.root), ['x'])
            tty.assert_called_once()

    def test_dialog_message_is_passed_as_argument_not_script(self):
        with mock.patch.object(prompt.sys, 'platform', 'darwin'), \
                mock.patch.object(prompt.subprocess, 'run') as run:
            run.return_value = subprocess.CompletedProcess([], 0, 'Continue\n', '')
            self.assertTrue(prompt.ask_dialog('evil" & do shell script "id'))
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[-1], 'evil" & do shell script "id')
        self.assertFalse(any('evil' in part for part in cmd[:-1]))


class PreflightTests(unittest.TestCase):
    def test_proxy_failure_blocks_without_prompt(self):
        with mock.patch.object(launchers.integrity, 'verify', return_value=['drift']), \
                mock.patch.object(launchers, 'gate', side_effect=OSError('refused')), \
                mock.patch.object(launchers.prompt, 'confirm') as confirm:
            with self.assertRaises(OSError):
                launchers.preflight(make_config())
            confirm.assert_not_called()

    def test_drift_and_exit_ip_problems_go_to_one_prompt(self):
        with mock.patch.object(launchers.integrity, 'verify', return_value=['drift']), \
                mock.patch.object(launchers, 'gate'), \
                mock.patch.object(launchers, 'exit_ip_problems', return_value=['ip']), \
                mock.patch.object(launchers.prompt, 'confirm') as confirm:
            launchers.preflight(make_config())
        self.assertEqual(confirm.call_args.args[1], ['drift', 'ip'])

    def test_clean_state_never_prompts(self):
        with mock.patch.object(launchers.integrity, 'verify', return_value=[]), \
                mock.patch.object(launchers, 'gate'), \
                mock.patch.object(launchers, 'exit_ip_problems', return_value=[]), \
                mock.patch.object(launchers.prompt, 'confirm') as confirm:
            launchers.preflight(make_config())
        confirm.assert_not_called()


class DriftDetectionTests(unittest.TestCase):
    def verify(self, h):
        return integrity.verify(Config.load(h.root), home=h.home)

    def test_fresh_install_is_clean_and_each_change_is_detected(self):
        with IsolatedHome() as h:
            self.assertEqual(h.install().returncode, 0)
            self.assertEqual(self.verify(h), [])

            # Claude writing its own settings must NOT trigger a prompt.
            data = json.loads(h.claude_settings.read_text())
            data['tui'] = {'theme': 'dark'}
            h.claude_settings.write_text(json.dumps(data))
            self.assertEqual(self.verify(h), [])

            data['env']['HTTPS_PROXY'] = 'http://127.0.0.1:1'
            h.claude_settings.write_text(json.dumps(data))
            self.assertTrue(any('env.HTTPS_PROXY' in p for p in self.verify(h)))
            data['env']['HTTPS_PROXY'] = 'http://127.0.0.1:7890'
            h.claude_settings.write_text(json.dumps(data))

            shim = h.root / 'bin' / 'claude'
            original = shim.read_bytes()
            shim.write_bytes(original + b'# tampered\n')
            self.assertTrue(any('Modified: ' in p and p.endswith('bin/claude') for p in self.verify(h)))
            shim.write_bytes(original)

            zshrc = h.home / '.zshrc'
            zshrc.write_text('# block removed\n')
            self.assertTrue(any('.zshrc' in p for p in self.verify(h)))

    def test_unapplied_env_edit_is_detected_then_applied(self):
        with IsolatedHome() as h:
            self.assertEqual(h.install().returncode, 0)
            env_file = h.root / 'claude.env'
            env_file.write_text(env_file.read_text() + 'export ANTHROPIC_MODEL="claude-opus-5-5"\n')
            self.assertTrue(any('not applied' in p for p in self.verify(h)))

            result = h.install()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.verify(h), [])
            self.assertEqual(json.loads(h.claude_settings.read_text())['env']['ANTHROPIC_MODEL'], 'claude-opus-5-5')
            variables = loads(h.vscode_settings.read_text())['claudeCode.environmentVariables']
            self.assertIn({'name': 'ANTHROPIC_MODEL', 'value': 'claude-opus-5-5'}, variables)

            # Removing the variable from claude.env removes it everywhere.
            env_file.write_text(env_file.read_text().replace('export ANTHROPIC_MODEL="claude-opus-5-5"\n', ''))
            self.assertEqual(h.install().returncode, 0)
            self.assertNotIn('ANTHROPIC_MODEL', json.loads(h.claude_settings.read_text())['env'])
            self.assertEqual(self.verify(h), [])

    def test_exit_ip_flag_writes_source_of_truth(self):
        with IsolatedHome() as h:
            result = h.install('--exit-ips', '203.0.113.10 198.51.100.0/24', '--on-mismatch', 'block')
            self.assertEqual(result.returncode, 0, result.stderr)
            values = envfile.parse((h.root / 'claude.env').read_text())
            self.assertEqual(values['CLAUDE_ENVLOCK_ALLOWED_EXIT_IPS'], '203.0.113.10 198.51.100.0/24')
            cfg = Config.load(h.root)
            self.assertEqual(cfg.allowed_exit_ips, ('203.0.113.10', '198.51.100.0/24'))
            self.assertEqual(cfg.on_mismatch, 'block')
            self.assertEqual(h.install().returncode, 0)  # values persist without flags
            self.assertEqual(Config.load(h.root).allowed_exit_ips, cfg.allowed_exit_ips)

    def test_hand_edited_generated_line_is_refused(self):
        with IsolatedHome() as h:
            self.assertEqual(h.install().returncode, 0)
            env_file = h.root / 'claude.env'
            env_file.write_text(env_file.read_text().replace(
                'export HTTPS_PROXY="http://127.0.0.1:7890"', 'export HTTPS_PROXY="http://10.0.0.1:8080"'))
            result = h.install()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('HTTPS_PROXY', result.stderr)

    def test_bad_env_file_value_is_refused(self):
        with IsolatedHome() as h:
            self.assertEqual(h.install().returncode, 0)
            env_file = h.root / 'claude.env'
            env_file.write_text(env_file.read_text().replace(
                'CLAUDE_ENVLOCK_ALLOWED_EXIT_IPS=""', 'CLAUDE_ENVLOCK_ALLOWED_EXIT_IPS="999.1.1.1"'))
            self.assertNotEqual(h.install().returncode, 0)


if __name__ == '__main__':
    unittest.main()


class SymlinkedHomeTests(unittest.TestCase):
    def test_fresh_install_is_clean_when_home_is_a_symlink(self):
        # Regression: /tmp -> /private/tmp made a fresh install report drift and block launches.
        with IsolatedHome() as h:
            link = h.home.parent / (h.home.name + '-link')
            link.symlink_to(h.home)
            try:
                env = dict(h.env, HOME=str(link))
                import sys
                from .support import REPO
                result = subprocess.run([sys.executable, '-I', str(REPO / 'install.py'), '--app-dir', str(h.app),
                                         '--claude', str(h.claude), '--skip-timezone-check'],
                                        env=env, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                runtime_root = (link / '.claude-env').resolve()  # what the shim computes
                self.assertEqual(integrity.verify(Config.load(runtime_root), home=link), [])
            finally:
                link.unlink()
