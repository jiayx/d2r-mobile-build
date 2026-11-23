"""Portable, verified game payloads; native runtime sources always come from the selected ref."""
import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ci
from archive_input import extract, MAX_EXPANDED_BYTES as MAX_PACKAGE_BYTES
from input_config import download_file, input_identity, settings
from source.metal import verify_payload
from source.compatibility import prepared_chain_header, verify_generation

GENERATED = ('host/dm_vault_tab.h', 'host/dm_hud_exp.h', 'host/dm_bright_levels.inc')

FORMAT = 'd2r-mobile-prepared'
FILES = {'source-payload.zip', 'shader-chain.lock', 'resource-manifest.json',
         'romfs-inputs.zip', 'legacy/pack.json', 'legacy/pack_index.tsv',
         *('generated/' + name for name in GENERATED)}


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n')


def verify_directory(directory):
    directory = Path(directory)
    info = read(directory / 'prepared.json')
    if info.get('format') != FORMAT or info.get('schema_version') != 2:
        raise ValueError('Expected a d2r-mobile prepared input package (schema 2)')
    if not FILES <= set(info['files']) <= FILES | {'resources.json', 'legacy-resources.json'}:
        raise ValueError('Prepared package file manifest is incomplete')
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file()}
    if actual != set(info['files']) | {'prepared.json'}:
        raise ValueError('Unexpected or missing prepared package file')
    for name, record in info['files'].items():
        path = directory / name
        if (path.is_symlink() or path.stat().st_size != record['bytes']
                or ci.sha256(path) != record['sha256']):
            raise ValueError('Prepared package checksum mismatch: ' + name)
    report = info['payload']
    if info['files']['source-payload.zip']['sha256'] != report['payload_sha256']:
        raise ValueError('Prepared payload checksum differs from its report')
    if report.get('phone_shader_compilation_required') is not False:
        raise ValueError('Prepared input requires precompiled Metal libraries')
    with zipfile.ZipFile(directory / 'source-payload.zip') as z:
        members = z.infolist()
        if sum(i.file_size for i in members) > MAX_PACKAGE_BYTES:
            raise ValueError('Prepared payload exceeds the supported size')
        for item in members:
            relative = item.filename.removeprefix('Payload/DmIOS.app/')
            if (not item.filename.startswith('Payload/DmIOS.app/') or '\\' in relative
                    or '..' in relative.split('/') or relative.startswith('/')
                    or stat.S_IFMT(item.external_attr >> 16) not in (0, stat.S_IFREG, stat.S_IFDIR)
                    or relative in ('DmIOS', 'embedded.mobileprovision') or '_CodeSignature' in relative.split('/')):
                raise ValueError('Unexpected path in prepared payload')
        pack = read(directory / 'legacy/pack.json')
        if pack != report['legacy_pack']:
            raise ValueError('Prepared Legacy descriptor differs from the payload')
        guest = z.read('Payload/DmIOS.app/Frameworks/Guest.framework/Guest')
        if guest[:8] != bytes.fromhex('cffaedfe0c000001'):
            raise ValueError('Prepared game program is not arm64')
    verify_payload(directory / 'source-payload.zip', report)
    return info


def verify_source(directory, info, upstream, config):
    manifest = read(directory / 'resource-manifest.json')
    if info['nso_sha256'] != config['nso_sha256']:
        raise ValueError('Prepared package does not match the selected game programs')
    for key in ('game_version', 'switch_version'):
        if info[key] != manifest[key]:
            raise ValueError('Prepared package resource metadata differs: ' + key)
    if {f['name']: f['bytes'] for f in manifest['files']} != ci.resource_sizes():
        raise ValueError('Prepared package resources do not match the selected source')
    dm = upstream / 'dm'
    if (dm / 'PRODUCT').read_text().strip() != info['payload']['product']:
        raise ValueError('Selected source requires a different prepared game product')
    verify_generation(upstream, info['producer']['source_commit'])
    shutil.copy2(directory / 'shader-chain.lock', dm / 'gfx/tools/dmsh_chain.lock')
    chain = prepared_chain_header(upstream, info['producer']['source_commit'])
    if chain != info['payload']['shader_chain']:
        raise ValueError('Selected source shader chain differs; supply an updated prepared package')


