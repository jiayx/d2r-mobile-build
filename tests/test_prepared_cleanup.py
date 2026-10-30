import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/maintenance'))
from clean_prepared import clean_archive


class PreparedCleanupTest(unittest.TestCase):
    def test_preserves_runtime_and_rejects_corruption(self):
        for platform in ('ios', 'macos'):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                obsolete = 'resources.json' if platform == 'ios' else 'resources/data/.build.config'
                files = {obsolete: b'old metadata', 'runtime/.build.config': b'required config',
                         'program': b'unchanged executable'}
                records = {n: hashlib.sha256(b).hexdigest() for n, b in files.items()}
                if platform == 'ios':
                    records = {n: {'sha256': h, 'bytes': len(files[n])} for n, h in records.items()}
                manifest = 'prepared.json' if platform == 'ios' else 'manifest.json'
                info = {'format': 'd2r-mobile-' + ('prepared' if platform == 'ios' else 'macos-prepared'),
                        'schema_version': 2, 'files': records,
                        'prepare_key' if platform == 'ios' else 'key': 'original'}
                with zipfile.ZipFile(root / 'input.zip', 'w') as z:
                    for n, b in files.items():
                        member = zipfile.ZipInfo(n); member.external_attr = 0o100755 << 16
                        z.writestr(member, b)
                    z.writestr(manifest, json.dumps(info))
                report = clean_archive(root / 'input.zip', root / 'output.zip', platform)
                self.assertEqual(report['removed'], [obsolete])
                with zipfile.ZipFile(root / 'output.zip') as z:
                    self.assertEqual(z.read('runtime/.build.config'), files['runtime/.build.config'])
                    self.assertEqual(z.read('program'), files['program'])
                    self.assertEqual(z.getinfo('program').external_attr >> 16, 0o100755)
                with zipfile.ZipFile(root / 'corrupt.zip', 'w') as z:
                    for n, b in files.items(): z.writestr(n, b + b'corruption')
                    z.writestr(manifest, json.dumps(info))
                with self.assertRaisesRegex(ValueError, 'Checksum mismatch'):
                    clean_archive(root / 'corrupt.zip', root / 'bad-output.zip', platform)
                self.assertFalse((root / 'bad-output.zip').exists())
