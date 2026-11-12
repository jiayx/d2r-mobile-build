"""Track source dependencies for prepared payloads and generated interface resources."""
import ast
import hashlib
from pathlib import Path
import posixpath
import re
import subprocess

ROOTS = ('dm/PRODUCT', 'dm/tools/product.sh', 'dm/gfx/tools/msl_retarget.sh')
SCRIPTS = ('dm/tools/patch_nso.py', 'dm/tools/guest_dylib.py',
           'dm/ios/tools/gen_embed.py', 'dm/gfx/tools/c1_guard.py')

# Reviewed generator revisions that can consume the same prepared output.
# Keep exact content hashes: an unrelated edit must still require new inputs.
COMPATIBLE_GENERATORS = {
    # Copy/validate reflections; imported packages already verify every library's JSON.
    'dm/gfx/tools/msl_retarget.sh': {
        'ec41dab53626ed1499854c39c9d308c02438a3e47c30a07f135b38165f074f72',
        'b443ecdfe3de442922e94ad9269a9aa8c1deb636b9953b8bdc00011111e8ffe2',
        # Terminology-only comment change.
        '111ad4b3a97556abd36a77b26d6a4089c424c01e0a8203f6022b316be7502b8f',
    },
    # Reserve a signature without changing module sections; IPA packaging signs Guest.
    'dm/tools/guest_dylib.py': {
        '19be747a6b26f78039c6fed9e51499761642e9eb35b524e0c93e772f6ceb6d76',
        '9bfe01372d1c3aea0fdcabcfc538e826d531b84d0da037bfd29c942208101527',
    },
    # Register prefilter only; upstream verified all nine rewritten images byte-identical.
    'dm/tools/patch_nso.py': {
        'c9a0c7574547ab945e4648bd6664e86fa4a77de12253a55e7b464232b2cdf274',
        'd0bee134202bcc7c976c2713ffec2881f77b43bbfc24f4ebde17f0886c3dc22e',
        # Android/OHOS branches preserve Apple instructions; the loader accepts
        # old fixup tables without TARGET as Apple (0).
        'f23802979ceeeab8267b724b2d7f1a568b900777eb8718a0471a41317dc744ee',
        '893460fffdc4a130ada06bd01fbf48f9afad920ef1e809cf0a2c4c57e81a920b',
        # Unsupported builds get a clear error; supported build output is unchanged.
        'cd205bcd22eb9d015c58f0fea4d727a2f7e2d16591236990fdfcb7f5366f80ce',
    },
}


def git(upstream, *args):
    return subprocess.check_output(['git', '-C', str(upstream), *args],
                                   stderr=subprocess.DEVNULL).decode()


def python_dependencies(names, scripts, read):
    paths = set()
    pending = [n for n in scripts if n in names]
    while pending:
        name = pending.pop()
        if name in paths:
            continue
        paths.add(name)
        tree = ast.parse(read(name))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(n.name.replace('.', '/') + '.py' for n in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module.replace('.', '/') + '.py')
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.endswith('.py'):
                imports.append(node.value)
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                  and node.func.id == '__import__' and node.args
                  and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                imports.append(node.args[0].value.replace('.', '/') + '.py')
        for child in imports:
            for directory in (posixpath.dirname(name), 'dm/ios/tools', 'dm/tools'):
                candidate = posixpath.normpath(directory + '/' + child)
                if candidate in names and candidate not in paths:
                    pending.append(candidate)
    return paths


def generation_paths(upstream, revision):
    if revision:
        names = set(git(upstream, 'ls-tree', '-r', '--name-only', '-z', revision).split('\0')) - {''}
    else:
        names = {n for n in git(upstream, 'ls-files', '-z', '--cached', '--others', '--exclude-standard').split('\0')
                 if n and (upstream / n).is_file()}

    def read(name):
        return git(upstream, 'show', revision + ':' + name) if revision else (upstream / name).read_text()

    paths = {n for n in names if any(n == p or n.startswith(p + '/') for p in ROOTS)}
    paths.update(n for n in names if n.startswith('dm/data/bootlist_'))
    paths.update(python_dependencies(names, SCRIPTS, read))

    chain = 'dm/gfx/tools/dmsh_chain.py'
    tree = ast.parse(read(chain))
    assignments = [n for n in tree.body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == 'FILES' for t in n.targets)]
    if len(assignments) != 1:
        raise ValueError('Cannot determine upstream shader dependencies')
    paths.add(chain)
    paths.update(posixpath.normpath('dm/gfx/' + n) for n in ast.literal_eval(assignments[0].value))
    paths.discard('dm/gfx/tools/dmsh_chain.lock')
    return paths


def verify_generation(upstream, baseline):
    upstream = Path(upstream)
    if not isinstance(baseline, str) or not re.fullmatch('[a-f0-9]{40}', baseline):
        raise ValueError('Prepared package source commit is invalid')
    try:
        git(upstream, 'cat-file', '-e', baseline + '^{commit}')
    except subprocess.CalledProcessError:
        raise ValueError('Prepared package source commit is missing from this source repository') from None
    changed = set(git(upstream, 'diff', '--name-only', '-z', baseline, '--').split('\0'))
    changed.update(git(upstream, 'ls-files', '--others', '--exclude-standard', '-z').split('\0'))
    changed.discard('')
    if not changed:
        return
    dependencies = generation_paths(upstream, baseline) | generation_paths(upstream, None)
    affected = []
    for name in sorted(changed & dependencies):
        allowed = COMPATIBLE_GENERATORS.get(name, set())
        current = upstream / name
        if allowed and current.is_file():
            before = hashlib.sha256(git(upstream, 'show', baseline + ':' + name).encode()).hexdigest()
            after = hashlib.sha256(current.read_bytes()).hexdigest()
            if before in allowed and after in allowed:
                print('Reused prepared output across reviewed generator change:', name, flush=True)
                continue
        affected.append(name)
    if affected:
        raise ValueError('Selected source changed generation inputs (' + ', '.join(affected[:5]) +
                         '); supply an updated prepared package')