def resolve():
    url, digest = settings()
    with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
        f.write('input_revision=' + input_identity(url, digest) + '\n')


def download(root=ci.ROOT, cache_name='.prepared-downloads'):
    url, digest = settings()
    archive = root / cache_name / 'prepared-input.archive'
    marker = archive.with_suffix('.json')
    if archive.is_file():
        try:
            saved = read(marker)
            if (saved['identity'] == input_identity(url, digest) and saved['bytes'] == archive.stat().st_size
                    and saved['sha256'] == ci.sha256(archive) and (not digest or saved['sha256'] == digest)):
                print('Reused verified prepared package; download skipped', flush=True)
                return
        except (OSError, ValueError, KeyError):
            pass
    download_file(url, archive, digest or None, max_bytes=MAX_PACKAGE_BYTES)
    if not archive.stat().st_size:
        raise ValueError('Prepared package download is empty')
    write(marker, {'identity': input_identity(url, digest), 'bytes': archive.stat().st_size,
                   'sha256': ci.sha256(archive)})
    print('Prepared package downloaded and verified; ready to cache before extraction', flush=True)


def prepare(root=ci.ROOT):
    archive = root / '.prepared-downloads/prepared-input.archive'
    target = root / '.prepared-input'
    shutil.rmtree(target, ignore_errors=True)
    extract(archive, target)
    candidates = list(target.rglob('prepared.json'))
    if len(candidates) != 1:
        raise ValueError('Archive must contain exactly one prepared.json')
    directory = candidates[0].parent
    info = verify_directory(directory)
    upstream = root / 'upstream'
    verify_source(directory, info, upstream, ci.CONFIG)
    ci.CONFIG.update(game_version=info['game_version'], switch_version=info['switch_version'])
    dm = upstream / 'dm'
    out = root / 'outputs'
    out.mkdir(exist_ok=True)
    from source.runtime_assets import ios_payload
    generation_seconds = ios_payload(directory, info, dm, out / 'source-payload.zip', root / '.runtime-inputs')
    subprocess.run([sys.executable, str(dm / 'ios/tools/shell_stubs.py'), 'stubs', str(dm)], check=True)
    allowed = ('product', 'shader_chain', 'shader_source_chain', 'payload_sha256', 'legacy_pack',
               'shader_source_sha16', 'metal_precompiled', 'metal_libraries', 'metal_unique_libraries',
               'metal_toolchain', 'phone_shader_compilation_required')
    report = {k: info['payload'][k] for k in allowed}
    report.update(source_repository=os.environ['SOURCE_REPOSITORY'], source_commit=ci.CONFIG['upstream_commit'],
                  tools_commit=os.environ.get('TOOLS_COMMIT'),
                  input_revision=os.environ['INPUT_REVISION'], prepared_input=True,
                  prepared_schema_version=info['schema_version'], prepared_archive_sha256=ci.sha256(archive),
                  prepared_from_source=info['producer']['source_commit'],
                  resource_manifest_sha256=ci.sha256(directory / 'resource-manifest.json'))
    report['payload_sha256'] = ci.sha256(out / 'source-payload.zip')
    report['runtime_generation_seconds'] = generation_seconds
    verify_payload(out / 'source-payload.zip', report)
    write(out / 'build-context.json', ci.CONFIG)
    write(out / 'source-input-report.json', report)
    with tarfile.open(out / 'native-inputs.tar.gz', 'w:gz', compresslevel=1) as tf:
        def include(item):
            return None if any(p in ('.git', 'Gen', '__pycache__', 'bin', 'obj')
                               for p in Path(item.name).parts) else item
        tf.add(dm, arcname='upstream/dm', filter=include)
    print('Prepared package and source compatibility verified', flush=True)
    print('Native runtime source:', ci.CONFIG['upstream_commit'], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('resolve', 'download', 'prepare'))
    args = parser.parse_args()
    try:
        globals()[args.command]()
    except Exception as exc:
        print('::error::' + (str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__), file=sys.stderr)
        sys.exit(1)
