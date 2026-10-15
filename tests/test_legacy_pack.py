import hashlib
import json
import os
from pathlib import Path
import plistlib
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import ci
import legacy_pack as legacy
import publish_release as publish
from test_resource_reuse import FakeGitHub, manifest


def small_pack(directory):
    directory.mkdir(parents=True, exist_ok=True)
    content = b'encoded ASTC archive'
    info = {'name': '00-00000008.data', 'size': len(content),
            'sha256': hashlib.sha256(content).hexdigest()}
    (directory / 'pack.json').write_text(json.dumps(info))
    (directory / 'pack_index.tsv').write_text('# pack\t00-00000008.data\ntexture\tentry\n')
    data = directory / 'Legacy Device Pack/data'
    data.mkdir(parents=True, exist_ok=True)
    (data / info['name']).write_bytes(content)
    (data.parent / 'manifest.json').write_text(json.dumps({'files': [info]}))
    return info


class LegacyPackTests(unittest.TestCase):
    def setUp(self):
        # Test publication must not append fake links or paths to the real runner.
        isolated = patch.dict(os.environ, {'GITHUB_ENV': '', 'GITHUB_STEP_SUMMARY': ''})
        isolated.start()
        self.addCleanup(isolated.stop)

    def test_converter_is_verified_and_cached_independently_of_app_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payloads = {name: name.encode() for name in legacy.CONVERTER_SOURCES}
            config = dict(ci.CONFIG, legacy_converter={'commit': 'a' * 40, 'sources': {
                name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()}})
            def download(url, path, digest):
                name = url.split('/' + 'a' * 40 + '/', 1)[1]
                self.assertEqual(digest, config['legacy_converter']['sources'][name])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payloads[name])
            with patch.object(legacy, 'CONVERTER', root), patch.object(ci, 'CONFIG', config), patch.object(ci, 'download', side_effect=download) as fetch:
                legacy.ensure_converter()
                self.assertEqual(fetch.call_count, 3)
                legacy.ensure_converter()
                self.assertEqual(fetch.call_count, 3)
                (root / legacy.CONVERTER_SOURCES[0]).write_bytes(b'corrupt')
                legacy.ensure_converter()
                self.assertEqual(fetch.call_count, 4)

    def test_recipe_preserves_existing_pack_identity_and_tracks_converter_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            converter = root / 'converter'
            for name in legacy.CONVERTER_SOURCES:
                path = converter / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(name)
            game = root / 'game'
            (game / 'RomFS/data').mkdir(parents=True)
            (game / 'RomFS/data/build_manifest.psv').write_text('manifest')
            original = {'format': 1, 'resource_id': legacy.export_resources.resource_identity(manifest()),
                        'build_manifest_sha256': ci.sha256(game / 'RomFS/data/build_manifest.psv'),
                        'encoder_sha256': ci.CONFIG['astc_encoder_sha256'], 'preset': 'thorough',
                        'sources': {p: ci.sha256(converter / p) for p in legacy.CONVERTER_SOURCES}}
            expected = hashlib.sha256(json.dumps(original, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            with patch.object(legacy, 'CONVERTER', converter), patch.object(ci, 'GAME', game):
                self.assertEqual(legacy.recipe(manifest()), expected)
                (converter / legacy.CONVERTER_SOURCES[-1]).write_text('different reader')
                self.assertNotEqual(legacy.recipe(manifest()), expected)

    def test_published_pack_is_restored_without_transcoding_or_uploading_again(self):
        store = FakeGitHub()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output, stage, pack = root / 'out', root / 'stage', root / 'pack'
            downloads = []
            def download(args, stdout, check):
                downloads.append(int(args[-1].rsplit('/', 1)[1]))
                stdout.write(store.content[downloads[-1]])
            env = {'GITHUB_REPOSITORY': store.repo, 'GITHUB_SHA': 'abc'}
            with patch.dict(os.environ, env), patch.object(legacy, 'ensure_converter'), patch.object(legacy, 'PACK', pack), patch.object(publish, 'OUT', output), patch.object(publish, 'STAGE', stage), patch.object(legacy.export_resources, 'scan_resources', return_value=manifest()), patch.object(legacy, 'recipe', return_value='a' * 64), patch.object(legacy, 'generate', side_effect=lambda: small_pack(pack)) as generate, patch.object(publish, 'gh', side_effect=store.gh), patch.object(publish, 'release_info', side_effect=lambda repo, tag: store.releases.get(tag)), patch.object(publish.subprocess, 'check_output', side_effect=store.download), patch.object(legacy.subprocess, 'run', side_effect=download):
                legacy.main()
                first = json.loads((output / 'legacy-resources.json').read_text())
                self.assertIsNone(store.latest)
                uploads = len([c for c in store.calls if c[:2] == ('release', 'upload')])
                (pack / 'Legacy Device Pack/data/00-00000008.data').unlink()
                legacy.main()
                self.assertEqual(first, json.loads((output / 'legacy-resources.json').read_text()))
                self.assertEqual(json.loads((pack / 'pack.json').read_text()), first['pack'])
                self.assertFalse((pack / 'Legacy Device Pack/data/00-00000008.data').exists())
                self.assertEqual(set(downloads), {a['id'] for a in first['assets'] if a['name'] in ('pack.json', 'pack_index.tsv')})
                generate.assert_called_once()
                self.assertEqual(uploads, len([c for c in store.calls if c[:2] == ('release', 'upload')]))
                with zipfile.ZipFile(stage / legacy.ZIP_NAME) as z:
                    self.assertEqual(set(z.namelist()), {'Legacy Device Pack/manifest.json', 'Legacy Device Pack/data/00-00000008.data'})
                release = store.releases[first['source_release']['tag']]
                index = next(a for a in release['assets'] if a['name'] == 'pack_index.tsv')
                index['digest'] = 'sha256:' + '0' * 64
                self.assertIsNone(legacy.reference(store.repo, release, 'a' * 64))

    def test_corrupt_payload_and_wrong_phone_manifest_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            small_pack(root)
            (root / 'Legacy Device Pack/manifest.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'manifest differs'):
                legacy.validate_pack(root)
            small_pack(root)
            (root / 'Legacy Device Pack/data/00-00000008.data').write_bytes(b'wrong')
            with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
                legacy.validate_pack(root)

    def test_restore_requires_exactly_two_metadata_assets(self):
        for assets in ([], [{'name': 'pack.json'}],
                       [{'name': 'pack.json'}, {'name': 'pack.json'}, {'name': 'pack_index.tsv'}]):
            with self.assertRaisesRegex(ValueError, 'metadata missing or duplicated'):
                legacy.restore('owner/repo', {'assets': assets})

    def test_ipa_verification_checks_system_and_paired_overlay(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            info = small_pack(root / 'pack')
            shell = root / 'shell.ipa'
            entries = {'Payload/Game.app/dm/shell_info.txt': b'PRODUCT=test\nCHAIN=chain\nSHADER_SRC=source\n',
                       'Payload/Game.app/dm/shell_manifest.txt': b'Frameworks/Guest.framework/\n',
                       'Payload/Game.app/Info.plist': plistlib.dumps({'MinimumOSVersion': '18.0', 'CFBundleExecutable': 'Game'}),
                       'Payload/Game.app/Game': struct.pack('<8I6I', 0xfeedfacf, 0x0100000c, 0, 2, 1, 24, 0, 0,
                                                            0x32, 24, 2, 18 << 16, 18 << 16, 0)}
            with zipfile.ZipFile(shell, 'w') as z:
                for n, b in entries.items(): z.writestr(n, b)
            entries.update({'Payload/Game.app/Frameworks/Guest.framework/Guest': struct.pack('<II', 0xfeedfacf, 0x0100000c),
                            'Payload/Game.app/dm/pack_info.txt': b'PRODUCT=test\n',
                            'Payload/Game.app/msl/b-chain/test_b.metallib': b'source',
                            'Payload/Game.app/romfs_overlay_astc/pack.json': (root / 'pack/pack.json').read_bytes(),
                            'Payload/Game.app/romfs_overlay_astc/data/a.data': b'overlay',
                            'Payload/Game.app/romfs_overlay_astc_variants/pad/data/a.data': b'overlay'})
            ipa = root / 'game.ipa'
            with zipfile.ZipFile(ipa, 'w') as z:
                for n, b in entries.items(): z.writestr(n, b)
            report = ci.verify_ipa(ipa, shell, '18.0', root / 'pack')
            self.assertEqual(report['minimum_os'], '18.0')
            self.assertTrue(report['native_matches_shell'])
            self.assertEqual(report['native_minimum_os'], '18.0.0')
            self.assertTrue(report['compatibility_no_metal4'])
            self.assertTrue(report['pack_info_verified'])
            self.assertEqual(report['pack_product'], 'test')
            for record in (None, b'PRODUCT=wrong\n', b'invalid', b'PRODUCT=test\nPRODUCT=test\n', b'\xff'):
                with self.subTest(pack_info=record):
                    invalid = dict(entries)
                    if record is None:
                        invalid.pop('Payload/Game.app/dm/pack_info.txt')
                    else:
                        invalid['Payload/Game.app/dm/pack_info.txt'] = record
                    with zipfile.ZipFile(ipa, 'w') as z:
                        for n, b in invalid.items(): z.writestr(n, b)
                    with self.assertRaisesRegex(ValueError, 'pack metadata'):
                        ci.verify_ipa(ipa, shell, '18.0', root / 'pack')
            with zipfile.ZipFile(ipa, 'w') as z:
                for n, b in entries.items(): z.writestr(n, b)
            with self.assertRaisesRegex(ValueError, 'minimum system'):
                ci.verify_ipa(ipa, shell, '26.0', root / 'pack')
            (root / 'pack/pack.json').write_text(json.dumps(dict(info, sha256='0' * 64)))
            with self.assertRaisesRegex(ValueError, 'does not match'):
                ci.verify_ipa(ipa, shell, '18.0', root / 'pack')

    def test_ipa_rejects_modified_native_or_incompatible_official_executable(self):
        def native(minimum=18, extra=b''):
            return struct.pack('<8I6I', 0xfeedfacf, 0x0100000c, 0, 2, 1, 24, 0, 0,
                               0x32, 24, 2, minimum << 16, minimum << 16, 0) + extra

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = 'Payload/Game.app/'
            entries = {base + 'Info.plist': plistlib.dumps({'MinimumOSVersion': '18.0', 'CFBundleExecutable': 'Game'}),
                       base + 'dm/shell_info.txt': b'PRODUCT=test\nCHAIN=chain\nSHADER_SRC=source\n',
                       base + 'dm/shell_manifest.txt': b'Frameworks/Guest.framework/\n',
                       base + 'Frameworks/Guest.framework/Guest': struct.pack('<II', 0xfeedfacf, 0x0100000c),
                       base + 'msl/b-chain/test_b.metallib': b'source'}
            for official, packaged, error in (
                    (native(), native(extra=b'changed'), 'differs from official shell'),
                    (native(26), native(26), 'minimum system differs'),
                    (native(extra=b'MTL4CommandQueue'), native(extra=b'MTL4CommandQueue'), 'references Metal 4')):
                with self.subTest(error=error):
                    for name, binary in (('shell.ipa', official), ('game.ipa', packaged)):
                        with zipfile.ZipFile(root / name, 'w') as z:
                            for key, value in dict(entries, **{base + 'Game': binary}).items():
                                z.writestr(key, value)
                    with self.assertRaisesRegex(ValueError, error):
                        ci.verify_ipa(root / 'game.ipa', root / 'shell.ipa', '18.0')

    def test_publication_rejects_missing_variant_and_modified_ipa(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(publish, 'OUT', root):
                with self.assertRaisesRegex(ValueError, 'Both verified'):
                    publish.validate_packages({'packages': []})
                packages = []
                for name, minimum, key in ((ci.ipa_names()[0], '26.0', 'shell_sha256'),
                                           (ci.ipa_names()[1], '18.0', 'ios18_shell_sha256')):
                    (root / name).write_bytes(b'ipa')
                    packages.append(dict({k: ci.CONFIG[k] for k in ('upstream_commit', 'game_version', 'switch_version')},
                                         ipa_name=name, minimum_os=minimum, shell_sha256=ci.CONFIG[key],
                                         ipa_bytes=3, ipa_sha256=ci.sha256(root / name)))
                (root / 'SHA256SUMS.txt').write_text(''.join(f"{p['ipa_sha256']}  {p['ipa_name']}\n" for p in packages))
                self.assertEqual(len(publish.validate_packages({'packages': packages})), 2)
                (root / packages[1]['ipa_name']).write_bytes(b'bad')
                with self.assertRaisesRegex(ValueError, 'IPA SHA256 mismatch'):
                    publish.validate_packages({'packages': packages})
