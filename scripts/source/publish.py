"""Validate and publish the two native IPA variants in the caller's repository."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ci

INSTALLERS = (('Sideloadly', 'https://sideloadly.io/'), ('iloader', 'https://iloader.app/'),
              ('AltStore Classic', 'https://faq.altstore.io/altstore-classic/your-altstore'),
              ('SideStore', 'https://sidestore.io/'))
INSTALLER_LINKS = ', '.join(f'[{name}]({url})' for name, url in INSTALLERS)
CHINESE_INSTALLER_LINKS = '、'.join(f'[{name}]({url})' for name, url in INSTALLERS)


def notes():
    standard, compatibility = ci.ipa_names()
    base = 'https://github.com/jiayx/d2r-mobile-build/blob/main/'
    english, chinese = (
        f'Source: `{ci.CONFIG["upstream_commit"]}`.\n\n'
        f'- iOS 26 and later: `{standard}`.\n'
        f'- iOS 18–25: `{compatibility}`.\n\n'
        f'Sign and install with {INSTALLER_LINKS}.\n\n'
        'Use matching Data and, for A14–A16 devices, the Legacy Device Pack '
        'for this game version. Imported matching resources can be reused. '
        'Metal shaders are included precompiled. This build has not been tested on a physical device.\n\n'
        f'For downloads and installation, see the [README]({base}README.md).',
        f'源码：`{ci.CONFIG["upstream_commit"]}`。\n\n'
        f'- iOS 26 及以上：`{standard}`。\n'
        f'- iOS 18–25：`{compatibility}`。\n\n'
        f'使用 {CHINESE_INSTALLER_LINKS} 签名安装。\n\n'
        '使用配套 Data；A14–A16 设备另需 Legacy Device Pack。'
        '已导入的相同资源可以继续复用。包内已包含预编译 Metal 着色器。此构建未进行真机测试。\n\n'
        f'下载和安装方式见[中文 README]({base}README.zh-CN.md)。')
    return '[English](#english) | [简体中文](#简体中文)\n\n## English\n\n' + english + '\n\n---\n\n## 简体中文\n\n' + chinese + '\n'


def gh(*args):
    return subprocess.check_output(['gh', *map(str, args)], text=True).strip()


def release_info(repo, tag):
    result = subprocess.run(['gh', 'api', f'repos/{repo}/releases/tags/{tag}'],
                            text=True, capture_output=True)
    if not result.returncode:
        return json.loads(result.stdout)
    if 'HTTP 404' not in result.stderr:
        raise RuntimeError('Could not inspect Release: ' + result.stderr.strip())
    pages = json.loads(gh('api', '--paginate', '--slurp', f'repos/{repo}/releases?per_page=100'))
    return next((r for page in pages for r in page if r['tag_name'] == tag), None)


def upload_verified(repo, tag, paths):
    current = {a['name']: a for a in release_info(repo, tag)['assets']}
    expected, pending = {}, []
    for path in paths:
        digest, size = ci.sha256(path), path.stat().st_size
        expected[path.name] = (digest, size)
        asset = current.get(path.name, {})
        if asset.get('state') != 'uploaded' or asset.get('digest') != 'sha256:' + digest or asset.get('size') != size:
            pending.append(path)
    def upload(path):
        gh('release', 'upload', tag, path, '--repo', repo, '--clobber')
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(upload, pending))
    actual = {a['name']: a for a in release_info(repo, tag)['assets']}
    for name, (digest, size) in expected.items():
        item = actual.get(name, {})
        if item.get('state') != 'uploaded' or item.get('digest') != 'sha256:' + digest or item.get('size') != size:
            raise ValueError('Uploaded asset missing or SHA256 mismatch: ' + name)


def collect_packages(out):
    reports = [json.loads((out / name).read_text()) for name in
               ('source-report.json', 'source-ios18-report.json')]
    common = ('source_commit', 'tools_commit', 'product', 'payload_sha256', 'legacy_pack',
              'app_version', 'build_number', 'release_tag', 'shader_chain', 'metal_toolchain',
              'prepared_archive_sha256', 'resource_manifest_sha256', 'runtime_resources_sha256')
    for key in common:
        if reports[0][key] != reports[1][key]:
            raise ValueError('IPA variants use different build inputs: ' + key)
    names = ci.ipa_names()
    paths = []
    for report, name, minimum in zip(reports, names, ('26.0', '18.0')):
        if report['ipa_name'] != name or report['minimum_os'] != minimum or report['native_minimum_os'] != minimum + '.0':
            raise ValueError('IPA filename or minimum system mismatch')
        for field, key in (('source_commit', 'upstream_commit'), ('app_version', 'app_version'),
                           ('build_number', 'build_number'), ('release_tag', 'release_tag')):
            if report[field] != ci.CONFIG[key]:
                raise ValueError('IPA build identity mismatch: ' + field)
        if (not report['native_built_from_source'] or not report['payload_verified']
                or not report['metal_precompiled'] or report['phone_shader_compilation_required'] is not False):
            raise ValueError('IPA native or payload verification missing')
        path = out / name
        if path.stat().st_size != report['ipa_bytes'] or ci.sha256(path) != report['ipa_sha256']:
            raise ValueError('IPA checksum mismatch: ' + name)
        paths.append(path)
    (out / 'build-report.json').write_text(json.dumps(dict(reports[0], packages=reports), indent=2) + '\n')
    (out / 'SHA256SUMS.txt').write_text(''.join(f"{r['ipa_sha256']}  {r['ipa_name']}\n" for r in reports))
    return paths


def publish_assets(repo, tag, title, body, paths):
    release = release_info(repo, tag)
    if release is None:
        gh('release', 'create', tag, '--repo', repo, '--target', os.environ['GITHUB_SHA'],
           '--title', title, '--notes-file', body, '--draft')
        for attempt in range(6):
            release = release_info(repo, tag)
            if release is not None:
                break
            time.sleep(min(2 ** attempt, 8))
        else:
            raise RuntimeError('Created Release is not visible after retrying')
    if release.get('immutable'):
        raise ValueError('Cannot update an immutable Release')
    upload_verified(repo, tag, paths)
    gh('release', 'edit', tag, '--repo', repo, '--notes-file', body, '--title', title,
       '--draft=false', '--latest=true')
    release = release_info(repo, tag)
    if not release or release['draft']:
        raise RuntimeError('Release did not become published')
    print('Published verified packages:', release['html_url'], flush=True)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
            summary.write(f"\n[Download packages]({release['html_url']})\n")
    return release


def main():
    repo = os.environ['GITHUB_REPOSITORY']
    out = ci.ROOT / 'outputs'
    paths = collect_packages(out)
    body = out / 'RELEASE.md'
    body.write_text(notes())
    title = f"{ci.build_label()} · build {ci.CONFIG['build_number']}"
    return publish_assets(repo, ci.release_tag(), title, body,
                          [*paths, out / 'SHA256SUMS.txt', out / 'build-report.json'])


if __name__ == '__main__':
    main()
