import json
import unittest

from claude_envlock.installer import shell_block
from claude_envlock.jsonc import loads

from .support import IsolatedHome


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
            managed = h.vscode_settings.read_text()
            h.vscode_settings.write_text(managed + '// later edit\n')
            self.assertNotEqual(h.rollback().returncode, 0)
            self.assertTrue((h.root / 'config.json').exists(), 'no partial rollback')

            h.vscode_settings.write_text(managed)
            result = h.rollback()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(h.vscode_settings.read_text(), initial)
            self.assertEqual(zshrc.read_text(), '# existing\n')
            self.assertFalse((h.root / 'config.json').exists())
            self.assertFalse((h.root / 'lib').exists())
            self.assertFalse(h.app.exists())

    def test_timezone_migration_keeps_unmanaged_edits_and_rollback(self):
        with IsolatedHome() as h:
            h.claude_settings.parent.mkdir()
            h.claude_settings.write_text(json.dumps({'env': {'TZ': 'Asia/Tokyo'}, 'model': 'original'}))
            self.assertEqual(h.install('--timezone', 'Asia/Jakarta').returncode, 0)

            data = json.loads(h.claude_settings.read_text())
            data['tui'] = {'theme': 'dark'}  # Claude writes its own settings over time.
            h.claude_settings.write_text(json.dumps(data))
            before = h.claude_settings.read_bytes()
            self.assertNotEqual(h.install('--timezone', 'Asia/Singapore').returncode, 0)
            self.assertEqual(h.claude_settings.read_bytes(), before)

            data['env']['TZ'] = 'Australia/Perth'  # A hand edit to a managed key must still block.
            h.claude_settings.write_text(json.dumps(data))
            self.assertNotEqual(h.install('--merge-unmanaged-settings').returncode, 0)

            data['env']['TZ'] = 'Asia/Jakarta'
            h.claude_settings.write_text(json.dumps(data))
            result = h.install('--timezone', 'Asia/Singapore', '--merge-unmanaged-settings')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(h.claude_settings.read_text())['env']['TZ'], 'Asia/Singapore')
            variables = loads(h.vscode_settings.read_text())['claudeCode.environmentVariables']
            self.assertIn({'name': 'TZ', 'value': 'Asia/Singapore'}, variables)

            result = h.rollback()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(h.claude_settings.read_text()), {
                'env': {'TZ': 'Asia/Tokyo'}, 'model': 'original', 'tui': {'theme': 'dark'}})

    def test_timezone_is_opt_in_sticky_and_clearable(self):
        with IsolatedHome() as h:
            self.assertEqual(h.install().returncode, 0)
            self.assertNotIn('TZ', json.loads(h.claude_settings.read_text())['env'])

            self.assertEqual(h.install('--timezone', 'Asia/Jakarta').returncode, 0)
            self.assertEqual(h.install().returncode, 0)  # sticky: no flag keeps the old value
            self.assertEqual(json.loads((h.root / 'config.json').read_text())['cli_timezone'], 'Asia/Jakarta')

            result = h.install('--no-timezone')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('TZ', json.loads(h.claude_settings.read_text())['env'])
            names = [v['name'] for v in loads(h.vscode_settings.read_text())['claudeCode.environmentVariables']]
            self.assertNotIn('TZ', names)

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
