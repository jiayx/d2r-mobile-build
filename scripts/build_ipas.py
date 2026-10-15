#!/usr/bin/env python3
"""Package both official shells with the same generated game and legacy pack."""
import json
import os
import copy
from pathlib import Path
import subprocess
import sys
import time
import zipfile

import ci

VARIANTS = tuple(zip(ci.ipa_names(),
                     ci.SHELL_NAMES,
                     ('26.0', '18.0')))


def reuse_payload(source, source_shell, target_shell, destination):
    """Put the generated payload into another matching official shell."""
    if ci.shell_info(source_shell) != ci.shell_info(target_shell):
        raise ValueError('Cannot share payload between incompatible shells')
    with zipfile.ZipFile(source_shell) as original, zipfile.ZipFile(target_shell) as target, zipfile.ZipFile(source) as built:
        def base(archive):
            roots = [n.removesuffix('dm/shell_manifest.txt') for n in archive.namelist()
                     if n.endswith('/dm/shell_manifest.txt')]
            if len(roots) != 1:
                raise ValueError('Shell app path ambiguous')
            return roots[0]
        old_base, new_base = base(original), base(target)
        if original.read(old_base + 'dm/shell_manifest.txt') != target.read(new_base + 'dm/shell_manifest.txt'):
            raise ValueError('Cannot share payload between different shell manifests')
        originals, targets = set(original.namelist()), set(target.namelist())
        additions = []
        names = set()
        for entry in built.infolist():
            if entry.filename in originals:
                continue
            if not entry.filename.startswith(old_base):
                raise ValueError('Generated payload is outside the app')
            relative = entry.filename.removeprefix(old_base)
            if '..' in relative.split('/') or not relative:
                raise ValueError('Invalid generated payload path')
            name = new_base + relative
            if name in targets or name in names:
                raise ValueError('Generated payload would replace a shell member')
            names.add(name)
            additions.append((entry, name))
        if not additions:
            raise ValueError('No generated payload to reuse')
        partial = Path(str(destination) + '.part')
        try:
            with zipfile.ZipFile(partial, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as out:
                for entry in target.infolist():
                    out.writestr(entry, target.read(entry))
                for entry, name in additions:
                    renamed = copy.copy(entry)
                    renamed.filename = name
                    out.writestr(renamed, built.read(entry))
            partial.replace(destination)
        finally:
            partial.unlink(missing_ok=True)
    print('Reused generated payload:', len(additions), 'members;', Path(destination).name, flush=True)


def main(first_built=None):
    output = ci.ROOT / 'outputs'
    output.mkdir(exist_ok=True)
    pack = Path(os.environ['D2RM_ASTC_PACK'])
    reports = []
    first = None
    for name, shell, minimum in VARIANTS:
        started = time.monotonic()
        shell_path = ci.TOOLS / shell
        if ci.sha256(shell_path) != ci.CONFIG['shell_sha256' if minimum == '26.0' else 'ios18_shell_sha256']:
            raise ValueError('Official shell SHA256 mismatch: ' + shell)
        if first is None:
            if first_built is None:
                subprocess.run([sys.executable, str(ci.ROOT / 'upstream/dm/tools/d2rm_pack.py'),
                                str(shell_path), str(ci.GAME), str(output / name)], check=True)
            elif Path(first_built).resolve() != (output / name).resolve():
                raise ValueError('Prebuilt first IPA has an unexpected path')
        else:
            reuse_payload(first[0], first[1], shell_path, output / name)
        report = ci.verify_ipa(output / name, shell_path, minimum, pack)
        report.update(build_seconds=round(time.monotonic() - started, 2),
                      reused_payload_from=Path(first[0]).name if first else None)
        reports.append(report)
        if first is None:
            first = (output / name, shell_path)
    report = dict(reports[0], packages=reports,
                  legacy_pack=json.loads((pack / 'pack.json').read_text()))
    (output / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n')
    (output / 'SHA256SUMS.txt').write_text(''.join(
        f"{r['ipa_sha256']}  {r['ipa_name']}\n" for r in reports))
    print('Build report:', json.dumps(report, sort_keys=True), flush=True)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write(f'version={ci.upstream_version()}\n')


if __name__ == '__main__':
    main()
