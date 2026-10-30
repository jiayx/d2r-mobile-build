"""Experimental tvOS packaging through upstream's device build entry point."""
import json
import hashlib
import shutil
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import zipfile

import ci
from archive_input import extract
from input_config import input_identity, settings
from source import prepared
import macos
import tvos_inputs
from source.publish import gh, release_info, upload_verified


def plan():
    data = tvos_inputs.configuration()
    identity = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    with open(os.environ['GITHUB_OUTPUT'], 'a') as out:
        out.write('input_revision=' + identity + '\n')


def configure_project(path, config):
    import yaml
    project = yaml.safe_load(path.read_text())
    target = project['targets']['DmTV']
    if target['platform'] != 'tvOS' or str(target['deploymentTarget']) != '26.0':
        raise ValueError('Review the changed upstream tvOS target before building')
    target['settings'].update(MARKETING_VERSION=config['app_version'],
                              CURRENT_PROJECT_VERSION=config['build_number'])
    path.write_text(yaml.safe_dump(project, sort_keys=False))


def verify_app(app, config):
    info = plistlib.loads((app / 'Info.plist').read_bytes())
    native = (app / info['CFBundleExecutable']).read_bytes()
    if (info['MinimumOSVersion'] != '26.0' or info['UIDeviceFamily'] != [3]
            or info['CFBundleSupportedPlatforms'] != ['AppleTVOS']
            or ci.macho_minimum_os(native, platform=3) != (26, 0, 0)
            or info['CFBundleShortVersionString'] != config['app_version']
            or info['CFBundleVersion'] != config['build_number']):
        raise ValueError('tvOS platform, minimum system or version mismatch')
    if (app / 'embedded.mobileprovision').exists():
        raise ValueError('Unexpected provisioning profile in unsigned tvOS package')
    required = ('dm/main.fixups.tsv', 'dm/main.gates.tsv', 'dm/shader_map.tsv',
                'dm/pso_manifest.tsv', 'dm/c1_full.tsv', 'romfs_overlay/data/.build.config')
    if any(not (app / name).is_file() for name in required):
        raise ValueError('tvOS runtime resources are incomplete')
    return info


