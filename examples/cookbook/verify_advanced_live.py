"""Bounded real-provider checks; only the synthetic cookbook workspace is sent.

No dummy fallback. Full native child traces are saved alongside the report.
"""
from __future__ import annotations
import argparse
from contextlib import redirect_stdout
from datetime import datetime
import json
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from examples.cookbook.run import create_recipe
from llm.env_config import load_local_env
from pipeline_engine import PipelineRunner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stages', default=','.join(str(i) for i in range(11, 25)))
    args = parser.parse_args()
    load_local_env(ROOT)
    output = ROOT / '.runtime-logs' / ('cookbook-advanced-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    output.mkdir(parents=True)
    print(f'Evidence: {output}', flush=True)
    report = []
    for stage in map(int, args.stages.split(',')):
        workspace = output / f'stage-{stage}'
        shutil.copytree(Path(__file__).parent / 'workspace', workspace)
        h = create_recipe(stage, workspace, session_dir=workspace / '.egoagent/session')
        prompts = [h.config['cookbook']['try']]
        if stage == 17:
            prompts.append('3件，每件19.9元，九折。另一个方案：3件，每件18元，不打折。')
        if stage == 18:
            prompts.append('/recall 青松 验收命令')
        if stage == 23:
            prompts.insert(0, '/design 为智能花盆写三条卖点，先提取再润色，说明：自动浇水、缺水提醒。')
        events = []
        started = time.monotonic()
        row = {'stage': stage, 'harness': h.name, 'provider': 'live_global_configuration', 'prompts': prompts,
               'approvals': 'approved for this isolated synthetic workspace only', 'session': str(h.session.save_dir)}
        try:
            inputs = iter(prompts)
            with (workspace / 'console.log').open('w', encoding='utf-8') as log, redirect_stdout(log):
                c = PipelineRunner(h, get_input=lambda: next(inputs, None), get_approval=lambda *_: 'approved',
                                   deadline_monotonic=time.monotonic() + 240,
                                   on_output=lambda e, p: events.append((e, p))).run()
            errors = [p for e, p in events if e in ('error', 'node_error') or
                      (e == 'flow_variant' and not p.get('ok', False))]
            calls = [p for e, p in events if e == 'subagent_spawned']
            answers = [m.get('content', '') for m in h.session.messages if m.get('role') == 'assistant']
            last = answers[-1] if answers else ''
            ok = bool(last) and not errors
            if stage == 11:
                ok &= c.data.get('extract', {}).get('quantity') == 3
            elif stage == 12:
                ok &= bool(c.data.get('support', {}).get('plan')) and c.stats.tool_calls > 0
            elif stage == 13:
                ok &= len(calls) == 1 and '53.73' in last and c.stats.tool_calls > 0
            elif stage in (14, 15, 24):
                key = 'team' if stage == 14 else 'workers'
                results = c.data.get('support', {}).get(key, [])
                ok &= len(results) >= 2 and all(not r.get('error') for r in results) and '53.73' in last
            elif stage == 16:
                ok &= bool(c.data.get('feedback')) and c.data.get('revision', 99) <= 2
            elif stage == 17:
                ok &= bool(c.data.get('clarification')) and c.stats.tool_calls > 0
            elif stage == 18:
                ok &= 'unittest' in last and (workspace / '.egoagent/memory/cookbook.json').is_file()
            elif stage == 19:
                ok &= c.data.get('support', {}).get('activation', {}).get('ok', False) and '53.73' in last
            elif stage == 20:
                tool_names = {m.get('function', {}).get('name') for e, p in events
                              for m in (p.get('tool_calls') or []) if isinstance(m, dict)}
                row['tool_names'] = sorted(str(x) for x in tool_names)
                ok &= 'web_search' in tool_names and 'fetch_url' in tool_names and 'https://' in last
                ok &= 'https://docs.python.org/' in str(c.data.get('support', {}).get('child', ''))
                # Calling tools is insufficient if the final answer ignores the returned evidence.
                ok &= not any(s in last for s in ('无法读取 Python 官方文档', '本次请求**未验证**', '无法执行 `/web`'))
            elif stage == 21:
                ok &= '第二次调用未执行' in last and c.stats.model_calls == 1
            elif stage == 22:
                ok &= (workspace / '.egoagent/cookbook/generated-flow.json').is_file() and bool(c.data.get('design_result'))
            elif stage == 23:
                ok &= (workspace / '.egoagent/cookbook/evolved-flow.json').is_file() and bool(c.data.get('evolved_result'))
            row.update(ok=bool(ok), last_answer=last, errors=errors, child_count=len(calls), stats=c.stats.as_dict())
        except Exception as error:
            row.update(ok=False, error=f'{type(error).__name__}: {error}')
        finally:
            h.session.save()
        row['elapsed_seconds'] = round(time.monotonic() - started, 2)
        report.append(row)
        (workspace / 'events.json').write_text(json.dumps(events, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'{stage}: {"PASS" if row["ok"] else "FAIL"} ({row["elapsed_seconds"]}s)', flush=True)
    return 0 if all(row['ok'] for row in report) else 1


if __name__ == '__main__':
    raise SystemExit(main())
