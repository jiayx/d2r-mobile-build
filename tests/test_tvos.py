"""Prevent publishing an iOS/simulator binary as a TV build."""
import os
from pathlib import Path
import plistlib
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import tvos
import tvos_inputs
import io
import zipfile


class TVBuildTests(unittest.TestCase):
    def test_reject_other_platform_and_missing_runtime_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary)
            config = {'app_version': '2.1.0', 'build_number': '1.1'}
            info = dict(CFBundleExecutable='DmTV', MinimumOSVersion='26.0',
                        UIDeviceFamily=[3], CFBundleSupportedPlatforms=['AppleTVOS'],
                        CFBundleShortVersionString='2.1.0', CFBundleVersion='1.1')
            (app / 'Info.plist').write_bytes(plistlib.dumps(info))
            header = struct.pack('<8I', 0xfeedfacf, 0x0100000c, 0, 2, 1, 24, 0, 0)
            def binary(platform):
                (app / 'DmTV').write_bytes(header + struct.pack('<6I', 0x32, 24, platform, 26 << 16, 26 << 16, 0))
            for platform in (2, 7, 8):
                binary(platform)
                with self.assertRaisesRegex(ValueError, 'wrong platform'):
                    tvos.verify_app(app, config)
            binary(3)
            with self.assertRaisesRegex(ValueError, 'resources are incomplete'):
                tvos.verify_app(app, config)
            for name in ('dm/main.fixups.tsv', 'dm/main.gates.tsv', 'dm/shader_map.tsv',
                         'dm/pso_manifest.tsv', 'dm/c1_full.tsv', 'romfs_overlay/data/.build.config'):
                p = app / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('data')
            tvos.verify_app(app, config)
            (app / 'embedded.mobileprovision').write_text('unexpected profile')
            with self.assertRaisesRegex(ValueError, 'provisioning profile'):
                tvos.verify_app(app, config)

class SplitArchiveTests(unittest.TestCase):
    def test_zip_reads_across_part_boundaries(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('data/test', b'original shader' * 200)
        data = stream.getvalue()
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for i, part in enumerate((data[:21], data[21:87], data[87:])):
                p = Path(directory) / str(i); p.write_bytes(part); paths.append(p)
            with zipfile.ZipFile(tvos_inputs.SplitReader(paths)) as z:
                self.assertEqual(z.read('data/test'), b'original shader' * 200)
            with zipfile.ZipFile(tvos_inputs.SplitReader(paths[::-1])) as z:
                with self.assertRaises(Exception):
                    z.read('data/test')