def build():
    root = ci.ROOT
    dm = root / 'upstream/dm'
    work = root / '.tvos-work'
    macos.import_prepared()
    mac = root / '.macos-prepared'
    mac_info = macos.load_prepared()
    inputs = root / '.tvos-ios-input'
    extract(root / '.prepared-downloads/prepared-input.archive', inputs)
    info = prepared.verify_directory(inputs)
    if info['nso_sha256'] != ci.CONFIG['nso_sha256']:
        raise ValueError('Legacy metadata belongs to different game programs')
    # Only Legacy pack metadata is reused; Apple binary libraries are NOT retargeted.
    environment = dict(os.environ, DM_ROOT=str(work),
                       DM_ASTC_PACK=str(inputs / 'legacy'), DM_TV_NOSIGN='1',
                       DM_TEAM_ID='0000000000', DM_BUNDLE_ID='org.d2rmobile.app')
    paths = tvos_inputs.download()
    romfs, packs = tvos_inputs.extract_shader_packs(dm, mac, work, paths, environment)
    environment['DM_ROMFS_SRC'] = str(romfs)
    product = work / 'build/cache/dm/out' / (mac_info['product'] + '-touch')
    shutil.copytree(mac / 'product', product, dirs_exist_ok=True)
    environment['DM_OUT'] = str(product)
    translator = work / 'build/gfx/dmsh_xlate'
    subprocess.run(['dotnet', 'publish', str(dm / 'gfx/tools/dmsh_xlate'), '-c', 'Release',
                    '-o', str(translator), '-v', 'quiet'], env=environment, check=True)
    for flag in ('--update-lock', '--header'):
        subprocess.run([sys.executable, str(dm / 'gfx/tools/dmsh_chain.py'), flag],
                       env=environment, check=True)
    shader_cache = work / 'build/cache/metal_shader_cache'
    environment['IOSOUT'] = str(work / 'build/ios/dmsh_b')
    subprocess.run([sys.executable, str(root / 'scripts/tvos_inputs.py'), 'translate',
                    str(dm), str(product), str(packs), str(shader_cache)], env=environment, check=True)
    chain = subprocess.check_output([sys.executable, str(dm / 'gfx/tools/dmsh_chain.py')],
                                    env=environment, text=True).strip()
    subprocess.run([sys.executable, str(dm / 'gfx/tools/c1_guard.py'),
                    str(shader_cache / ('b-' + chain)), str(dm / 'gfx/nvn/c1_full.tsv')],
                   env=environment, check=True)
    python_dir = Path(sys.executable).parent
    configure_project(dm / 'ios/project.yml', ci.CONFIG)
    subprocess.run(['bash', str(dm / 'tvos/build.sh')], env=environment, check=True)
    overlay = work / 'tv-overlay/romfs_overlay'
    subprocess.run([str(python_dir / 'python3'), str(dm / 'tvos/gen_romfs_overlay.py'),
                    str(romfs), str(overlay)], env=environment, check=True)
    astc = overlay.with_name('romfs_overlay_astc')
    if not (astc / 'data/.build.config').is_file() or not (astc / 'pack.json').is_file():
        raise ValueError('Required TV Legacy overlay was not generated')
    app = work / 'run/tvos/dd/Build/Products/Release-appletvos/DmTV.app'
    verify_app(app, ci.CONFIG)
    # Compare all compiled shader outputs with the app, including reflection files.
    chain = subprocess.check_output([str(python_dir / 'python3'), str(dm / 'gfx/tools/dmsh_chain.py')],
                                    env=environment, text=True).strip()
    shaders = work / 'build/tvos/msl' / ('b-' + chain)
    libs = list(shaders.glob('*.metallib'))
    if not libs:
        raise ValueError('No tvOS Metal libraries generated')
    for source in shaders.iterdir():
        if source.suffix in ('.json', '.metallib'):
            if ci.sha256(source) != ci.sha256(app / 'msl' / shaders.name / source.name):
                raise ValueError('tvOS shader missing or changed during packaging')
    out = root / 'outputs'
    tag = ci.release_tag() + '-tvos'
    ipa = out / ('D2RMobile-' + tag + '.ipa')
    with zipfile.ZipFile(ipa, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as z:
        for path in sorted(app.rglob('*')):
            if path.is_symlink():
                raise ValueError('App still contains an external symlink')
            if path.is_file():
                z.write(path, 'Payload/DmTV.app/' + path.relative_to(app).as_posix())
    overlay_zip = out / ('D2RMobile-' + tag + '-overlay.zip')
    with zipfile.ZipFile(overlay_zip, 'w', zipfile.ZIP_DEFLATED) as z:
        for path in sorted(astc.rglob('*')):
            if path.is_file():
                z.write(path, 'romfs_overlay_astc/' + path.relative_to(astc).as_posix())
    packages = [{'name': p.name, 'sha256': ci.sha256(p), 'bytes': p.stat().st_size}
                for p in (ipa, overlay_zip)]
    report = dict(platform='tvos', source_commit=ci.CONFIG['upstream_commit'],
                  app_version=ci.CONFIG['app_version'], minimum_os='26.0',
                  release_tag=tag, device_tested=False, signed=False,
                  game_program_layout='upstream embedded segments',
                  shader_chain=chain, metal_libraries=len(libs),
                  legacy_pack=info['payload']['legacy_pack'], packages=packages)
    (out / 'tvos-build-report.json').write_text(json.dumps(report, indent=2) + '\n')
    (out / 'TV-SHA256SUMS.txt').write_text(''.join(p['sha256'] + '  ' + p['name'] + '\n' for p in packages))


def publish():
    out = ci.ROOT / 'outputs'
    report = json.loads((out / 'tvos-build-report.json').read_text())
    paths = [out / p['name'] for p in report['packages']]
    for record, path in zip(report['packages'], paths):
        if path.name != record['name'] or ci.sha256(path) != record['sha256']:
            raise ValueError('tvOS package checksum mismatch')
    body = out / 'TV-RELEASE.md'
    body.write_text('Experimental Apple TV build / Apple TV 实验版\n\n'
                    'Apple TV 4K (3rd generation, A15), tvOS 26+, extended gamepad required. '
                    'Unsigned: re-sign for your device. No physical-device testing.\n\n'
                    '需要第三代 Apple TV 4K、tvOS 26 和手柄。安装包未签名，需自行签名。未进行真机测试。\n\n'
                    '**Saves are in purgeable Caches; back them up. 存档在系统可清理的 Caches 中，请备份。**\n\n'
                    '[Installation / 安装与资源导入](https://github.com/jiayx/d2r-mobile-build/blob/main/docs/TVOS.md)\n\n'
                    'Source: `' + report['source_commit'] + '`\n')
    repo, tag = os.environ['GITHUB_REPOSITORY'], report['release_tag']
    if release_info(repo, tag) is None:
        gh('release', 'create', tag, '--repo', repo, '--target', os.environ['GITHUB_SHA'],
           '--title', tag + ' (experimental)', '--notes-file', body, '--draft', '--prerelease')
    upload_verified(repo, tag, [*paths, out / 'TV-SHA256SUMS.txt', out / 'tvos-build-report.json'])
    gh('release', 'edit', tag, '--repo', repo, '--draft=false', '--prerelease', '--latest=false')


if __name__ == '__main__':
    try:
        {'plan': plan, 'download': tvos_inputs.download, 'build': build, 'publish': publish}[sys.argv[1]]()
    except Exception as exc:
        # Downloader exceptions can contain private URLs.
        message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
        print('::error::' + message, file=sys.stderr)
        sys.exit(1)
