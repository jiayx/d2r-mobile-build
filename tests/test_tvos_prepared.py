import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import ci
import tvos_prepared as tv


class TVPreparedTests(unittest.TestCase):
    def test_minimal_package_integrity_and_rejection_of_platform_libraries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in tv.FILES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'{}' if name == 'legacy/pack.json' else b'fixture')
            info = {'format': tv.FORMAT, 'schema_version': 1, 'legacy_pack': {},
                    'files': {n: {'bytes': (root/n).stat().st_size, 'sha256': ci.sha256(root/n)} for n in tv.FILES}}
            (root/'manifest.json').write_text(json.dumps(info))
            tv.verify(root, check_source=False)
            (root/'romfs-inputs.zip').write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                tv.verify(root, check_source=False)
            (root/'romfs-inputs.zip').write_bytes(b'fixture')
            (root/'unneeded.metallib').write_bytes(b'MTLB')
            with self.assertRaisesRegex(ValueError, 'Unexpected'):
                tv.verify(root, check_source=False)
            info['files']['unneeded.metallib'] = {'bytes':4,'sha256':ci.sha256(root/'unneeded.metallib')}
            (root/'manifest.json').write_text(json.dumps(info))
            with self.assertRaisesRegex(ValueError, 'unused'):
                tv.verify(root, check_source=False)
