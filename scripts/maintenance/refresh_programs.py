"""Regenerate Apple programs from verified originals, preserving compatible assets."""
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
from archive_input import extract
from input_config import settings
from source import compatibility, prepared, prepare_ios

REGENERATED = {'dm/tools/patch_nso.py', 'dm/tools/guest_dylib.py'}


def verify_reusable(upstream, baseline):
    # Only these two generators are rerun here. Every other generation dependency
    # must be identical or already reviewed by the standard compatibility guard.
    names = compatibility.generation_paths(upstream, baseline) | compatibility.generation_paths(upstream, None)
    changed = set(compatibility.git(upstream, 'diff', '--name-only', baseline, 'HEAD').splitlines())
    for name in sorted((names & changed) - REGENERATED):
        allowed = compatibility.COMPATIBLE_GENERATORS.get(name, set())
        before = hashlib.sha256(compatibility.git(upstream, 'show', baseline + ':' + name).encode()).hexdigest()
        current = upstream / name
        if not current.is_file() or before not in allowed or ci.sha256(current) not in allowed:
            raise ValueError('Full preparation required; asset dependency changed: ' + name)


def refresh():
    upstream = ROOT / 'upstream'
    originals = ROOT / 'recovered-input/ExeFS'
    for name, expected in ci.CONFIG['nso_sha256'].items():
        if ci.sha256(originals / name) != expected:
            raise ValueError('Original executable checksum mismatch: ' + name)
    stages = {}
    archives = {}
    for kind, cache in (('ios', '.prepared-downloads'), ('macos', '.macos-downloads')):
        os.environ['PREPARED_INPUT'] = os.environ[kind.upper() + '_PREPARED_INPUT']
        prepared.download(cache_name=cache)
        archive = ROOT / cache / 'prepared-input.archive'
        destination = ROOT / ('.ios-prepared' if kind == 'ios' else '.macos-prepared')
        if destination.exists():
            raise ValueError('Refresh destination already exists; preserve it and use a fresh workspace')
        extract(archive, destination)
        archives[kind] = ci.sha256(archive)
        if kind == 'ios':
            info = prepared.verify_directory(destination)
            baseline = info['producer']['source_commit']
        else:
            # First validate archive integrity without pretending it targets current source.
            saved = prepared.read(destination / 'manifest.json')
            os.environ['MACOS_PREPARED_KEY'] = saved['key']
            info = macos.load_prepared()
            del os.environ['MACOS_PREPARED_KEY']
            baseline = info['source_commit']
        if info['nso_sha256'] != ci.CONFIG['nso_sha256']:
            raise ValueError('Base prepared input uses different original programs')
        verify_reusable(upstream, baseline)
        stages[kind] = (destination, info, baseline)

    output = ROOT / 'refreshed-programs'
    output.mkdir()
    environment = dict(os.environ, DM_RULESET='touch-run-v4', DM_TARGET='apple')
    # Do not inherit developer switches which would change the game's rewrite rules.
    for key in ('DM_PRIVATE_GATES', 'DM_PRIVATE_AIM'):
        environment.pop(key, None)
    for name in ci.CONFIG['nso_sha256']:
        subprocess.run([sys.executable, str(upstream / 'dm/tools/patch_nso.py'),
                        str(originals / name), str(output), name], env=environment, check=True)
    frameworks = ROOT / 'refreshed-frameworks'
    subprocess.run([sys.executable, str(upstream / 'dm/tools/guest_dylib.py'), str(output),
                    str(frameworks), 'main', 'sdk'], check=True)
    (frameworks / 'Guest.framework/Guest').chmod(0o755)
    source = ci.CONFIG['upstream_commit']
    evidence = {'source_commit': source, 'nso_sha256': ci.CONFIG['nso_sha256'],
                'generator_sha256': {n: ci.sha256(upstream / n) for n in sorted(REGENERATED)},
                'product_files': {p.name: ci.sha256(p) for p in sorted(output.iterdir()) if p.is_file()}}
    identity = hashlib.sha256(json.dumps({'base_archives': archives, **evidence}, sort_keys=True).encode()).hexdigest()
    for kind, (destination, info, baseline) in stages.items():
        info['program_refresh'] = {**evidence, 'base_archive_sha256': archives[kind],
                                   'reused_assets_source_commit': baseline}
        if kind == 'ios':
            payload = destination / 'source-payload.zip'
            revised = destination / 'revised-payload.zip'
            base = prepare_ios.BASE
            replacements = {base + 'Frameworks/' + p.relative_to(frameworks).as_posix(): p
                            for p in frameworks.rglob('*') if p.is_file()}
            for name in ('main.cuts.tsv', 'main.fixups.tsv', 'main.gates.tsv', 'sdk.fixups.tsv', 'sdk.gates.tsv'):
                replacements[base + 'dm/' + name] = output / name
            with zipfile.ZipFile(payload) as old, zipfile.ZipFile(revised, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as new:
                for member in old.infolist():
                    if member.filename not in replacements:
                        new.writestr(member, old.read(member))
                for name, path in replacements.items():
                    new.write(path, name)
            revised.replace(payload)
            info['producer'] = {'source_commit': source, 'tools_commit': os.environ['TOOLS_COMMIT']}
            info['prepare_key'] = 'ios-program-refresh-v1-' + identity
            info['payload']['payload_sha256'] = ci.sha256(payload)
            info['files'] = {name: {'bytes': (destination / name).stat().st_size,
                                    'sha256': ci.sha256(destination / name)} for name in info['files']}
            prepared.write(destination / 'prepared.json', info)
            os.environ['IOS_PREPARED_KEY'] = info['prepare_key']
            prepare_ios.cached()
        else:
            # The entire product directory is regenerated, including gates/fixups/evidence.
            shutil.rmtree(destination / 'product')
            shutil.copytree(output, destination / 'product')
            info['source_commit'] = source
            info['key'] = 'macos-program-refresh-v1-' + identity
            info['files'] = {p.relative_to(destination).as_posix(): ci.sha256(p)
                             for p in sorted(destination.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
            prepared.write(destination / 'manifest.json', info)
            macos.load_prepared()
    # Publish only after both platforms' inputs have passed validation.
    prepare_ios.export()
    macos.export_prepared()
    prepared.write(ROOT / 'outputs/program-refresh-report.json', evidence)


if __name__ == '__main__':
    refresh()
