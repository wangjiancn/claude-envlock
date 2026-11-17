import unittest

from claude_envlock.jsonc import loads, update


class JsoncTests(unittest.TestCase):
    def test_preserves_comments_and_nested_settings(self):
        text = '{\n// 中文注释\n"other": {"url": "https://a/b", "items": [1, 2,],},\n/* keep */ "replace": false,\n}\n'
        new = update(text, {'replace': True, 'added': ['x']})
        self.assertIn('// 中文注释', new)
        self.assertIn('/* keep */', new)
        self.assertEqual(loads(new), {'other': {'url': 'https://a/b', 'items': [1, 2]},
                                      'replace': True, 'added': ['x']})

    def test_update_is_idempotent(self):
        new = update('{"a": 1}', {'a': 2, 'b': [3]})
        self.assertEqual(update(new, {'a': 2, 'b': [3]}), new)

    def test_adds_to_empty_object(self):
        self.assertEqual(loads(update('{}\n', {'k': 'v'})), {'k': 'v'})

    def test_rejects_duplicate_keys(self):
        with self.assertRaises(ValueError):
            update('{"a": 1, "a": 2}', {'a': 3})

    def test_rejects_non_object(self):
        with self.assertRaises(ValueError):
            update('[1]', {'a': 1})


if __name__ == '__main__':
    unittest.main()
