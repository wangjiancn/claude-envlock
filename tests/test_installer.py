import json
import unittest

from claude_envlock.installer import shell_block
from claude_envlock.jsonc import loads, update
from claude_envlock.proxy import proxy_environment

from .support import IsolatedHome, closed_port, make_config

NONESSENTIAL = 'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC'


class InstallerTests(unittest.TestCase):
    def test_repeat_install_rollback_and_conflict_protection(self):
        with IsolatedHome() as h:
            h.vscode_settings.parent.mkdir(parents=True)
            initial = '{\n// preserve comment\n"other": [1,2,],\n}\n'
            h.vscode_settings.write_text(initial)
            zshrc = h.home / '.zshrc'
            zshrc.write_text('# existing\n')

            first = h.install()
            self.assertEqual(first.returncode, 0, first.stderr)
            manifest = h.root / 'backups/manifest.json'
            before = manifest.read_bytes()
            self.assertEqual(oct(h.root.stat().st_mode & 0o777), '0o700')
            self.assertEqual(oct(manifest.stat().st_mode & 0o777), '0o600')

            second = h.install()
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn('Already up to date', second.stdout)
            self.assertEqual(manifest.read_bytes(), before)
            self.assertIn('// preserve comment', h.vscode_settings.read_text())
            self.assertEqual(zshrc.read_text().count('Claude Envlock managed entry >>>'), 1)

            self.assertEqual(h.rollback('--check').returncode, 0)
            config = h.root / 'config.json'  # a file claude-envlock owns: edits there still block rollback
            owned = config.read_text()
            config.write_text(owned + ' ')
            self.assertNotEqual(h.rollback().returncode, 0)
            self.assertTrue(h.app.exists(), 'no partial rollback')

            config.write_text(owned)
            result = h.rollback()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(h.vscode_settings.read_text(), initial)
            self.assertEqual(zshrc.read_text(), '# existing\n')
            self.assertFalse((h.root / 'config.json').exists())
            self.assertFalse((h.root / 'lib').exists())
            self.assertFalse(h.app.exists())

    def test_shared_settings_never_block_install(self):
        with IsolatedHome() as h:
            h.claude_settings.parent.mkdir()
            h.claude_settings.write_text(json.dumps({'env': {'TZ': 'Asia/Tokyo'}, 'model': 'original'}))
            self.assertEqual(h.install('--timezone', 'Asia/Jakarta').returncode, 0)

            data = json.loads(h.claude_settings.read_text())
            data['tui'] = {'theme': 'dark'}  # Claude writes its own settings over time.
            data['env']['MY_VAR'] = 'mine'
            h.claude_settings.write_text(json.dumps(data))
            result = h.install('--timezone', 'Asia/Singapore')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('Replacing', result.stdout)
            data = json.loads(h.claude_settings.read_text())
            self.assertEqual((data['tui'], data['env']['MY_VAR'], data['env']['TZ']),
                             ({'theme': 'dark'}, 'mine', 'Asia/Singapore'))

            data['env']['TZ'] = 'Australia/Perth'  # a hand edit to a managed key: replaced and reported
            h.claude_settings.write_text(json.dumps(data))
            result = h.install()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('env.TZ: Australia/Perth -> Asia/Singapore', result.stdout)
            self.assertEqual(json.loads(h.claude_settings.read_text())['env']['TZ'], 'Asia/Singapore')
            backups = list((h.root / 'backups').glob('claude-settings.json.*.bak'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(json.loads(backups[0].read_text())['env']['TZ'], 'Australia/Perth')
            variables = loads(h.vscode_settings.read_text())['claudeCode.environmentVariables']
            self.assertIn({'name': 'TZ', 'value': 'Asia/Singapore'}, variables)

            self.assertEqual(h.install('--merge-unmanaged-settings').returncode, 0)  # old flag still accepted

    def test_rollback_restores_only_managed_keys_after_later_edits(self):
        with IsolatedHome() as h:
            h.claude_settings.parent.mkdir()
            h.claude_settings.write_text(json.dumps({'env': {'TZ': 'Asia/Tokyo'}, 'model': 'original'}))
            h.vscode_settings.parent.mkdir(parents=True)
            h.vscode_settings.write_text('{\n  // mine\n  "editor.fontSize": 13\n}\n')
            self.assertEqual(h.install().returncode, 0)

            data = json.loads(h.claude_settings.read_text())
            data['tui'] = {'theme': 'dark'}
            data['env']['HTTPS_PROXY'] = 'http://127.0.0.1:1'  # hand edit to a managed key: still restored
            h.claude_settings.write_text(json.dumps(data))
            h.vscode_settings.write_text(h.vscode_settings.read_text() + '// later edit\n')

            result = h.rollback()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(h.claude_settings.read_text()), {
                'env': {'TZ': 'Asia/Tokyo'}, 'model': 'original', 'tui': {'theme': 'dark'}})
            text = h.vscode_settings.read_text()
            self.assertIn('// mine', text)
            self.assertIn('// later edit', text)
            self.assertEqual(loads(text), {'editor.fontSize': 13})

    def test_nonessential_traffic_variable_is_no_longer_set(self):
        cfg_env = make_config().managed_env()
        self.assertNotIn(NONESSENTIAL, cfg_env)
        self.assertEqual((cfg_env['DISABLE_TELEMETRY'], cfg_env['DISABLE_ERROR_REPORTING']), ('1', '1'))
        self.assertNotIn(NONESSENTIAL, proxy_environment(make_config(), {}))

    def test_upgrade_removes_values_older_releases_wrote(self):
        with IsolatedHome() as h:
            self.assertEqual(h.install().returncode, 0)
            # What an older release left behind: the variable in all three places.
            data = json.loads(h.claude_settings.read_text())
            data['env'][NONESSENTIAL] = '1'
            h.claude_settings.write_text(json.dumps(data, indent=2) + '\n')
            vscode = loads(h.vscode_settings.read_text())
            variables = vscode['claudeCode.environmentVariables'] + [{'name': NONESSENTIAL, 'value': '1'}]
            h.vscode_settings.write_text(update(h.vscode_settings.read_text(),
                                                {'claudeCode.environmentVariables': variables}))
            env_file = h.root / 'claude.env'
            env_file.write_text(env_file.read_text().replace(
                'unset ALL_PROXY', 'export {}="1"\nunset ALL_PROXY'.format(NONESSENTIAL)))

            result = h.install()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('Replacing', result.stdout)
            self.assertNotIn(NONESSENTIAL, json.loads(h.claude_settings.read_text())['env'])
            names = [v['name'] for v in loads(h.vscode_settings.read_text())['claudeCode.environmentVariables']]
            self.assertNotIn(NONESSENTIAL, names)
            self.assertNotIn(NONESSENTIAL, env_file.read_text())

    def test_user_can_still_opt_in_or_keep_own_value(self):
        with IsolatedHome() as h:
            h.claude_settings.parent.mkdir()
            h.claude_settings.write_text(json.dumps({'env': {NONESSENTIAL: 'true'}}))  # the user's own value
            self.assertEqual(h.install().returncode, 0)
            self.assertEqual(h.install().returncode, 0)
            self.assertEqual(json.loads(h.claude_settings.read_text())['env'][NONESSENTIAL], 'true')

        with IsolatedHome() as h:
            self.assertEqual(h.install().returncode, 0)
            env_file = h.root / 'claude.env'  # opt back in as an extra variable
            env_file.write_text(env_file.read_text().replace(
                '# ---- Extra variables passed to Claude (add your own export lines here) ----\n',
                '# ---- Extra variables passed to Claude (add your own export lines here) ----\n'
                'export {}="1"\n'.format(NONESSENTIAL)))
            result = h.install()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(h.claude_settings.read_text())['env'][NONESSENTIAL], '1')
            self.assertIn('export {}="1"'.format(NONESSENTIAL), env_file.read_text())

    def test_whole_file_records_from_older_releases_are_migrated(self):
        import base64
        with IsolatedHome() as h:
            h.claude_settings.parent.mkdir()
            original = json.dumps({'env': {'TZ': 'Asia/Tokyo'}, 'model': 'original'}).encode()
            h.claude_settings.write_bytes(original)
            self.assertEqual(h.install().returncode, 0)
            manifest_path = h.root / 'backups/manifest.json'
            manifest = json.loads(manifest_path.read_text())
            installed = h.claude_settings.read_bytes()
            import hashlib
            manifest['files'][str(h.claude_settings)] = {   # the old whole-file record format
                'existed': True, 'mode': 0o644, 'original': base64.b64encode(original).decode(),
                'installed_sha256': hashlib.sha256(installed).hexdigest()}
            manifest_path.write_text(json.dumps(manifest))

            data = json.loads(installed)
            data['tui'] = 'fullscreen'
            h.claude_settings.write_text(json.dumps(data))
            result = h.install()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(manifest_path.read_text())['files'][str(h.claude_settings)]['kind'], 'keys')
            result = h.rollback()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(h.claude_settings.read_text()),
                             {'env': {'TZ': 'Asia/Tokyo'}, 'model': 'original', 'tui': 'fullscreen'})

    def test_timezone_defaults_and_is_sticky(self):
        with IsolatedHome() as h:
            self.assertEqual(h.install().returncode, 0)
            self.assertEqual(json.loads(h.claude_settings.read_text())['env']['TZ'], 'Asia/Jakarta')

            self.assertEqual(h.install('--timezone', 'Asia/Tokyo').returncode, 0)
            self.assertEqual(h.install().returncode, 0)  # sticky: no flag keeps the old value
            self.assertEqual(json.loads((h.root / 'config.json').read_text())['cli_timezone'], 'Asia/Tokyo')
            self.assertIn({'name': 'TZ', 'value': 'Asia/Tokyo'},
                          loads(h.vscode_settings.read_text())['claudeCode.environmentVariables'])

    def test_china_timezone_rejected_before_writing(self):
        with IsolatedHome() as h:
            result = h.install('--timezone', 'Asia/Shanghai')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('China timezones are not allowed', result.stderr)
            self.assertFalse(h.root.exists())

    def test_timezone_mismatch_stops_install_until_skipped(self):
        with IsolatedHome() as h, closed_port() as port:
            # Proxy unreachable, so the exit country can't be confirmed: the check must stop the install.
            result = h.install('--port', str(port), check_timezone=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('--skip-timezone-check', result.stderr)
            self.assertFalse(h.root.exists())
            result = h.install('--port', str(port))  # helper passes --skip-timezone-check
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Timezone check: skipped', result.stdout)

    def test_invalid_timezone_rejected_before_writing(self):
        with IsolatedHome() as h:
            result = h.install('--timezone', 'Bad/Timezone')
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(h.root.exists())

    def test_missing_claude_cli_fails_before_writing(self):
        with IsolatedHome() as h:
            result = h.install('--claude', str(h.home / 'missing'), claude=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('No Claude CLI found', result.stderr)
            self.assertFalse(h.root.exists())

    def test_dry_run_writes_nothing(self):
        with IsolatedHome() as h:
            result = h.install('--dry-run')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(h.root.exists())
            self.assertFalse(h.claude_settings.exists())

    def test_refuses_foreign_app_bundle(self):
        with IsolatedHome() as h:
            h.app.mkdir(parents=True)
            self.assertNotEqual(h.install().returncode, 0)


def block(body):
    return '# >>> Claude Envlock managed entry >>>\n' + body + '\n# <<< Claude Envlock managed entry <<<'


class ShellBlockTests(unittest.TestCase):
    def test_replaces_existing_block_in_place(self):
        once = shell_block('# a\n', block('x'))
        twice = shell_block(once, block('y'))
        self.assertEqual(twice.count('managed entry >>>'), 1)
        self.assertIn('y', twice)
        self.assertTrue(twice.startswith('# a\n'))

    def test_rejects_malformed_markers(self):
        with self.assertRaises(ValueError):
            shell_block('# >>> Claude Envlock managed entry >>>\n', block('x'))


if __name__ == '__main__':
    unittest.main()


class UpgradeFromClaudeSafeTests(unittest.TestCase):
    """Installs made before the rename (claude-safe) must upgrade in place."""

    def test_legacy_shell_block_is_replaced_not_duplicated(self):
        with IsolatedHome() as h:
            zshrc = h.home / '.zshrc'
            zshrc.write_text('# mine\n\n# >>> Claude Safe managed entry >>>\nold\n# <<< Claude Safe managed entry <<<\n')
            result = h.install()
            self.assertEqual(result.returncode, 0, result.stderr)
            text = zshrc.read_text()
            self.assertNotIn('Claude Safe', text)
            self.assertEqual(text.count('Claude Envlock managed entry >>>'), 1)
            self.assertTrue(text.startswith('# mine\n'))

    def test_legacy_setting_names_are_migrated(self):
        with IsolatedHome() as h:
            self.assertEqual(h.install().returncode, 0)
            env_file = h.root / 'claude.env'
            env_file.write_text(env_file.read_text().replace('CLAUDE_ENVLOCK_', 'CLAUDE_SAFE_')
                                .replace('CLAUDE_SAFE_ON_MISMATCH="prompt"', 'CLAUDE_SAFE_ON_MISMATCH="block"'))
            result = h.install()
            self.assertEqual(result.returncode, 0, result.stderr)
            text = env_file.read_text()
            self.assertNotIn('CLAUDE_SAFE_', text)
            self.assertIn('CLAUDE_ENVLOCK_ON_MISMATCH="block"', text)

    def test_renamed_app_is_retired_and_rollback_still_works(self):
        with IsolatedHome() as h:
            old_app = h.home / 'Applications' / 'Claude Safe.app'
            self.assertEqual(h.install('--app-dir', str(old_app)).returncode, 0)
            self.assertTrue(old_app.exists())
            result = h.install()  # default test app dir = "Claude Envlock.app"
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(old_app.exists())
            self.assertTrue(h.app.exists())
            self.assertIn('Already up to date', h.install().stdout)
            result = h.rollback()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(h.app.exists())

    def test_modified_old_app_blocks_retirement(self):
        with IsolatedHome() as h:
            old_app = h.home / 'Applications' / 'Claude Safe.app'
            self.assertEqual(h.install('--app-dir', str(old_app)).returncode, 0)
            plist = old_app / 'Contents' / 'Info.plist'
            plist.write_bytes(plist.read_bytes() + b'\n')
            self.assertNotEqual(h.install().returncode, 0)
            self.assertTrue(plist.exists())
