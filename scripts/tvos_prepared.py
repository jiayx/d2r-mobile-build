"""Create and consume a minimal, independently verified TV input package."""
import json
import os
from pathlib import Path
import shutil
import sys
import time
import zipfile

import ci
import macos
import tvos_inputs
from archive_input import extract
from input_config import settings, input_identity, download_file
from source import prepared
from source.compatibility import verify_generation
from source.publish import gh, release_info, upload_verified

FORMAT = 'd2r-mobile-tvos-prepared'
BASE = {'romfs-inputs.zip', 'D2RMobile-TVShaderInput.zip', 'legacy/pack.json', 'legacy/pack_index.tsv'}
PROGRAMS = {f'product/{m}.{s}' for m in ('main', 'sdk') for s in ('patched.bin', 'fixups.tsv', 'gates.tsv')}
OPTIONAL = {'product/bootlist.tsv', 'product/main.cuts.tsv'}
FILES = BASE | PROGRAMS


def verify(directory, check_source=True):
    info = json.loads((directory / 'manifest.json').read_text())
    if info.get('format') != FORMAT or info.get('schema_version') != 1:
        raise ValueError('Expected a TV prepared package (schema 1)')
    files = info['files']
    if not FILES <= set(files) <= FILES | OPTIONAL:
        raise ValueError('TV input file manifest is incomplete or contains unused files')
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file()}
    if actual != set(files) | {'manifest.json'}:
        raise ValueError('Unexpected or missing TV input files')
    for name, record in files.items():
        path = directory / name
        if path.is_symlink() or path.stat().st_size != record['bytes'] or ci.sha256(path) != record['sha256']:
            raise ValueError('TV input checksum mismatch: ' + name)
    if json.loads((directory / 'legacy/pack.json').read_text()) != info['legacy_pack']:
        raise ValueError('TV Legacy descriptor differs from its report')
    if check_source:
        if info['nso_sha256'] != ci.CONFIG['nso_sha256']:
            raise ValueError('TV input belongs to different game programs')
        if info['product'] != (ci.ROOT / 'upstream/dm/PRODUCT').read_text().strip():
            raise ValueError('TV input belongs to a different product')
        verify_generation(ci.ROOT / 'upstream', info['source_commit'])
    return info


def create():
    root = ci.ROOT
    macos.import_prepared()
    mac = root / '.macos-prepared'
    mi = macos.load_prepared()
    ios = root / '.tvos-ios-input'
    extract(root / '.prepared-downloads/prepared-input.archive', ios)
    ii = prepared.verify_directory(ios)
    if ii['nso_sha256'] != mi['nso_sha256'] or ii['payload']['product'] != mi['product']:
        raise ValueError('iOS and Mac inputs use different game programs')
    stage = root / '.tvos-prepared-stage'
    stage.mkdir(exist_ok=True)
    for name in PROGRAMS | {'romfs-inputs.zip'} | {n for n in OPTIONAL if (mac / n).is_file()}:
        destination = stage / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(mac / name, destination)
    shutil.copytree(ios / 'legacy', stage / 'legacy', dirs_exist_ok=True)
    paths = tvos_inputs.download()
    if len(paths) != 1 or paths[0].name != 'D2RMobile-TVShaderInput.zip':
        raise ValueError('TV input preparation requires a verified recovered shader artifact')
    shutil.copy2(paths[0], stage / paths[0].name)
    # Verify every original shader CKey before publishing the new input.
    tvos_inputs.extract_shader_packs(root / 'upstream/dm', stage, root / '.tvos-input-validation',
                                    [stage / paths[0].name], os.environ)
    info = {'format': FORMAT, 'schema_version': 1, 'product': mi['product'],
            'nso_sha256': mi['nso_sha256'], 'source_commit': mi['source_commit'],
            'legacy_pack': ii['payload']['legacy_pack'],
            'inputs': {'ios_sha256': ci.sha256(root / '.prepared-downloads/prepared-input.archive'),
                       'macos_sha256': ci.sha256(root / '.macos-downloads/prepared-input.archive'),
                       'shaders_sha256': ci.sha256(paths[0])},
            'files': {p.relative_to(stage).as_posix(): {'bytes': p.stat().st_size, 'sha256': ci.sha256(p)}
                      for p in sorted(stage.rglob('*')) if p.is_file() and p.name != 'manifest.json'}}
    (stage / 'manifest.json').write_text(json.dumps(info, indent=2) + '\n')
    verify(stage)
    out = root / 'outputs'
    out.mkdir(exist_ok=True)
    package = out / 'D2RMobile-TVPrepared.zip'
    with zipfile.ZipFile(package, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in sorted(stage.rglob('*')):
            if path.is_file():
                member = zipfile.ZipInfo(path.relative_to(stage).as_posix(), (1980, 1, 1, 0, 0, 0))
                member.compress_type = zipfile.ZIP_DEFLATED
                member.external_attr = 0o100644 << 16
                z.writestr(member, path.read_bytes(), compresslevel=6)
    report = {'name': package.name, 'bytes': package.stat().st_size, 'sha256': ci.sha256(package),
              'previous_input_bytes': sum(p.stat().st_size for p in
                 (root / '.prepared-downloads/prepared-input.archive', root / '.macos-downloads/prepared-input.archive', paths[0])),
              'files': info['files'], 'source_commit': info['source_commit']}
    (out / 'tvos-prepared-report.json').write_text(json.dumps(report, indent=2) + '\n')
    (out / 'TVPrepared-SHA256SUMS.txt').write_text(report['sha256'] + '  ' + package.name + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'files'}), flush=True)


def plan():
    url, digest = settings()
    with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
        f.write('input_revision=' + input_identity(url, digest) + '\n')


def download():
    url, digest = settings()
    if not digest:
        raise ValueError('TV prepared input requires sha256 or sha256_url')
    archive = ci.ROOT / '.tvos-prepared-downloads/prepared-input.archive'
    if not archive.is_file() or ci.sha256(archive) != digest:
        download_file(url, archive, digest, max_bytes=1024**3)
    return archive


def load():
    directory = ci.ROOT / '.tvos-prepared'
    extract(download(), directory)
    return directory, verify(directory)


def publish():
    out = ci.ROOT / 'outputs'
    report = json.loads((out / 'tvos-prepared-report.json').read_text())
    tag = 'tvos-prepared-v1-' + report['sha256']
    repo = os.environ['GITHUB_REPOSITORY']
    if release_info(repo, tag) is None:
        gh('release', 'create', tag, '--repo', repo, '--target', os.environ['GITHUB_SHA'],
           '--title', 'TV prepared build input', '--notes', 'Verified TV build input; not an installable app.',
           '--draft', '--prerelease')
    for attempt in range(6):
        if release_info(repo, tag) is not None:
            break
        time.sleep(2)
    else:
        raise RuntimeError('New draft release is not yet visible to the release API')
    upload_verified(repo, tag, [out / report['name'], out / 'TVPrepared-SHA256SUMS.txt', out / 'tvos-prepared-report.json'])
    gh('release', 'edit', tag, '--repo', repo, '--draft=false', '--prerelease', '--latest=false')
    print('TV prepared input: https://github.com/' + repo + '/releases/tag/' + tag)


if __name__ == '__main__':
    try:
        {'create': create, 'plan': plan, 'download': download, 'publish': publish}[sys.argv[1]]()
    except Exception as exc:
        print('::error::' + (str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__), file=sys.stderr)
        sys.exit(1)
