import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import ci
import fast_pack


SOURCE = '''
def main():
    events.append('art')
    def patch():
        events.append('rewrite')
    step('rewrite', lambda: False, patch)
    events.append('overlay')
    packs = 'input packages'
    events.append('translate')
    lib = 'translated output'
    events.append('validate and package')
'''


class FastPackTests(unittest.TestCase):
    def test_split_retains_generation_and_final_validation_without_running_linux_rewrite(self):
        prefix, suffix, cached = fast_pack.phase_nodes(SOURCE)
        module = type('Packer', (), {'__file__': 'test-packer.py'})()
        namespace = {'events': [], 'step': lambda name, done, fn: fn()}
        exec(fast_pack.compiled(module, [prefix]), namespace)
        namespace['main']()
        self.assertEqual(namespace['events'], ['art', 'overlay'])
        exec(fast_pack.compiled(module, suffix), namespace)
        self.assertEqual(namespace['events'], ['art', 'overlay', 'translate', 'validate and package'])
        namespace['events'] = []
        exec(fast_pack.compiled(module, cached), namespace)
        self.assertEqual(namespace['events'], ['validate and package'])

    def test_upstream_stage_changes_fail_closed(self):
        for source in (SOURCE.replace("packs = 'input packages'", 'inputs = 1'),
                       SOURCE.replace("lib = 'translated output'", 'library = 1'),
                       SOURCE.replace("step('rewrite', lambda: False, patch)", 'patch()')):
            with self.assertRaises(ValueError):
                fast_pack.phase_nodes(source)

    def test_receipt_rejects_changed_incomplete_or_wrong_recipe_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            file = root / 'program.bin'
            file.write_bytes(b'complete program')
            fast_pack.seal(root, 'recipe')
            self.assertEqual(fast_pack.receipt(root, 'recipe')['key'], 'recipe')
            with self.assertRaises(ValueError):
                fast_pack.receipt(root, 'different recipe')
            file.write_bytes(b'corrupt')
            with self.assertRaises(ValueError):
                fast_pack.receipt(root, 'recipe')
            file.unlink()
            with self.assertRaises(ValueError):
                fast_pack.receipt(root, 'recipe')

    def test_payload_cache_rejects_member_that_escapes_app(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'shells').mkdir()
            for name in ci.SHELL_NAMES:
                (root / 'shells' / name).write_bytes(b'shell')
            with zipfile.ZipFile(root / 'payload.zip', 'w') as archive:
                archive.writestr('../escape', b'invalid')
                archive.writestr('Frameworks/Guest.framework/Guest', bytes.fromhex('cffaedfe0c000001'))
            fast_pack.seal(root, 'recipe')
            with patch.object(fast_pack, 'CACHE', root), patch.dict(ci.CONFIG, {
                    'shell_sha256': ci.sha256(root / 'shells' / ci.SHELL_NAMES[0]),
                    'ios18_shell_sha256': ci.sha256(root / 'shells' / ci.SHELL_NAMES[1])}):
                self.assertIsNone(fast_pack.cached_payload('recipe'))


if __name__ == '__main__':
    unittest.main()
