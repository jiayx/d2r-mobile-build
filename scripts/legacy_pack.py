#!/usr/bin/env python3
"""Generate a paired ASTC pack once, or restore its verified Release assets."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import ci
import export_resources
import publish_release as publish
import release_notes

PACK = ci.DM / 'build/legacy/pack'
ZIP_NAME = 'Legacy-Device-Pack.zip'
META_NAMES = ('pack.json', 'pack_index.tsv', 'legacy-report.json')
CONVERTER = ci.TOOLS / 'legacy-converter'
CONVERTER_SOURCES = ('dm/tools/astc_pack.py', 'dm/tools/casc_overlay.py',
                     'dm/ios/tools/touch_layout.py')


def ensure_converter():
    """Pin offline texture conversion independently of the app's UI source."""
    config = ci.CONFIG['legacy_converter']
    if set(config['sources']) != set(CONVERTER_SOURCES):
        raise ValueError('Unexpected Legacy Device Pack converter sources')
    for name in CONVERTER_SOURCES:
        path = CONVERTER / name
        digest = config['sources'][name]
        if not path.exists() or ci.sha256(path) != digest:
            ci.download(f"https://raw.githubusercontent.com/{ci.CONFIG['upstream_repository']}/"
                        f"{config['commit']}/{name}", path, digest)


def recipe(manifest):
    value = {'format': 1, 'resource_id': export_resources.resource_identity(manifest),
             'build_manifest_sha256': ci.sha256(ci.GAME / 'RomFS/data/build_manifest.psv'),
             'encoder_sha256': ci.CONFIG['astc_encoder_sha256'], 'preset': 'thorough',
             'sources': {p: ci.sha256(CONVERTER / p) for p in CONVERTER_SOURCES}}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def validate_pack(directory):
    directory = Path(directory)
    info = json.loads((directory / 'pack.json').read_text())
    if info.get('name') != '00-00000008.data' or type(info.get('size')) is not int or info['size'] <= 0:
        raise ValueError('Unexpected Legacy Device Pack archive')
    data = directory / 'Legacy Device Pack/data' / info['name']
    if data.stat().st_size != info['size'] or ci.sha256(data) != info['sha256']:
        raise ValueError('Legacy Device Pack SHA256 mismatch')
    manifest = json.loads((directory / 'Legacy Device Pack/manifest.json').read_text())
    if manifest != {'files': [info]}:
        raise ValueError('Legacy Device Pack manifest differs')
    header = (directory / 'pack_index.tsv').read_text().splitlines()[0].split('\t')
    if header[:2] != ['# pack', info['name']]:
        raise ValueError('Legacy Device Pack index differs')
    return info


def reference(repo, release, recipe_id):
    if not release or release.get('draft') or release.get('prerelease'):
        return None
    assets = {a['name']: a for a in release['assets']}
    if not {ZIP_NAME, *META_NAMES} <= assets.keys():
        return None
    try:
        report = json.loads(publish.read_metadata(repo, assets['legacy-report.json']))
        if report['recipe_id'] != recipe_id:
            return None
        for name in (ZIP_NAME, 'pack.json', 'pack_index.tsv'):
            asset = assets[name]
            if (asset['size'], publish.asset_digest(asset)) != (report['assets'][name]['bytes'], report['assets'][name]['sha256']):
                return None
            if not asset['browser_download_url'].startswith(f'https://github.com/{repo}/releases/download/'):
                return None
        info = json.loads(publish.read_metadata(repo, assets['pack.json']))
        if info != report['pack']:
            return None
        return {'recipe_id': recipe_id, 'pack': info,
                'source_release': {'id': release['id'], 'url': release['html_url'], 'tag': release['tag_name']},
                'assets': [{'name': n, 'bytes': assets[n]['size'], 'sha256': publish.asset_digest(assets[n]),
                            'url': assets[n]['browser_download_url'], 'id': assets[n]['id']}
                           for n in (ZIP_NAME, *META_NAMES)]}
    except (ValueError, KeyError, TypeError):
        return None


def restore(repo, ref):
    """The app needs the verified index and descriptor, not the phone's 1 GB archive."""
    selected = [a for a in ref['assets'] if a['name'] in ('pack.json', 'pack_index.tsv')]
    if len(selected) != 2 or {a['name'] for a in selected} != {'pack.json', 'pack_index.tsv'}:
        raise ValueError('Legacy build metadata missing or duplicated')
    publish.STAGE.mkdir(parents=True, exist_ok=True)
    PACK.mkdir(parents=True, exist_ok=True)
    for asset in selected:
        path = publish.STAGE / asset['name']
        with path.open('wb') as stream:
            subprocess.run(['gh', 'api', '-H', 'Accept: application/octet-stream',
                            f"repos/{repo}/releases/assets/{asset['id']}"], stdout=stream, check=True)
        if path.stat().st_size != asset['bytes'] or ci.sha256(path) != asset['sha256']:
            raise ValueError('Restored legacy asset SHA256 mismatch: ' + asset['name'])
        if asset['name'] in ('pack.json', 'pack_index.tsv'):
            shutil.copyfile(path, PACK / asset['name'])
    if json.loads((PACK / 'pack.json').read_text()) != ref['pack']:
        raise ValueError('Restored legacy descriptor differs from Release')
    if (PACK / 'pack_index.tsv').read_text().splitlines()[0].split('\t')[:2] != ['# pack', ref['pack']['name']]:
        raise ValueError('Restored legacy index differs from Release')


