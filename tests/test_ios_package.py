import copy
import plistlib
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from source.build import package_ipa, prepare_project, sign_memory_request, MEMORY_ENTITLEMENT
from source.metal import verify_payload
from fixtures import BASE, package


def project():
    return {'name': 'DmIOS', 'configFiles': {'Release': 'Gen/dm.xcconfig'},
            'targets': {'DmIOS': {
                'sources': ['Sources', 'Assets.xcassets',
                            {'path': 'Gen/assets/NativeHUD/v4/hud_v4_ui', 'type': 'folder'},
                            *({'path': 'Gen/' + n, 'type': 'folder'} for n in
                              ('dm', 'msl', 'romfs_overlay_astc', 'save_ref', 'save_ref_warlock')),
                            {'path': 'Gen/main/main.c', 'compilerFlags': '-Dmain=dm_main'}],
                'settings': {'OTHER_CFLAGS': '$(inherited) -mcpu=apple-a14 -DDM_NVN_M3=1'},
                'dependencies': [{'sdk': 'Network.framework'}],
                'entitlements': {'path': 'Sources/DmIOS.entitlements', 'properties': {'group': ['app']}},
                'preBuildScripts': [{'script': 'python3 "$SRCROOT/tools/gen_assets.py"'},
                                    {'script': 'echo upstream hook'}]},
                        'SmokeTests': {'type': 'bundle.ui-testing'}},
            'schemes': {'DmIOS': {'build': {'targets': {'DmIOS': 'all', 'SmokeTests': ['test']}}}}}


