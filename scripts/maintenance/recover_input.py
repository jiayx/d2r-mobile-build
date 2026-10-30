"""Run only the historically documented input download/extraction operations."""
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / 'scripts'))
from input_config import download_file

old = root / 'historical-input'
spec = importlib.util.spec_from_file_location('historical_ci', old / 'scripts/ci.py')
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)
# Use main's checksum-verifying Drive downloader for the historical URL.
ci.download = download_file
blocks = re.findall(r'```json\s*(.*?)```', (old / 'README.md').read_text(), re.S)
manifests = [json.loads(block) for block in blocks]
manifests = [m for m in manifests if m.get('kind') == 'packages' and 'key_archive' in m]
if len(manifests) != 1:
    raise ValueError('Expected one historical package input manifest')
override = os.environ.get('RECOVERY_KEY_ARCHIVE', '').strip()
if override:
    source = json.loads(override)
    if (not isinstance(source, dict) or set(source) != {'url', 'sha256'}
            or not isinstance(source['url'], str) or not source['url'].startswith('https://')
            or not re.fullmatch(r'[a-f0-9]{64}', source.get('sha256', ''))):
        raise ValueError('Recovery key archive requires HTTPS url and SHA-256')
    manifests[0]['key_archive'] = source
os.environ['GAME_INPUT_MANIFEST'] = json.dumps(manifests[0])
operation = sys.argv[1]
if operation == 'preflight':
    # Validate availability before downloading multi-gigabyte game packages.
    # Never print key values or upload the working/key directories.
    ci.load_prod_keys(manifests[0])
elif operation == 'download':
    ci.download_game_inputs()
elif operation == 'extract':
    ci.prepare_game()
    # Retain only the original executable inputs for the subsequent refresh.
    import shutil
    destination = root / 'recovered-input/ExeFS'
    destination.mkdir(parents=True, exist_ok=True)
    for name, expected in ci.CONFIG['nso_sha256'].items():
        source = ci.GAME / 'ExeFS' / name
        if ci.sha256(source) != expected:
            raise ValueError('Original executable checksum mismatch: ' + name)
        shutil.copy2(source, destination / name)
    (destination.parent / 'input-report.json').write_text(json.dumps({
        'game_version': ci.CONFIG['game_version'],
        'nso_sha256': ci.CONFIG['nso_sha256'],
        'input_identity': ci.download_identity(manifests[0]),
    }, indent=2) + '\n')
else:
    raise ValueError('Unknown recovery operation')
