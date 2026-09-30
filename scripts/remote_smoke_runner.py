"""Run the small, inspectable smoke test in an already connected target."""
import argparse
import io
import json
from pathlib import Path
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from remote_workspaces import RemoteWorkspaceManager, _run, INSTALL_CODE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('connection_id')
    parser.add_argument('--model-env', default='')
    args = parser.parse_args()
    profile = RemoteWorkspaceManager(ROOT).get(args.connection_id)
    if not profile or not profile.get('runtimeRoot'):
        raise ValueError('Connect this profile first')
    if args.model_env and profile['kind'] != 'wsl':
        raise ValueError('This runner does not transfer host credentials to SSH')
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode='w:gz') as archive:
        archive.add(ROOT / 'scripts/remote_functional_smoke.py', arcname='app/scripts/remote_functional_smoke.py')
    _run(profile, ['python3', '-c', INSTALL_CODE, profile['id']], data=payload.getvalue(), timeout=120)
    app = profile['runtimeRoot'] + '/app'
    argv = ['env', f'PYTHONPATH={app}/.deps:{app}', 'python3', app + '/scripts/remote_functional_smoke.py', '--port', str(profile['port'])]
    if args.model_env:
        argv.extend(['--model-env', args.model_env])
    output = _run(profile, argv, timeout=180)
    print(output)
    report = json.loads(output.splitlines()[-1])
    path = ROOT / '.runtime' / f'remote-smoke-{profile["id"]}.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
