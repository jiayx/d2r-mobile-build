"""Compile the complete native iOS runtime on macOS; add the matching generated payload."""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import stat
import subprocess
import sys
import zipfile
import time
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ci
from source.metal import verify_payload


def run(*args, **kwargs):
    return subprocess.check_output([str(a) for a in args],text=True,**kwargs)


def prepare_project(ios, payload, project, flags):
    """Restore prepared resources into the original project's resource folders."""
    target = project['targets']['DmIOS']
    sources = target['sources']
    directories = {Path(s['path']).name: ios / s['path'] for s in sources
                   if isinstance(s, dict) and s.get('type') == 'folder'}
    # Upstream creates these empty when development test saves are not supplied.
    for name in ('save_ref', 'save_ref_warlock'):
        if name in directories:
            directories[name].mkdir(parents=True, exist_ok=True)
    art = ios / 'Sources/TouchArt'
    art.mkdir(parents=True, exist_ok=True)
    dm = ios.parent
    resources = {f'dm/{name}': dm / 'gfx/nvn' / name
                 for name in ('shader_map.tsv', 'pso_manifest.tsv')}
    resources['dm/asset_pointers.txt'] = ios / 'asset_pointers.txt'
    # Keep handwritten art from the selected source, rather than an older prepared package.
    resources.update({p.name: p for p in art.rglob('*')
                      if p.is_file() and p.name != 'native_art_manifest.json'})
    for name, path in resources.items():
        if not path.is_file() or not path.stat().st_size:
            raise ValueError('Missing upstream runtime resource: ' + name)
    base = 'Payload/DmIOS.app/'
    extras = set()
    with zipfile.ZipFile(payload) as src:
        for item in src.infolist():
            if not item.filename.startswith(base) or '..' in item.filename.split('/'):
                raise ValueError('Unexpected generated payload path')
            name = item.filename.removeprefix(base)
            if item.is_dir() or name == 'Info.plist' or name in resources:
                continue
            parts = Path(name).parts
            if len(parts) == 1:
                destination = art / name
            else:
                directory = directories.get(parts[0])
                if directory is None:
                    directory = ios / 'Gen/prepared' / parts[0]
                    extras.add(parts[0])
                destination = directory.joinpath(*parts[1:])
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(src.read(item))
            destination.chmod(stat.S_IMODE(item.external_attr >> 16) or 0o644)
    for name in sorted(extras):
        sources.append({'path': 'Gen/prepared/' + name, 'type': 'folder', 'buildPhase': 'resources'})
    for name, path in resources.items():
        if name.startswith('dm/'):
            shutil.copy2(path, directories['dm'] / Path(name).name)
    for name, directory in directories.items():
        if name not in ('save_ref', 'save_ref_warlock') and not any(p.is_file() for p in directory.rglob('*')):
            raise ValueError('Prepared input is missing upstream resource folder: ' + name)
    manifest = directories['dm'] / 'shell_manifest.txt'
    manifest.write_text('\n'.join(dict.fromkeys([*manifest.read_text().splitlines(), *resources])) + '\n')
    # Only the game-resource generation hook is replaced; other upstream build hooks remain.
    target['preBuildScripts'] = [s for s in target.get('preBuildScripts', [])
                                 if 'tools/gen_assets.py' not in s.get('script', '')]
    (ios / 'Gen/embed.S').write_text('// Game modules are loaded from Guest.framework (DM_SHELL).\n')
    flags = flags.replace('OTHER_CFLAGS = $(inherited)', 'OTHER_CFLAGS = $(inherited) -DDM_SHELL')
    (ios / 'Gen/dm.xcconfig').write_text(flags + '\nOTHER_LDFLAGS = $(inherited) $(DM_FRAMEWORKS)\n')
    return {name: ci.sha256(path) for name, path in resources.items()}


MEMORY_ENTITLEMENT = 'com.apple.developer.kernel.increased-memory-limit'


