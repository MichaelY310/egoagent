"""Run a cookbook recipe, optionally continuing its Session or checkpoint.

python examples/cookbook/run.py --stage 1
python examples/cookbook/run.py --stage 9 --session <printed-directory>
python examples/cookbook/run.py --stage 10 --resume-checkpoint <printed-path>
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_factory import AgentFactory
from harness import Harness, Session
from llm.env_config import load_local_env
from pipeline_engine import run_pipeline


def recipes():
    return sorted((ROOT / 'harness').glob('cookbook_*/config.json'))


def create_recipe(stage, workspace, *, provider=None, session_dir=None):
    paths = recipes()
    if not 1 <= stage <= len(paths):
        raise ValueError(f'stage must be between 1 and {len(paths)}')
    path = paths[stage - 1]
    config = json.loads(path.read_text(encoding='utf-8'))
    workspace = Path(workspace).resolve()
    if not workspace.is_dir():
        raise ValueError(f'Workspace does not exist: {workspace}')
    factory = AgentFactory(identity_roots=[ROOT / 'identity'])
    agents = factory.create_slots(
        {slot: spec['identity'] for slot, spec in config['slots'].items()},
        workspace=workspace, model_provider=provider,
    )
    harness = Harness(path.parent, workspace=workspace, agents=agents)
    # A separate directory per run avoids same-second recipe collisions.
    harness.session = Session(workspace=workspace, save_dir=session_dir or
                              ROOT / 'sessions' / f'{config["name"]}_{uuid.uuid4().hex[:12]}')
    harness.session.set_agent_config({'harness': config['name'],
                                     'agents': {slot: spec['identity'] for slot, spec in config['slots'].items()},
                                     'mode': config['pipeline']['mode']})
    return harness


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', type=int, default=1)
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--workspace', type=Path, default=Path(__file__).parent / 'workspace')
    parser.add_argument('--session', type=Path, help='Continue conversation history, not the execution cursor')
    parser.add_argument('--resume-checkpoint', help='Resume the execution cursor; revision/in-flight checks remain enabled')
    args = parser.parse_args()
    if args.list:
        for path in recipes():
            print(json.loads(path.read_text(encoding='utf-8'))['description'])
        return
    if args.session and args.resume_checkpoint:
        parser.error('Choose Session continuation OR execution checkpoint recovery, not both')
    load_local_env(ROOT)
    harness = create_recipe(args.stage, args.workspace)
    if args.session:
        metadata_path = args.session / 'session.json'
        if not metadata_path.is_file():
            parser.error('Session directory must contain session.json')
        metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
        if Path(metadata.get('workspace', '')).resolve() != args.workspace.resolve():
            parser.error('Resume with the original --workspace')
        if metadata.get('agent_config', {}).get('harness') != harness.name:
            parser.error('Resume with the original --stage')
        harness.session.load(args.session)
    print(harness.config['description'])
    print(f'Session: {harness.session.save_dir}\nWorkspace: {harness.workspace}')
    try:
        run_pipeline(harness, resume_from=args.resume_checkpoint)
    except KeyboardInterrupt:
        print('\nStopped; conversation saved. Use a completed checkpoint for cursor recovery.')
    finally:
        harness.session.save()


if __name__ == '__main__':
    main()