class IOSPackageTests(unittest.TestCase):
    def test_upstream_project_resources_survive_staging_build_and_packaging(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            upstream, prepared, info = package(root)
            ios = upstream / 'dm/ios'
            (ios / 'Gen').mkdir()
            art = ios / 'Sources/TouchArt'
            art.mkdir(parents=True)
            (art / 'dm_touch_joy.png').write_bytes(b'current source joystick')
            (art / 'native_art_manifest.json').write_bytes(b'source placeholder')
            payload = prepared / 'source-payload.zip'
            with zipfile.ZipFile(payload, 'a') as archive:
                archive.writestr(BASE + 'romfs_overlay_astc/pack.json', '{}')
                archive.writestr(BASE + 'Info.plist', b'prepared metadata')
                archive.writestr(BASE + 'native_art_manifest.json', b'prepared art metadata')
                archive.writestr(BASE + 'dm_touch_joy.png', b'old joystick')
                archive.writestr(BASE + 'hud_v4_ui/ui.json', b'prepared HUD')
                archive.writestr(BASE + 'Licenses/upstream.txt', b'upstream license')
            spec = project()
            original = copy.deepcopy(spec)
            resources = prepare_project(ios, payload, spec, 'OTHER_CFLAGS = $(inherited) -DFIXTURE\n')
            self.assertEqual(spec['targets']['DmIOS']['sources'][:len(original['targets']['DmIOS']['sources'])],
                             original['targets']['DmIOS']['sources'])
            for field in ('settings', 'dependencies', 'entitlements'):
                self.assertEqual(spec['targets']['DmIOS'][field], original['targets']['DmIOS'][field])
            self.assertEqual(spec['schemes'], original['schemes'])
            self.assertEqual(spec['targets']['SmokeTests'], original['targets']['SmokeTests'])
            self.assertEqual(spec['targets']['DmIOS']['preBuildScripts'], [{'script': 'echo upstream hook'}])
            self.assertIn('-DDM_SHELL -DFIXTURE', (ios / 'Gen/dm.xcconfig').read_text())
            self.assertEqual((ios / 'Gen/assets/NativeHUD/v4/hud_v4_ui/ui.json').read_bytes(), b'prepared HUD')
            self.assertEqual((art / 'native_art_manifest.json').read_bytes(), b'prepared art metadata')
            self.assertTrue((ios / 'Gen/save_ref').is_dir())
            app = root / 'DmIOS.app'
            app.mkdir()
            # Model Xcode's folder-resource copies; real Xcode coverage runs in Actions.
            for source in spec['targets']['DmIOS']['sources']:
                if isinstance(source, dict) and source.get('type') == 'folder':
                    path = ios / source['path']
                    shutil.copytree(path, app / path.name)
            for path in art.iterdir():
                shutil.copy2(path, app / path.name)
            (app / 'DmIOS').write_bytes(b'compiled executable')
            (app / 'Info.plist').write_bytes(b'compiled app metadata')
            destination = root / 'test.ipa'
            guest = app / 'Frameworks/Guest.framework/Guest'
            unsigned_guest = guest.read_bytes()
            def codesign(command, *, check):
                self.assertTrue(check)
                if command[1] == '-f':
                    self.assertEqual(command, ['codesign', '-f', '-s', '-', str(guest)])
                    guest.write_bytes(unsigned_guest + b'fixture ad-hoc signature')
                    signature = guest.parent / '_CodeSignature/CodeResources'
                    signature.parent.mkdir(exist_ok=True)
                    signature.write_bytes(b'framework signature resources')
                else:
                    self.assertEqual(command, ['codesign', '--verify', '--strict', str(guest)])
            (app / '_CodeSignature').mkdir()
            (app / '_CodeSignature/CodeResources').write_bytes(b'outer app signature')
            with patch('source.build.subprocess.run', side_effect=codesign), patch('source.build.sign_memory_request') as sign_main:
                package_ipa(app, payload, destination, resources, memory_request=True)
                sign_main.assert_called_once_with(app)
            verify_payload(destination, info['payload'])
            with zipfile.ZipFile(destination) as archive:
                self.assertEqual(archive.read(BASE + 'DmIOS'), b'compiled executable')
                self.assertEqual(archive.read(BASE + 'Info.plist'), b'compiled app metadata')
                self.assertEqual(archive.read(BASE + 'dm/shader_map.tsv'), b'fixture shader map\n')
                self.assertEqual(archive.read(BASE + 'dm/pso_manifest.tsv'), b'# fixture pipeline seed\n')
                self.assertEqual(archive.read(BASE + 'dm/asset_pointers.txt'), b'# fixture download pointers\n')
                self.assertEqual(archive.read(BASE + 'dm_touch_joy.png'), b'current source joystick')
                self.assertEqual(archive.read(BASE + 'Licenses/upstream.txt'), b'upstream license')
                self.assertEqual(archive.read(BASE + 'Frameworks/Guest.framework/Guest'),
                                 unsigned_guest + b'fixture ad-hoc signature')
                self.assertEqual(archive.read(BASE + 'Frameworks/Guest.framework/_CodeSignature/CodeResources'),
                                 b'framework signature resources')
                self.assertEqual(archive.read(BASE + '_CodeSignature/CodeResources'), b'outer app signature')
                self.assertTrue(resources.keys() <= set(archive.read(BASE + 'dm/shell_manifest.txt').decode().splitlines()))
                self.assertEqual(len(archive.namelist()), len(set(archive.namelist())))
            (app / 'dm/shader_map.tsv').write_bytes(b'corrupt')
            guest.write_bytes(unsigned_guest)
            with patch('source.build.subprocess.run', side_effect=codesign), self.assertRaisesRegex(ValueError, 'runtime resource changed'):
                package_ipa(app, payload, destination, resources)

    def test_memory_signature_rejects_missing_or_extra_entitlements(self):
        for actual in ({}, {MEMORY_ENTITLEMENT: False}, {MEMORY_ENTITLEMENT: True, 'get-task-allow': True}):
            with patch('source.build.subprocess.run'), patch('source.build.subprocess.check_output', return_value=plistlib.dumps(actual)):
                with self.assertRaisesRegex(ValueError, 'memory entitlement'):
                    sign_memory_request(Path('/fixture.app'))

    def test_memory_signature_requests_only_increased_limit(self):
        requested = {MEMORY_ENTITLEMENT: True}
        commands = []
        def execute(command, *, check):
            commands.append(command)
            if '--entitlements' in command:
                self.assertEqual(plistlib.loads(Path(command[command.index('--entitlements') + 1]).read_bytes()), requested)
        with patch('source.build.subprocess.run', side_effect=execute), patch('source.build.subprocess.check_output', return_value=plistlib.dumps(requested)):
            self.assertEqual(sign_memory_request(Path('/fixture.app')), requested)
        self.assertIn('--generate-entitlement-der', commands[0])
        self.assertEqual(commands[-1], ['codesign', '--verify', '--deep', '--strict', '/fixture.app'])

    def test_missing_upstream_table_or_new_resource_folder_stops_preparation(self):
        for missing in ('table', 'folder'):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                upstream, prepared, _ = package(root)
                ios = upstream / 'dm/ios'
                (ios / 'Gen').mkdir()
                spec = project()
                with zipfile.ZipFile(prepared / 'source-payload.zip', 'a') as archive:
                    archive.writestr(BASE + 'romfs_overlay_astc/pack.json', '{}')
                if missing == 'table':
                    (upstream / 'dm/gfx/nvn/shader_map.tsv').unlink()
                    message = 'Missing upstream runtime resource: dm/shader_map.tsv'
                else:
                    spec['targets']['DmIOS']['sources'].pop(2)  # This fixture has no HUD data.
                    spec['targets']['DmIOS']['sources'].append({'path': 'Gen/new_resource', 'type': 'folder'})
                    message = 'missing upstream resource folder: new_resource'
                with self.assertRaisesRegex(ValueError, message):
                    prepare_project(ios, prepared / 'source-payload.zip', spec, 'OTHER_CFLAGS = $(inherited)\n')
