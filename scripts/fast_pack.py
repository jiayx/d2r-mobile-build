"""Keep Linux-generated art and legacy packs; finish CPU-heavy shell inputs on macOS."""
import argparse
import ast
import concurrent.futures
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile

import ci

CACHE = ci.ROOT / '.fast-payload'
REWRITE = ci.ROOT / '.fast-rewrite'
SHADERS = ci.ROOT / '.fast-shaders'
MAX_BYTES = 3 * 1024**3


def output(**values):
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            for key, value in values.items():
                f.write(f'{key}={str(value).lower() if isinstance(value, bool) else value}\n')


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')


def identity(files, values):
    h = hashlib.sha256(json.dumps(values, sort_keys=True).encode())
    for name, path in sorted(files.items()):
        h.update(name.encode() + b'\0' + Path(path).read_bytes() + b'\0')
    return h.hexdigest()


def keys():
    upstream = ci.ROOT / 'upstream'
    source = subprocess.check_output(['git', '-C', str(upstream), 'rev-parse', 'HEAD'], text=True).strip()
    if source != ci.CONFIG['upstream_commit']:
        raise ValueError('The official-shell fast path requires its matching source commit')
    files = {name: ci.ROOT / name for name in
             ('scripts/fast_pack.py', 'scripts/build_ipas.py', 'scripts/ci.py', 'requirements.txt')}
    key = identity(files, {'config': ci.CONFIG, 'source': source, 'input': os.environ['INPUT_REVISION']})
    rewrite_files = {'patch_nso.py': upstream / 'dm/tools/patch_nso.py'}
    rewrite_files.update({p.relative_to(upstream).as_posix(): p for p in (upstream / 'dm/data').glob('bootlist*.tsv')})
    rewrite_key = identity(rewrite_files, {'nso': ci.CONFIG['nso_sha256'], 'ruleset': 'touch-run-v4',
                                         'requirements': (ci.ROOT / 'requirements.txt').read_text()})
    tools = subprocess.check_output(['git', '-C', str(ci.ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    output(key=key, rewrite_key=rewrite_key, source_commit=source, tools_commit=tools)
    return key, rewrite_key


def receipt(directory, key):
    directory = Path(directory)
    info = read(directory / 'receipt.json')
    if info['key'] != key or not info['files']:
        raise ValueError('Cached stage recipe differs')
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file()}
    if actual != set(info['files']) | {'receipt.json'}:
        raise ValueError('Cached stage is incomplete')
    for name, expected in info['files'].items():
        path = directory / name
        if (Path(name).is_absolute() or '..' in Path(name).parts or path.is_symlink()
                or path.stat().st_size != expected['bytes'] or ci.sha256(path) != expected['sha256']):
            raise ValueError('Cached stage checksum differs')
    return info


def seal(directory, key, **metadata):
    directory = Path(directory)
    files = {p.relative_to(directory).as_posix(): {'sha256': ci.sha256(p), 'bytes': p.stat().st_size}
             for p in directory.rglob('*') if p.is_file() and p != directory / 'receipt.json'}
    write(directory / 'receipt.json', dict(metadata, key=key, files=files))


def base(z):
    roots = [n.removesuffix('dm/shell_manifest.txt') for n in z.namelist()
             if n.endswith('/dm/shell_manifest.txt')]
    if len(roots) != 1:
        raise ValueError('Ambiguous official shell app')
    return roots[0]


def cached_payload(key):
    try:
        info = receipt(CACHE, key)
        for name, checksum in zip(ci.SHELL_NAMES, (ci.CONFIG['shell_sha256'], ci.CONFIG['ios18_shell_sha256'])):
            if ci.sha256(CACHE / 'shells' / name) != checksum:
                return None
        with zipfile.ZipFile(CACHE / 'payload.zip') as z:
            names = z.namelist()
            if (not names or len(names) != len(set(names)) or
                    any(Path(n).is_absolute() or '..' in Path(n).parts or '\\' in n for n in names)):
                return None
            if z.read('Frameworks/Guest.framework/Guest')[:8] != bytes.fromhex('cffaedfe0c000001'):
                return None
        return info
    except (OSError, ValueError, KeyError, zipfile.BadZipFile):
        return None


def check():
    key, _ = keys()
    info = cached_payload(key)
    if info:
        ci.TOOLS.mkdir(exist_ok=True)
        for name in ci.SHELL_NAMES:
            shutil.copy2(CACHE / 'shells' / name, ci.TOOLS / name)
        out = ci.ROOT / 'outputs'
        out.mkdir(exist_ok=True)
        for p in (CACHE / 'metadata').iterdir():
            shutil.copy2(p, out / p.name)
        pack = ci.DM / 'build/legacy/pack'
        pack.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out / 'pack.json', pack / 'pack.json')
        shutil.copy2(out / 'pack_index.tsv', pack / 'pack_index.tsv')
        os.environ['D2RM_ASTC_PACK'] = str(pack)
        if os.environ.get('GITHUB_ENV'):
            with open(os.environ['GITHUB_ENV'], 'a') as f:
                f.write('D2RM_ASTC_PACK=' + str(pack) + '\n')
    needs_game = not bool(info)
    if info and os.environ.get('PUBLISH_RELEASE') == 'true':
        import publish_release as publish
        repo = os.environ['GITHUB_REPOSITORY']
        reference = publish.find_resources(repo, read(ci.ROOT / 'outputs/resource-manifest.json'))
        needs_game = reference is None
    output(reused=bool(info), needs_game=needs_game)
    print('Verified complete shell payload cache:', bool(info), 'game input needed:', needs_game, flush=True)


def load_packer():
    path = ci.ROOT / 'upstream/dm/tools/d2rm_pack.py'
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location('upstream_shell_packer', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def phase_nodes(source):
    """Split at explicit upstream stage boundaries; retain upstream final validation."""
    tree = ast.parse(source)
    mains = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main']
    if len(mains) != 1:
        raise ValueError('Cannot locate upstream shell packer entrypoint')
    body = mains[0].body
    def assignment(node, name):
        return isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets)
    shaders = [i for i, n in enumerate(body) if assignment(n, 'packs')]
    copies = [i for i, n in enumerate(body) if assignment(n, 'lib')]
    rewrites = [i for i, n in enumerate(body) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                and isinstance(n.value.func, ast.Name) and n.value.func.id == 'step'
                and len(n.value.args) == 3 and isinstance(n.value.args[2], ast.Name) and n.value.args[2].id == 'patch']
    if len(shaders) != 1 or len(copies) != 1 or len(rewrites) != 1 or not rewrites[0] < shaders[0] < copies[0]:
        raise ValueError('Upstream packer stage boundaries changed; adapt the fast path before building')
    prefix = copy.deepcopy(mains[0])
    prefix.body = [copy.deepcopy(n) for i, n in enumerate(body[:shaders[0]]) if i != rewrites[0]]
    prefix.body.append(ast.Return(value=ast.Call(func=ast.Name(id='locals', ctx=ast.Load()), args=[], keywords=[])))
    return prefix, copy.deepcopy(body[shaders[0]:]), copy.deepcopy(body[copies[0]:])


def compiled(module, phase):
    code = ast.fix_missing_locations(ast.Module(body=phase, type_ignores=[]))
    return compile(code, str(module.__file__), 'exec')


def rewrite_valid(directory):
    directory = Path(directory)
    required = [directory / (m + suffix) for m in ('main', 'sdk')
                for suffix in ('.patched.bin', '.fixups.tsv', '.gates.tsv', '.cuts.tsv')]
    try:
        return (all(p.is_file() for p in required) and
                (directory / 'build_src.sha256').read_text().split()[0] == ci.sha256(ci.ROOT / 'upstream/dm/tools/patch_nso.py'))
    except (OSError, IndexError):
        return False


def shader_valid(module, directory, chain):
    mac = Path(directory) / 'mac'
    ios = Path(directory) / 'ios'
    try:
        rows = read(mac / '_b_build.json')
        if not rows or any(r['st'] != 'ok' for r in rows):
            return False
        if module.src_digest(str(mac)) != ci.shell_info(ci.SHELL)['SHADER_SRC']:
            return False
        for row in rows:
            name = row['key'] + '_b'
            if not (ios / (name + '.metallib')).is_file() or read(ios / (name + '.json'))['chain'] != chain:
                return False
        return True
    except (OSError, ValueError, KeyError):
        return False


def prepare():
    key, rewrite_key = keys()
    module = load_packer()
    prefix, _, _ = phase_nodes(Path(module.__file__).read_text())
    exec(compiled(module, [prefix]), module.__dict__)
    old = sys.argv
    sys.argv = [str(module.__file__), str(ci.SHELL), str(ci.GAME), str(ci.ROOT / 'outputs' / ci.ipa_names()[0])]
    try:
        context = module.main()
    finally:
        sys.argv = old
    context['z'].close()
    bundle = ci.ROOT / 'outputs/mac-pack-input'
    shutil.rmtree(bundle, ignore_errors=True)
    bundle.mkdir()
    shutil.copytree(context['stage'], bundle / 'stage', ignore=shutil.ignore_patterns('*.log'))
    (bundle / 'ExeFS').mkdir()
    for name in ('main', 'sdk'):
        shutil.copy2(ci.GAME / 'ExeFS' / name, bundle / 'ExeFS' / name)
    (bundle / 'shells').mkdir()
    for name in ci.SHELL_NAMES:
        shutil.copy2(ci.TOOLS / name, bundle / 'shells' / name)
    metadata = bundle / 'metadata'
    metadata.mkdir()
    for name in ('resource-manifest.json', 'legacy-resources.json', 'resources.json', 'RESOURCE-INSTALL.txt'):
        path = ci.ROOT / 'outputs' / name
        if path.is_file():
            shutil.copy2(path, metadata / name)
    for name in ('pack.json', 'pack_index.tsv'):
        shutil.copy2(Path(os.environ['D2RM_ASTC_PACK']) / name, metadata / name)
    if rewrite_valid(context['out']):
        shutil.copytree(context['out'], bundle / 'rewrite', ignore=shutil.ignore_patterns('*.log'))
    chain = subprocess.check_output([sys.executable, str(ci.ROOT / 'upstream/dm/gfx/tools/nometal_run.py'),
                                    str(ci.ROOT / 'upstream/dm/gfx/tools/dmsh_chain.py')], text=True).strip().splitlines()[-1]
    candidate = bundle / 'shaders'
    for folder, original in (('mac', ci.DM / 'build/cache/metal_shader_cache' / ('b-' + chain)),
                             ('ios', ci.DM / 'build/ios/dmsh_b' / ('b-' + chain))):
        if original.is_dir():
            shutil.copytree(original, candidate / folder)
    if not shader_valid(module, candidate, chain):
        shutil.rmtree(candidate, ignore_errors=True)
        packs = ci.DM / 'build/cache/dm/dmsh'
        packs.mkdir(parents=True, exist_ok=True)
        if len(list(packs.glob('*.bin'))) != 162:
            env = dict(os.environ, DMX_ROOT=str(ci.GAME / 'RomFS/data'))
            dmx = ci.ROOT / 'upstream/dm/tools/dmx.py'
            rows = subprocess.check_output([sys.executable, str(dmx), 'list', 'data:data/hd/shaders/*.bin'], env=env, text=True)
            for row in rows.splitlines():
                name = row.split('\t')[0]
                if name:
                    subprocess.run([sys.executable, str(dmx), 'get', name, str(packs / Path(name).name)], env=env, check=True)
        (bundle / 'packs').mkdir()
        for path in packs.glob('*.bin'):
            shutil.copy2(path, bundle / 'packs' / path.name)
        if len(list((bundle / 'packs').iterdir())) != 162:
            raise ValueError('Incomplete shader input packages')
    info = {'payload_key': key, 'rewrite_key': rewrite_key, 'shader_key': os.environ['SHADER_KEY'],
            'producer_shader_chain': chain, 'extra': context['extra'], 'config': ci.CONFIG}
    seal(bundle, key, **info)
    with tarfile.open(ci.ROOT / 'outputs/mac-pack-inputs.tar.gz', 'w:gz') as tf:
        for p in sorted(bundle.rglob('*')):
            if p.is_file():
                tf.add(p, arcname=p.relative_to(bundle).as_posix())
    output(bundle=True, version=ci.upstream_version())
    print('Prepared compact macOS inputs; original download and Linux caches retained', flush=True)


def unpack():
    bundle = ci.ROOT / '.mac-pack-input'
    shutil.rmtree(bundle, ignore_errors=True)
    with tarfile.open(ci.ROOT / 'outputs/mac-pack-inputs.tar.gz') as tf:
        seen = set()
        size = 0
        for member in tf:
            p = Path(member.name)
            size += member.size
            if (not member.isfile() or p.is_absolute() or '..' in p.parts or '\\' in member.name
                    or member.name in seen or size > MAX_BYTES):
                raise ValueError('Unsafe or oversized macOS input package')
            seen.add(member.name)
            dest = bundle / p
            dest.parent.mkdir(parents=True, exist_ok=True)
            with tf.extractfile(member) as src, dest.open('wb') as dst:
                shutil.copyfileobj(src, dst)
    key, _ = keys()
    info = receipt(bundle, key)
    if info['config'] != ci.CONFIG:
        raise ValueError('macOS input configuration differs')
    ci.TOOLS.mkdir(exist_ok=True)
    for name, checksum in zip(ci.SHELL_NAMES, (ci.CONFIG['shell_sha256'], ci.CONFIG['ios18_shell_sha256'])):
        path = bundle / 'shells' / name
        if ci.sha256(path) != checksum:
            raise ValueError('Official shell checksum differs')
        shutil.copy2(path, ci.TOOLS / name)
    for name in ('main', 'sdk'):
        if ci.sha256(bundle / 'ExeFS' / name) != ci.CONFIG['nso_sha256'][name]:
            raise ValueError('Original NSO checksum differs')
    needs_shaders = not (bundle / 'shaders').is_dir()
    if needs_shaders:
        try:
            saved = receipt(SHADERS, info['shader_key'])
            needs_shaders = not shader_valid(load_packer(), SHADERS, saved['chain'])
        except (OSError, ValueError, KeyError):
            pass
    output(needs_shaders=needs_shaders, rewrite_key=info['rewrite_key'], shader_key=info['shader_key'])
    return bundle, info


def tools():
    destination = ci.ROOT / '.mac-pack-tools'
    spirv = destination / 'bin/spirv-cross'
    xlate = destination / 'dmsh_xlate/dmsh_xlate'
    if not spirv.is_file():
        commit = ci.CONFIG['spirv_commit']
        with tempfile.TemporaryDirectory(prefix='mac-spirv-') as temporary:
            source = Path(temporary) / 'source'
            subprocess.run(['git', 'clone', '--quiet', 'https://github.com/KhronosGroup/SPIRV-Cross.git', str(source)], check=True)
            subprocess.run(['git', '-C', str(source), 'checkout', '--quiet', commit], check=True)
            build = Path(temporary) / 'build'
            subprocess.run(['cmake', '-S', str(source), '-B', str(build), '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=Release',
                            '-DCMAKE_CXX_COMPILER=clang++', '-DSPIRV_CROSS_ENABLE_TESTS=OFF'], check=True)
            subprocess.run(['cmake', '--build', str(build), '--target', 'spirv-cross', '-j', '4'], check=True)
            spirv.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(build / 'spirv-cross', spirv)
    if not xlate.is_file():
        subprocess.run(['dotnet', 'publish', 'upstream/dm/gfx/tools/dmsh_xlate', '-c', 'Release',
                        '-o', str(xlate.parent), '-v', 'quiet'], check=True)
    target = ci.DM / 'build/gfx/dmsh_xlate'
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(xlate.parent, target)
    os.environ['PATH'] = str(spirv.parent) + os.pathsep + os.environ['PATH']
    return destination


def rewrite(bundle, info):
    target = ci.DM / 'build/cache/dm/out' / ((ci.ROOT / 'upstream/dm/PRODUCT').read_text().strip() + '-touch')
    reused = False
    if (bundle / 'rewrite').is_dir() and rewrite_valid(bundle / 'rewrite'):
        source = bundle / 'rewrite'
        reused = True
    else:
        try:
            receipt(REWRITE, info['rewrite_key'])
            if not rewrite_valid(REWRITE / 'out'):
                raise ValueError('Incomplete rewritten program cache')
            source = REWRITE / 'out'
            reused = True
        except (OSError, ValueError, KeyError):
            source = ci.ROOT / '.rewrite-work'
            shutil.rmtree(source, ignore_errors=True)
            source.mkdir()
            def one(name):
                directory = source / name
                directory.mkdir()
                with (source / (name + '.log')).open('w') as log:
                    subprocess.run([sys.executable, 'upstream/dm/tools/patch_nso.py', str(bundle / 'ExeFS' / name),
                                    str(directory), name], env=dict(os.environ, DM_RULESET='touch-run-v4'),
                                   stdout=log, stderr=subprocess.STDOUT, check=True)
                return directory
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                directories = list(pool.map(one, ('main', 'sdk')))
            merged = source / 'merged'
            merged.mkdir()
            for directory in directories:
                for p in directory.iterdir():
                    dest = merged / p.name
                    if dest.exists() and ci.sha256(dest) != ci.sha256(p):
                        raise ValueError('Parallel rewrites produced conflicting shared files')
                    shutil.copy2(p, dest)
            source = merged
    if not rewrite_valid(source):
        raise ValueError('Rewritten game modules are incomplete')
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(source, target)
    if not reused or source != REWRITE / 'out':
        shutil.rmtree(REWRITE, ignore_errors=True)
        shutil.copytree(target, REWRITE / 'out')
        seal(REWRITE, info['rewrite_key'], producer=platform.system())
    return target, reused


def finish():
    started = time.monotonic()
    bundle, info = unpack()
    module = load_packer()
    _, all_suffix, cached_suffix = phase_nodes(Path(module.__file__).read_text())
    stage = ci.DM / 'build/pack/stage'
    shutil.rmtree(stage, ignore_errors=True)
    shutil.copytree(bundle / 'stage', stage)
    out, rewrite_reused = rewrite(bundle, info)
    shader_source = None
    chain = None
    if (bundle / 'shaders').is_dir() and shader_valid(module, bundle / 'shaders', info['producer_shader_chain']):
        shader_source, chain = bundle / 'shaders', info['producer_shader_chain']
    else:
        try:
            saved = receipt(SHADERS, info['shader_key'])
            if shader_valid(module, SHADERS, saved['chain']):
                shader_source, chain = SHADERS, saved['chain']
        except (OSError, ValueError, KeyError):
            pass
    shader_reused = shader_source is not None
    if shader_source:
        for folder, destination in (('mac', ci.DM / 'build/cache/metal_shader_cache' / ('b-' + chain)),
                                    ('ios', ci.DM / 'build/ios/dmsh_b' / ('b-' + chain))):
            shutil.rmtree(destination, ignore_errors=True)
            shutil.copytree(shader_source / folder, destination)
    else:
        tools()
        packs = ci.DM / 'build/cache/dm/dmsh'
        shutil.rmtree(packs, ignore_errors=True)
        shutil.copytree(bundle / 'packs', packs)
        game = ci.DM / 'fast-game'
        shutil.copytree(bundle / 'ExeFS', game / 'ExeFS', dirs_exist_ok=True)
    shell = str(ci.SHELL)
    z, app, manifest, shell_info, exe = module.read_shell(shell)
    gt = lambda script, *args: [sys.executable, str(ci.ROOT / 'upstream/dm/gfx/tools/nometal_run.py'),
                               str(ci.ROOT / 'upstream/dm/gfx/tools' / script), *args]
    game = str(ci.DM / 'fast-game')
    first = ci.ROOT / 'outputs' / ci.ipa_names()[0]
    namespace = dict(module.__dict__, shell=shell, game=game, out_ipa=str(first), z=z, base=app,
                     manifest=manifest, info=shell_info, exe=exe, P=(ci.ROOT / 'upstream/dm/PRODUCT').read_text().strip(),
                     chain=shell_info['CHAIN'], dotnet=shutil.which('dotnet') or 'dotnet', nometal=True, gt=gt,
                     romfs=str(Path(game) / 'RomFS'), stage=str(stage), out=str(out), extra=info['extra'])
    if shader_reused:
        namespace.update(local=chain, mac_cache=str(ci.DM / 'build/cache/metal_shader_cache'),
                         ios_out=str(ci.DM / 'build/ios/dmsh_b'))
    try:
        exec(compiled(module, cached_suffix if shader_reused else all_suffix), namespace)
    finally:
        z.close()
    if not shader_reused:
        chain = namespace['local']
        shutil.rmtree(SHADERS, ignore_errors=True)
        for folder, source in (('mac', ci.DM / 'build/cache/metal_shader_cache' / ('b-' + chain)),
                               ('ios', ci.DM / 'build/ios/dmsh_b' / ('b-' + chain))):
            shutil.copytree(source, SHADERS / folder)
        if not shader_valid(module, SHADERS, chain):
            raise ValueError('Generated shaders failed completeness and official-source checks')
        seal(SHADERS, info['shader_key'], chain=chain, producer=platform.system())
    outdir = ci.ROOT / 'outputs'
    for p in (bundle / 'metadata').iterdir():
        shutil.copy2(p, outdir / p.name)
    pack = ci.DM / 'build/legacy/pack'
    pack.mkdir(parents=True, exist_ok=True)
    for name in ('pack.json', 'pack_index.tsv'):
        shutil.copy2(outdir / name, pack / name)
    os.environ['D2RM_ASTC_PACK'] = str(pack)
    import build_ipas
    build_ipas.main(first_built=first)
    report = read(outdir / 'build-report.json')
    report.update(payload_reused=False, rewrite_reused=rewrite_reused, shader_reused=shader_reused,
                  generation_platform=platform.system(), generation_seconds=round(time.monotonic()-started, 2))
    write(outdir / 'build-report.json', report)
    save_payload(first, key=info['payload_key'], metadata=bundle / 'metadata', report=report)
    output(version=ci.upstream_version(), rewrite_reused=rewrite_reused, shader_reused=shader_reused)


def save_payload(ipa, key, metadata, report):
    shutil.rmtree(CACHE, ignore_errors=True)
    CACHE.mkdir()
    with zipfile.ZipFile(ci.SHELL) as shell, zipfile.ZipFile(ipa) as built, zipfile.ZipFile(CACHE / 'payload.zip', 'w') as payload:
        original = set(shell.namelist())
        app = base(shell)
        for item in built.infolist():
            if item.filename in original:
                continue
            if not item.filename.startswith(app):
                raise ValueError('Generated payload is outside the app')
            renamed = copy.copy(item)
            renamed.filename = item.filename.removeprefix(app)
            payload.writestr(renamed, built.read(item))
    shutil.copytree(metadata, CACHE / 'metadata')
    (CACHE / 'shells').mkdir()
    for name in ci.SHELL_NAMES:
        shutil.copy2(ci.TOOLS / name, CACHE / 'shells' / name)
    seal(CACHE, key, producer=report['generation_platform'], shader_chain=report['shader_chain'])
    if not cached_payload(key):
        raise ValueError('Complete payload cache verification failed')


def assemble():
    key, _ = keys()
    info = cached_payload(key)
    if not info:
        raise ValueError('Verified complete payload cache missing')
    first = ci.ROOT / 'outputs' / ci.ipa_names()[0]
    with zipfile.ZipFile(ci.SHELL) as shell, zipfile.ZipFile(CACHE / 'payload.zip') as payload, zipfile.ZipFile(first, 'w') as z:
        app = base(shell)
        originals = set(shell.namelist())
        for item in shell.infolist():
            z.writestr(item, shell.read(item))
        for item in payload.infolist():
            renamed = copy.copy(item)
            renamed.filename = app + item.filename
            if renamed.filename in originals:
                raise ValueError('Cached payload would replace an official shell member')
            z.writestr(renamed, payload.read(item))
    import build_ipas
    build_ipas.main(first_built=first)
    report = read(ci.ROOT / 'outputs/build-report.json')
    report.update(payload_reused=True, rewrite_reused=True, shader_reused=True, generation_platform=info['producer'])
    write(ci.ROOT / 'outputs/build-report.json', report)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('keys', 'check', 'prepare', 'inspect', 'finish', 'assemble'))
    args = parser.parse_args()
    {'keys': keys, 'check': check, 'prepare': prepare, 'inspect': unpack, 'finish': finish, 'assemble': assemble}[args.command]()