def sign_memory_request(app):
    """Carry a request for re-signers; this is not an installable provisioning signature."""
    requested = {MEMORY_ENTITLEMENT: True}
    with tempfile.TemporaryDirectory() as directory:
        entitlements = Path(directory) / 'memory.plist'
        entitlements.write_bytes(plistlib.dumps(requested))
        subprocess.run(['codesign', '--force', '--sign', '-', '--entitlements', str(entitlements),
                        '--generate-entitlement-der', str(app)], check=True)
    actual = plistlib.loads(subprocess.check_output(
        ['codesign', '--display', '--entitlements', ':-', str(app)]))
    if actual != requested:
        raise ValueError('App signature does not carry the requested memory entitlement')
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    return actual


def package_ipa(app, payload, destination, resources, *, memory_request=False):
    """Archive the complete built app, then verify its prepared and source resources."""
    base = 'Payload/DmIOS.app/'
    guest_name = 'Frameworks/Guest.framework/Guest'
    guest = app / guest_name
    with zipfile.ZipFile(payload) as prepared:
        if guest.read_bytes() != prepared.read(base + guest_name):
            raise ValueError('Generated Guest changed before signing')
    # Give re-signers such as zsign an existing LC_CODE_SIGNATURE to replace.
    subprocess.run(['codesign', '-f', '-s', '-', str(guest)], check=True)
    subprocess.run(['codesign', '--verify', '--strict', str(guest)], check=True)
    guest_sha256 = ci.sha256(guest)
    if memory_request:
        sign_memory_request(app)
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for path in sorted(app.rglob('*')):
            relative = path.relative_to(app)
            guest_framework = relative.parts[:2] == ('Frameworks', 'Guest.framework')
            if (path.is_file() and path.name != 'embedded.mobileprovision'
                    and ('_CodeSignature' not in relative.parts or guest_framework or memory_request)):
                archive.write(path, base + relative.as_posix())
    with zipfile.ZipFile(destination) as final, zipfile.ZipFile(payload) as prepared:
        for name in prepared.namelist():
            if (not name.endswith('/') and name not in (base + 'Info.plist', base + 'dm/shell_manifest.txt', base + guest_name)
                    and name.removeprefix(base) not in resources and final.read(name) != prepared.read(name)):
                raise ValueError('Generated payload changed or missing: ' + name)
        if hashlib.sha256(final.read(base + guest_name)).hexdigest() != guest_sha256:
            raise ValueError('Signed Guest changed during IPA packaging')
        for name, digest in resources.items():
            if hashlib.sha256(final.read(base + name)).hexdigest() != digest:
                raise ValueError('Upstream runtime resource changed or missing: ' + name)
        manifest = final.read(base + 'dm/shell_manifest.txt').decode().splitlines()
        if not resources.keys() <= set(manifest):
            raise ValueError('Runtime resources missing from the launch manifest')
    return guest_sha256


