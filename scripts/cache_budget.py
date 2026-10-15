"""Save optional speed caches only when existing downloads can remain in place."""
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

LIMIT = 10 * 1024**3
RESERVE = 256 * 1024**2
ORDER = ('payload', 'rewrite', 'shaders', 'tools')
PATHS = dict(zip(ORDER, ('.fast-payload', '.fast-rewrite', '.fast-shaders', '.mac-pack-tools')))


def choose(used, sizes, limit=LIMIT, reserve=RESERVE):
    remaining = max(0, limit - used - reserve)
    result = {}
    for name in ORDER:
        size = sizes.get(name, 0)
        result[name] = size > 0 and size <= remaining
        if result[name]:
            remaining -= size
    return result


def usage(repository):
    url = f'https://api.github.com/repos/{repository}/actions/cache/usage'
    # Public main does not need extra workflow permissions. Private callers may
    # use an existing Actions-readable token; unavailable usage means no saves.
    for token in ('', os.environ.get('GH_TOKEN', '')):
        headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'd2r-build-cache-budget'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as response:
                return json.load(response)['active_caches_size_in_bytes']
        except (OSError, ValueError, KeyError):
            pass
    return None


def main():
    used = usage(os.environ['GITHUB_REPOSITORY'])
    sizes = {}
    for name, directory in PATHS.items():
        if os.environ.get('SAVE_' + name.upper()) != 'true':
            continue
        files = [p for p in Path(directory).rglob('*') if p.is_file()]
        if files:
            # An uncompressed upper bound also covers tar headers and padding.
            sizes[name] = sum(p.stat().st_size + 4096 for p in files) + 16 * 1024**2
    selected = choose(used, sizes) if used is not None else dict.fromkeys(ORDER, False)
    with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
        for name, enabled in selected.items():
            f.write(f'{name}={str(enabled).lower()}\n')
    print('Optional cache saves:', json.dumps(selected), '; existing caches are never deleted')


if __name__ == '__main__':
    main()
