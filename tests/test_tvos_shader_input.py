import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'scripts'))
from tvos_inputs import import_shader_packs
class TVShaderInputTest(unittest.TestCase):
    def test_original_ckey_is_required_even_with_matching_package_checksums(self):
        value=b'original shader'; corrupt=b'wrong shader'
        md5=hashlib.md5(value).hexdigest()
        row=['id','0','0','3',md5,str(len(value)),'00'*16,'20','n','data:/shaders/test.bin','0']
        manifest='|'.join(row)+'\n'
        for data in (value,corrupt):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                record={'bytes':len(data),'md5':hashlib.md5(data).hexdigest(),'sha256':hashlib.sha256(data).hexdigest()}
                with zipfile.ZipFile(root/'input.zip','w') as z:
                    z.writestr('packs/test.bin',data)
                    z.writestr('manifest.json',json.dumps({'format':'d2r-mobile-tv-shaders','schema_version':1,
                        'resource_manifest_sha256':hashlib.sha256(manifest.encode()).hexdigest(),'files':{'test.bin':record}}))
                if data==value:
                    import_shader_packs(root/'input.zip',manifest,root/'packs')
                    self.assertEqual((root/'packs/test.bin').read_bytes(),value)
                else:
                    with self.assertRaisesRegex(ValueError,'checksum mismatch'):
                        import_shader_packs(root/'input.zip',manifest,root/'packs')
                    self.assertFalse((root/'packs').exists())
