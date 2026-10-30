"""Remove obsolete download/distribution metadata without changing runtime files."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

OBSOLETE = {
    'ios': {'resources.json', 'legacy-resources.json'},
    'macos': {'resources/data/build_manifest.psv', 'resources/data/.build.config'},
}
MANIFEST = {'ios': 'prepared.json', 'macos': 'manifest.json'}


def cleaned_manifest(info, platform, removed):
    info = json.loads(json.dumps(info))
    for name in removed:
        info['files'].pop(name)
    if removed:
        key = 'prepare_key' if platform == 'ios' else 'key'
        identity = hashlib.sha256(json.dumps(info, sort_keys=True).encode()).hexdigest()
        info[key] = platform + '-metadata-clean-v1-' + identity
    return info


def clean_directory(directory, info, platform):
    removed = sorted(OBSOLETE[platform] & info['files'].keys())
    for name in removed:
        (directory / name).unlink()
    return cleaned_manifest(info, platform, removed)


def verify(archive, platform):
    names = [m.filename for m in archive.infolist() if not m.is_dir()]
    if len(names) != len(set(names)):
        raise ValueError('Duplicate archive member')
    info = json.loads(archive.read(MANIFEST[platform]))
    expected_format = 'd2r-mobile-' + ('prepared' if platform == 'ios' else 'macos-prepared')
    if info['format'] != expected_format or info['schema_version'] != 2:
        raise ValueError('Unsupported prepared input')
    if set(names) != set(info['files']) | {MANIFEST[platform]}:
        raise ValueError('Archive differs from manifest')
    for name, record in info['files'].items():
        digest = hashlib.sha256()
        size = 0
        with archive.open(name) as source:
            for block in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(block)
                size += len(block)
        expected = record['sha256'] if platform == 'ios' else record
        if digest.hexdigest() != expected or (platform == 'ios' and size != record['bytes']):
            raise ValueError('Checksum mismatch: ' + name)
    return info


def clean_archive(source, target, platform):
    if target.exists():
        raise ValueError('Refusing to overwrite an existing output')
    with zipfile.ZipFile(source) as old:
        before = verify(old, platform)
        removed = sorted(OBSOLETE[platform] & before['files'].keys())
        after = cleaned_manifest(before, platform, removed)
        with zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED, compresslevel=6) as new:
            for member in old.infolist():
                if member.filename in removed or member.filename == MANIFEST[platform]:
                    continue
                # Preserve member attributes, including executable modes.
                new.writestr(member, old.read(member))
            new.writestr(MANIFEST[platform], json.dumps(after, indent=2) + '\n')
    with zipfile.ZipFile(target) as result:
        verified = verify(result, platform)
        if verified != after:
            raise ValueError('Output manifest mismatch')
        for name, record in verified['files'].items():
            if record != before['files'][name]:
                raise ValueError('Runtime file changed: ' + name)
    with target.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'removed': removed, 'preserved_files': len(after['files']), 'sha256': digest,
            'bytes': target.stat().st_size,
            'key': after['prepare_key' if platform == 'ios' else 'key']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('platform', choices=OBSOLETE)
    parser.add_argument('source', type=Path)
    parser.add_argument('target', type=Path)
    args = parser.parse_args()
    print(json.dumps(clean_archive(args.source, args.target, args.platform), indent=2))
