"""Copy existing resource releases once, verifying both ends without regeneration."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request
from urllib.parse import urlparse

SOURCE = 'jiayx/d2r-mobile-build-test'
TARGET = 'jiayx/d2r-mobile-build'
TAGS = (
    'data-3.3.94012-97a2ada74145114ff8364bdc51a756408ef0c6d332e58fefe68eb0ee2b7c4a31',
    'legacy-3.3.94012-3e82ab6dec4dee197c05cfc558f60d794e62394f4d843c908c2b91837fa6f9ce',
)


def gh(*args, source=False):
    env = dict(os.environ)
    if source:
        token = env.get('RESOURCE_SOURCE_TOKEN')
        if not token:
            raise ValueError('SOURCE_TOKEN is not configured for private resource access')
        env['GH_TOKEN'] = token
    return subprocess.check_output(['gh', *map(str, args)], env=env, text=True)


def destination(tag):
    pages = json.loads(gh('api', '--paginate', '--slurp', f'repos/{TARGET}/releases?per_page=100'))
    return next((r for page in pages for r in page if r['tag_name'] == tag), None)


def digest(path):
    with path.open('rb') as stream:
        return 'sha256:' + hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    manifest = event.get('inputs', {}).get('resource_manifest', '')
    sources = json.loads(manifest) if manifest else [
        json.loads(gh('api', f'repos/{SOURCE}/releases/tags/{tag}', source=True)) for tag in TAGS]
    if [r['tag_name'] for r in sources] != list(TAGS):
        raise ValueError('Unexpected source resource release')
    for release in sources:
        if release['draft'] or not release['assets']:
            raise ValueError('Source resource release is incomplete')
        for a in release['assets']:
            if Path(a['name']).name != a['name']:
                raise ValueError('Invalid asset filename')
            if manifest:
                url = a['download_url']
                if urlparse(url).scheme != 'https' or urlparse(url).hostname != 'release-assets.githubusercontent.com':
                    raise ValueError('Unexpected download host')
                print('::add-mask::' + url, flush=True)
            if a['state'] != 'uploaded' or not (a.get('digest') or '').startswith('sha256:'):
                raise ValueError('Source asset lacks server checksum')
    print('Existing resource releases accessible; all source assets have server SHA-256', flush=True)
    if '--publish' not in sys.argv:
        return
    root = Path('.resource-migration')
    root.mkdir(exist_ok=True)
    for release in sources:
        tag = release['tag_name']
        if destination(tag) is None:
            raise ValueError('Prepare reviewed destination release notes first: ' + tag)
        for asset in release['assets']:
            found = next((a for a in destination(tag)['assets'] if a['name'] == asset['name']), None)
            identity = (asset['size'], asset['digest'])
            if found:
                if found['state'] != 'uploaded' or (found['size'], found['digest']) != identity:
                    raise ValueError('Existing asset differs: ' + asset['name'])
                print('Already verified:', asset['name'], flush=True)
                continue
            path = root / asset['name']
            if not path.exists():
                if manifest:
                    try:
                        with urllib.request.urlopen(asset['download_url'], timeout=120) as response, path.open('wb') as output:
                            while chunk := response.read(8 * 1024**2):
                                output.write(chunk)
                    except Exception:
                        raise RuntimeError('Resource transfer failed; source URL omitted') from None
                else:
                    gh('release', 'download', tag, '-R', SOURCE, '--pattern', asset['name'], '--dir', root, source=True)
            if (path.stat().st_size, digest(path)) != identity:
                raise ValueError('Downloaded asset checksum differs')
            gh('release', 'upload', tag, path, '-R', TARGET)
            found = next(a for a in destination(tag)['assets'] if a['name'] == asset['name'])
            if found['state'] != 'uploaded' or (found['size'], found['digest']) != identity:
                raise ValueError('Uploaded asset checksum differs')
            print('Uploaded and verified:', asset['name'], flush=True)
        gh('release', 'edit', tag, '-R', TARGET, '--draft=false', '--latest=false')
        print('Published verified resources:', tag, flush=True)


if __name__ == '__main__':
    main()
