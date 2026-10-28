"""Read existing public Data parts and Mac prepared programs for TV generation."""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys
import zipfile

import ci
from input_config import download_file, https_url
from source.romfs_input import restore


class SplitReader(io.RawIOBase):
    """Seek across concatenated split ZIP parts without duplicating the archive."""
    def __init__(self, paths):
        self.paths = list(paths)
        self.sizes = [p.stat().st_size for p in self.paths]
        self.position = 0
        self.length = sum(self.sizes)

    def seekable(self): return True
    def readable(self): return True
    def tell(self): return self.position

    def seek(self, offset, whence=0):
        position = offset + (self.position if whence == 1 else self.length if whence == 2 else 0)
        if whence not in (0, 1, 2) or position < 0:
            raise ValueError('Invalid split archive seek')
        self.position = position
        return position

    def read(self, size=-1):
        left = max(0, self.length - self.position) if size < 0 else min(size, max(0, self.length - self.position))
        chunks, start = [], 0
        for p, length in zip(self.paths, self.sizes):
            if left and self.position < start + length:
                offset = self.position - start
                with p.open('rb') as stream:
                    stream.seek(offset)
                    chunk = stream.read(min(left, length - offset))
                chunks.append(chunk); self.position += len(chunk); left -= len(chunk)
            start += length
        return b''.join(chunks)


def configuration():
    data = json.loads(os.environ['DATA_INPUT'])
    if not isinstance(data, dict) or set(data) != {'parts', 'sha256'}:
        raise ValueError('data_input requires parts and combined sha256')
    parts = data['parts']
    if not isinstance(parts, list) or not 1 <= len(parts) <= 16:
        raise ValueError('data_input must contain 1–16 ordered parts')
    for item in parts:
        if set(item) != {'url', 'sha256'} or not re.fullmatch('[a-f0-9]{64}', item['sha256']):
            raise ValueError('Each Data part requires url and SHA-256')
        https_url(item['url'])
    if not re.fullmatch('[a-f0-9]{64}', data['sha256']):
        raise ValueError('Invalid combined Data SHA-256')
    return data


def download():
    data = configuration()
    root = ci.ROOT / '.tvos-data-downloads'
    paths = []
    for index, part in enumerate(data['parts']):
        path = root / ('part-%03d' % index)
        if not path.is_file() or ci.sha256(path) != part['sha256']:
            download_file(part['url'], path, part['sha256'], max_bytes=8 * 1024**3)
        paths.append(path)
    h = hashlib.sha256()
    for path in paths:
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(8 * 1024**2), b''):
                h.update(block)
    if h.hexdigest() != data['sha256']:
        raise ValueError('Combined Data checksum mismatch')
    return paths


def extract_shader_packs(dm, mac, work, paths, environment):
    romfs = restore(mac / 'romfs-inputs.zip', work / 'RomFS')
    manifest = (romfs / 'data/build_manifest.psv').read_text()
    shader_rows = [line.split('|') for line in manifest.splitlines()
                   if len(line.split('|')) >= 11 and '/shaders/' in line.split('|')[9].lower()
                   and line.split('|')[9].endswith('.bin')]
    if not shader_rows:
        raise ValueError('No original shader pack addresses found')
    needed = set()
    for row in shader_rows:
        key = bytes.fromhex(row[6]); needed.add(f'{key[9]:02d}-{key[10]:08d}.data')
    with zipfile.ZipFile(SplitReader(paths)) as archive:
        for name in needed:
            matches = [m for m in archive.infolist() if m.filename.endswith('/data/' + name)]
            if len(matches) != 1 or matches[0].file_size > 2 * 1024**3:
                raise ValueError('Data archive lacks shader source file: ' + name)
            # Restore replaced sparse input with the complete original archive, validated by ZIP CRC.
            with archive.open(matches[0]) as src, (romfs / 'data' / name).open('wb') as dst:
                shutil.copyfileobj(src, dst, 8 * 1024**2)
    packs = work / 'build/cache/dm/dmsh'
    packs.mkdir(parents=True, exist_ok=True)
    env = dict(environment, DMX_ROOT=str(romfs / 'data'))
    for row in shader_rows:
        name = Path(row[9]).name
        subprocess.run([sys.executable, str(dm / 'tools/dmx.py'), 'get',
                        'data:' + row[9], str(packs / name)], env=env, check=True,
                       stdout=subprocess.DEVNULL)
    return romfs, packs


def translate_from_prepared():
    # The upstream translator needs only embedded shader bytes from the main image.
    # Its control-segment hash checks still validate every mapped embedded shader.
    dm, product, packs, cache = map(Path, sys.argv[2:])
    sys.path.insert(0, str(dm / 'verify'))
    import nsoimg
    expected = product / 'main.patched.bin'
    original = nsoimg.load
    def load(path):
        if Path(path) != expected:
            raise ValueError('Unexpected embedded shader image')
        return expected.read_bytes()
    nsoimg.load = load
    os.environ['MAIN'] = str(expected)
    sys.path.insert(0, str(dm / 'gfx/tools'))
    sys.argv = [str(dm / 'gfx/tools/dmsh_build.py'), str(packs), str(cache)]
    try:
        runpy.run_path(sys.argv[0], run_name='__main__')
    finally:
        nsoimg.load = original


if __name__ == '__main__':
    translate_from_prepared()