def generate():
    encoder_zip = ci.TOOLS / 'astcenc-5.2.0-linux-x64.zip'
    if not encoder_zip.exists() or ci.sha256(encoder_zip) != ci.CONFIG['astc_encoder_sha256']:
        ci.download(ci.CONFIG['astc_encoder_url'], encoder_zip, ci.CONFIG['astc_encoder_sha256'])
    encoder = ci.TOOLS / 'bin/astcenc-avx2'
    encoder.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(encoder_zip) as z:
        encoder.write_bytes(z.read('bin/astcenc-avx2'))
    encoder.chmod(0o755)
    work = PACK.parent / 'work'
    # Partial conversions are not a complete pack; always rebuild them coherently.
    shutil.rmtree(PACK, ignore_errors=True)
    shutil.rmtree(work, ignore_errors=True)
    romfs = ci.GAME / 'RomFS'
    tools = CONVERTER / 'dm/tools'
    for args in ([tools / 'astc_pack.py', romfs, work, '--astcenc', encoder, '--preset', 'thorough'],
                 [tools / 'casc_overlay.py', 'pack', romfs, PACK, work / 'repl.tsv', '0-8'],
                 [tools / 'astc_pack.py', 'finalize', PACK]):
        subprocess.run([sys.executable, '-u', *map(str, args)], check=True)
    info = validate_pack(PACK)
    shutil.rmtree(work)
    return info


def publish_pack(repo, recipe_id, tag):
    info = generate()
    archive = publish.STAGE / ZIP_NAME
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as z:
        for path in sorted((PACK / 'Legacy Device Pack').rglob('*')):
            if path.is_file():
                z.write(path, path.relative_to(PACK).as_posix())
    for name in ('pack.json', 'pack_index.tsv'):
        shutil.copyfile(PACK / name, publish.STAGE / name)
    report = {'recipe_id': recipe_id, 'pack': info, 'assets': {
        name: {'bytes': (publish.STAGE / name).stat().st_size, 'sha256': ci.sha256(publish.STAGE / name)}
        for name in (ZIP_NAME, 'pack.json', 'pack_index.tsv')}}
    (publish.STAGE / 'legacy-report.json').write_text(json.dumps(report, indent=2) + '\n')
    (publish.STAGE / 'Legacy-SHA256SUMS.txt').write_text(
        f"{report['assets'][ZIP_NAME]['sha256']}  {ZIP_NAME}\n")
    notes = publish.STAGE / 'LEGACY-RELEASE.md'
    notes.write_text(release_notes.legacy(repo, ZIP_NAME))
    title = f"D2R Mobile Legacy Device Pack · {ci.CONFIG['game_version']} · {recipe_id[:12]}"
    current = publish.ensure_release(repo, tag, title, notes)
    if not current['draft']:
        publish.gh('release', 'edit', tag, '--repo', repo, '--draft=true')
    publish.upload_verified(repo, tag, [publish.STAGE / n for n in
                                      (ZIP_NAME, *META_NAMES, 'Legacy-SHA256SUMS.txt')])
    release = publish.publish_complete(repo, tag, notes, title, latest=False)
    ref = reference(repo, release, recipe_id)
    if not ref:
        raise ValueError('Published legacy pack failed verification')
    return ref


def main():
    repo = os.environ['GITHUB_REPOSITORY']
    publish.OUT.mkdir(exist_ok=True)
    publish.STAGE.mkdir(exist_ok=True)
    ensure_converter()
    manifest = export_resources.scan_resources(ci.GAME)
    (publish.OUT / 'resource-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    identity = recipe(manifest)
    tag = f"legacy-{ci.CONFIG['game_version']}-{identity}"
    ref = reference(repo, publish.release_info(repo, tag), identity)
    if ref:
        restore(repo, ref)
        print('Reused verified Legacy Device Pack; skipped transcoding and upload', flush=True)
    else:
        ref = publish_pack(repo, identity, tag)
    (publish.OUT / 'legacy-resources.json').write_text(json.dumps(ref, indent=2) + '\n')
    env_file = os.environ.get('GITHUB_ENV')
    if env_file:
        with open(env_file, 'a') as f:
            f.write(f'D2RM_ASTC_PACK={PACK}\n')


if __name__ == '__main__':
    main()