def main():
    import yaml

    step_started = time.monotonic()
    minimum=sys.argv[1]
    if minimum not in ('26.0','18.0'):raise ValueError('Unsupported system variant')
    root=ci.ROOT; ios=root/'upstream/dm/ios'; gen=ios/'Gen'
    report=json.loads((root/'outputs/source-input-report.json').read_text())
    payload=root/'outputs/source-payload.zip'
    if ci.sha256(payload)!=report['payload_sha256']:raise ValueError('Payload checksum mismatch')
    verify_payload(payload, report)
    if f'#define DMSH_CHAIN "{report["shader_chain"]}"' not in (root/'upstream/dm/gfx/nvn/dmsh_chain.h').read_text():
        raise ValueError('Native shader chain differs from compiled libraries')
    shutil.rmtree(gen,ignore_errors=True);gen.mkdir()
    flags=run(sys.executable,ios/'tools/gen_build.py',ios.parent/'host',gen)
    # Keep the complete upstream project and its free-account / iOS 18 transformations.
    free=ios/'source-free.yml'
    run(sys.executable,ios/'tools/project_free.py',ios/'project.yml',free)
    spec=free
    if minimum=='18.0':
        spec=ios/'source-m3.yml'
        run(sys.executable,ios/'tools/project_m3.py',free,spec,'free')
    text=spec.read_text().replace('${DM_BUNDLE_ID}','org.d2rmobile.app').replace('${DM_TEAM_ID}','0000000000')
    project=yaml.safe_load(text)
    resources=prepare_project(ios, payload, project, flags)
    (ios/'source-build.yml').write_text(yaml.safe_dump(project,sort_keys=False))
    run('xcodegen','generate','--spec','source-build.yml',cwd=ios)
    project_prepare_seconds=round(time.monotonic()-step_started,2)
    derived=root/'native-build'
    started=time.monotonic()
    subprocess.run(['xcodebuild','-project',project['name']+'.xcodeproj','-scheme','DmIOS','-configuration','Release',
                    '-sdk','iphoneos','-destination','generic/platform=iOS','-derivedDataPath',str(derived),
                    'CODE_SIGNING_ALLOWED=NO','CODE_SIGNING_REQUIRED=NO','CLANG_ENABLE_MODULES=YES',
                    'DM_DEVICE_FAMILY=1,2','DM_BUILD_NUMBER='+ci.CONFIG['build_number'],
                    'MARKETING_VERSION='+ci.CONFIG['app_version'],'DM_UPDATE_URL=',
                    'COMPRESS_PNG_FILES=NO','STRIP_PNG_TEXT=NO',
                    'COMPILER_INDEX_STORE_ENABLE=NO','CLANG_MODULE_CACHE_PATH='+str(root/'.native-module-cache'),
                    'build'],cwd=ios,check=True)
    native_seconds=round(time.monotonic()-started,2)
    app=derived/'Build/Products/Release-iphoneos/DmIOS.app'
    plist=plistlib.loads((app/'Info.plist').read_bytes());native=(app/plist['CFBundleExecutable']).read_bytes()
    native_os=ci.macho_minimum_os(native)
    if plist['MinimumOSVersion']!=minimum or native_os!=(int(minimum.split('.')[0]),0,0):
        raise ValueError('Compiled app targets wrong minimum iOS')
    if (plist['CFBundleVersion']!=ci.CONFIG['build_number'] or
            plist['CFBundleShortVersionString']!=ci.CONFIG['app_version']):
        raise ValueError('Compiled app version differs from selected source')
    if minimum=='18.0' and b'MTL4CommandQueue' in native:raise ValueError('Compatibility build references Metal 4')
    suffix='-ios18' if minimum=='18.0' else ''
    name=ci.ipa_names()[minimum=='18.0']
    destination=root/'outputs'/name
    base='Payload/DmIOS.app/'
    package_started=time.monotonic()
    guest_sha256 = package_ipa(app, payload, destination, resources, memory_request=True)
    native = (app / plist['CFBundleExecutable']).read_bytes()
    with zipfile.ZipFile(destination) as final:
        if final.read(base+plist['CFBundleExecutable'])!=native:
            raise ValueError('Native executable changed during IPA packaging')
    verify_payload(destination, report)
    report.update(ipa_name=name,ipa_sha256=ci.sha256(destination),ipa_bytes=destination.stat().st_size,
                  game_version=ci.CONFIG['game_version'],
                  switch_version=ci.CONFIG['switch_version'],input_revision=os.environ.get('INPUT_REVISION'),
                  minimum_os=minimum,native_minimum_os='.'.join(map(str,native_os)),native_sha256=hashlib.sha256(native).hexdigest(),
                  app_version=ci.CONFIG['app_version'],build_number=ci.CONFIG['build_number'],
                  release_tag=ci.CONFIG['release_tag'],
                  native_built_from_source=True,payload_verified=True,device_tested=False,signed=False,
                  guest_signature='ad-hoc',guest_sha256=guest_sha256,
                  app_signature='ad-hoc',requested_entitlements={MEMORY_ENTITLEMENT: True},
                  entitlement_signature_verified=True,requires_resigning=True,
                  runtime_resources_sha256=resources,
                  upstream_project=True,project_prepare_seconds=project_prepare_seconds,
                  ipa_package_seconds=round(time.monotonic()-package_started,2),
                  native_step_seconds=round(time.monotonic()-step_started,2),
                  native_build_seconds=native_seconds,
                  native_module_cache_hit=os.environ.get('NATIVE_MODULE_CACHE_HIT')=='true',
                  xcode=run('xcodebuild','-version').strip(),sdk=run('xcrun','--sdk','iphoneos','--show-sdk-version').strip())
    (root/'outputs'/f'source{suffix}-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
