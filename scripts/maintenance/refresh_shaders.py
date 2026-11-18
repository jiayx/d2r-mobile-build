"""Refresh Metal payloads from recovered shaders, retaining verified game inputs."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import ci
import macos
import tvos_inputs
from archive_input import extract
from source import compatibility, prepared, prepare_ios


def verify_reuse(upstream, baseline):
    # This path regenerates shaders, not programs or game-table headers. Keep the
    # ordinary guard intact and narrowly review the translator-only change here.
    name = 'dm/gfx/tools/dmsh_xlate/Program.cs'
    before = compatibility.git(upstream, 'show', baseline + ':' + name)
    after = (upstream / name).read_text()
    if after != before and (after.count('.Add((JsonNode)new JsonObject') != 3
            or after.replace('.Add((JsonNode)new JsonObject', '.Add(new JsonObject') != before):
        raise ValueError('Review changed shader translator before refreshing')
    paths = compatibility.generation_paths(upstream, baseline) | compatibility.generation_paths(upstream, None)
    paths.update(('dm/ios/tools/gen_vault_table.py', 'dm/ios/tools/gen_hud_exp.py', 'dm/tools/gen_bright_levels.py'))
    changed = set(compatibility.git(upstream, 'diff', '--name-only', baseline, 'HEAD').splitlines())
    for path in sorted((paths & changed) - {name}):
        allowed = compatibility.COMPATIBLE_GENERATORS.get(path, set())
        old = hashlib.sha256(compatibility.git(upstream, 'show', baseline + ':' + path).encode()).hexdigest()
        if old not in allowed or ci.sha256(upstream / path) not in allowed:
            raise ValueError('Cannot reuse prepared non-shader input: ' + path)


def run(*args, **kwargs):
    return subprocess.check_output(list(map(str, args)), text=True, **kwargs).strip()


def refresh():
    upstream = ROOT / 'upstream'
    dm = upstream / 'dm'
    stages = {}
    for kind, cache in (('ios', '.prepared-downloads'), ('macos', '.macos-downloads')):
        os.environ['PREPARED_INPUT'] = os.environ[kind.upper() + '_PREPARED_INPUT']
        prepared.download(cache_name=cache)
        archive = ROOT / cache / 'prepared-input.archive'
        stage = ROOT / ('.' + kind + '-prepared')
        if stage.exists():
            raise ValueError('Use a fresh staging directory; existing prepared inputs are preserved')
        extract(archive, stage, max_members=100000 if kind == 'macos' else 32)
        if kind == 'ios':
            info = prepared.verify_directory(stage)
            baseline = info['producer']['source_commit']
        else:
            saved = prepared.read(stage / 'manifest.json')
            os.environ['MACOS_PREPARED_KEY'] = saved['key']
            info = macos.load_prepared()
            del os.environ['MACOS_PREPARED_KEY']
            baseline = info['source_commit']
        if info['nso_sha256'] != ci.CONFIG['nso_sha256']:
            raise ValueError('Original game program identity differs')
        verify_reuse(upstream, baseline)
        stages[kind] = (stage, info, baseline, ci.sha256(archive))
    ios, ii, _, _ = stages['ios']
    mac, mi, _, _ = stages['macos']
    work = ROOT / '.shader-refresh'
    environment = dict(os.environ, DM_ROOT=str(work), DM_OUT=str(mac / 'product'),
                       IOSOUT=str(work / 'build/ios/dmsh_b'))
    _, packs = tvos_inputs.extract_shader_packs(dm, mac, work, tvos_inputs.download(), environment)
    translator = work / 'build/gfx/dmsh_xlate'
    subprocess.run(['dotnet', 'publish', str(dm / 'gfx/tools/dmsh_xlate'), '-c', 'Release',
                    '-o', str(translator), '-v', 'quiet'], env=environment, check=True)
    for flag in ('--update-lock', '--header'):
        subprocess.run([sys.executable, str(dm / 'gfx/tools/dmsh_chain.py'), flag], env=environment, check=True)
    cache = work / 'build/cache/metal_shader_cache'
    subprocess.run([sys.executable, str(ROOT / 'scripts/tvos_inputs.py'), 'translate', str(dm),
                    str(mac / 'product'), str(packs), str(cache)], env=environment, check=True)
    chain = run(sys.executable, dm / 'gfx/tools/dmsh_chain.py', env=environment)
    subprocess.run([sys.executable, str(dm / 'gfx/tools/c1_guard.py'), str(cache / ('b-' + chain)),
                    str(dm / 'gfx/nvn/c1_full.tsv')], env=environment, check=True)
    new_mac = work / 'macos-msl'
    macos.retarget_shaders(dm / 'gfx/tools/msl_retarget.sh', '15.0', new_mac, environment)
    # Preserve old outputs in this run as well as in their immutable release/cache.
    (mac / 'msl').rename(work / 'previous-macos-msl')
    shutil.copytree(new_mac, mac / 'msl')
    ios_msl = work / 'build/ios/dmsh_b' / ('b-' + chain)
    payload = ios / 'source-payload.zip'
    revised = work / 'source-payload.zip'
    base = prepare_ios.BASE
    with zipfile.ZipFile(payload) as old, zipfile.ZipFile(revised, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as new:
        for member in old.infolist():
            if member.filename.startswith(base + 'msl/') or member.filename == base + 'dm/c1_full.tsv':
                continue
            data = old.read(member)
            if member.filename in (base + 'dm/shell_info.txt', base + 'dm/shell_manifest.txt'):
                data = data.replace(ii['payload']['shader_chain'].encode(), chain.encode())
            new.writestr(member, data)
        new.write(dm / 'gfx/nvn/c1_full.tsv', base + 'dm/c1_full.tsv')
        for path in sorted(ios_msl.iterdir()):
            if path.suffix in ('.json', '.metallib'):
                new.write(path, base + 'msl/' + ios_msl.name + '/' + path.name)
    payload.rename(work / 'previous-ios-payload.zip')
    shutil.copy2(revised, payload)
    record = run(sys.executable, '-c', 'import ios_metal; print(ios_metal.RECORD)', cwd=dm / 'ios/tools', env=environment)
    libraries = list(ios_msl.glob('*.metallib'))
    ii['payload'].update(shader_chain=chain, shader_source_chain=chain,
        shader_source_sha16=run(sys.executable, dm / 'tools/d2rm_pack.py', '--src-digest', cache / ('b-' + chain), env=environment),
        payload_sha256=ci.sha256(payload), metal_libraries=len(libraries),
        metal_unique_libraries=len({ci.sha256(p) for p in libraries}),
        metal_toolchain={'metal': run('xcrun', '-sdk', 'iphoneos', 'metal', '--version').splitlines()[0],
                         'xcode': run('xcodebuild', '-version'),
                         'sdk': run('xcrun', '--sdk', 'iphoneos', '--show-sdk-build-version'), 'compile_record': record})
    mi.update(shader_chain=chain, metal_libraries=len(list((mac / 'msl' / ('b-' + chain)).glob('*.metallib'))))
    mi['metal_reflections'] = macos.verify_shaders(mac / 'msl' / ('b-' + chain), chain, mi['metal_libraries'])
    shutil.copy2(dm / 'gfx/nvn/c1_full.tsv', mac / 'c1_full.tsv')
    evidence = {'source_commit': ci.CONFIG['upstream_commit'], 'shader_chain': chain, 'platforms': {}}
    for kind, (stage, info, baseline, digest) in stages.items():
        shutil.copy2(dm / 'gfx/tools/dmsh_chain.lock', stage / 'shader-chain.lock')
        identity = hashlib.sha256((digest + chain + ci.CONFIG['upstream_commit']).encode()).hexdigest()
        info['shader_refresh'] = {'base_archive_sha256': digest, 'reused_inputs_source_commit': baseline,
                                  'recovery_run_id': tvos_inputs.configuration()['recovery_run_id']}
        if kind == 'ios':
            info['producer'] = {'source_commit': ci.CONFIG['upstream_commit'], 'tools_commit': os.environ['GITHUB_SHA']}
            info['prepare_key'] = 'ios-shader-refresh-v1-' + identity
            info['files'] = {n: {'bytes': (stage / n).stat().st_size, 'sha256': ci.sha256(stage / n)} for n in info['files']}
            prepared.write(stage / 'prepared.json', info)
            os.environ['IOS_PREPARED_KEY'] = info['prepare_key']
            prepare_ios.cached()
        else:
            info['source_commit'] = ci.CONFIG['upstream_commit']
            info['key'] = 'macos-shader-refresh-v1-' + identity
            info['toolchain'] = run('xcodebuild', '-version')
            info['files'] = {p.relative_to(stage).as_posix(): ci.sha256(p) for p in stage.rglob('*') if p.is_file() and p.name != 'manifest.json'}
            prepared.write(stage / 'manifest.json', info)
            macos.load_prepared()
        evidence['platforms'][kind] = info['shader_refresh']
    (ROOT / 'outputs').mkdir(exist_ok=True)
    prepared.write(ROOT / 'outputs/shader-refresh-report.json', evidence)
    prepare_ios.export()
    macos.export_prepared()


if __name__ == '__main__':
    refresh()
