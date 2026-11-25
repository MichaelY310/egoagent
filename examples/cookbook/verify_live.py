"""Opt-in, bounded live-model smoke check. Sends only synthetic cookbook tasks.

python examples/cookbook/verify_live.py --stages 1,2,3,4,5,6,7,8,9,10
Results include the full native trajectories; scripted unit tests live separately.
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


def seed(harness, turns):
    for question, answer in turns:
        for role, text in [('user', question), ('assistant', answer)]:
            message = {'role': role, 'content': text}
            harness.session.record(message)
            harness.session.record_full(message.copy())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stages', default='1,2,3,4,5,6,7,8,9,10')
    parser.add_argument('--walkthrough', action='store_true',
                        help='For stages 7/8, send the exact UI example sequence instead of seeding history')
    args = parser.parse_args()
    load_local_env(ROOT)
    output = ROOT / '.runtime-logs' / ('cookbook-live-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    output.mkdir(parents=True)
    report = []
    print(f'Evidence: {output}', flush=True)
    for stage in [int(value) for value in args.stages.split(',')]:
        workspace = output / f'stage-{stage}'
        shutil.copytree(Path(__file__).parent / 'workspace', workspace)
        harness = create_recipe(stage, workspace, session_dir=workspace / '.egoagent/session')
        events = []
        prompt = {1: '你好', 2: '用 quote_total 计算3件每件19.9元打九折的金额。',
                  3: '用 quote_total 计算3件每件19.9元打九折的金额。',
                  4: '用 quote_total 计算3件每件19.9元打九折的金额。',
                  5: '/review 为报价函数设计三个有用的测试，只给简短建议。',
                  6: '/discover cookbook_shipping_policy：折后商品150元，总付款多少？请读取政策。',
                  7: '之前的项目代号和必须使用的验证命令是什么？',
                  8: '之前的项目代号和必须使用的验证命令是什么？',
                  9: '记住：项目代号青松；验收日期11月3日。只回复已记住。',
                  10: '用 quote_total 算3件每件19.9元打九折的金额。'}[stage]
        if stage == 7 and not args.walkthrough:
            seed(harness, [('无关闲聊：天气随便聊。' * 70, '天气闲聊。' * 70)] * 4 +
                 [('项目代号青松；验证命令 python -m unittest。', '记住了。')] * 3)
        if stage == 8 and not args.walkthrough:
            seed(harness, [('项目代号青松；验证命令 python -m unittest。',
                            '已完成的重复测试日志：全部通过。\n' * 1800),
                           ('继续', '收到'), ('保留项目要求', '收到')])
        prompts = iter([prompt, '/save'] if stage in (4, 10) else [prompt])
        if args.walkthrough and stage in (7, 8):
            prompts = iter(example['text'] + ('\n' + example['repeat_text'] * example.get('repeat', 0)
                                           if example.get('repeat_text') else '')
                           for example in harness.config['cookbook']['examples'])
        started = time.monotonic()
        result = {'stage': stage, 'harness': harness.name, 'provider': 'live_global_configuration',
                  'seeded_context_fixture': stage in (7, 8) and not args.walkthrough,
                  'ui_walkthrough': stage in (7, 8) and args.walkthrough,
                  'session': str(harness.session.save_dir)}
        try:
            with (workspace / 'console.log').open('w', encoding='utf-8') as log, redirect_stdout(log):
                runner = PipelineRunner(harness, get_input=lambda: next(prompts, None),
                                        get_approval=lambda *_: 'approved',
                                        deadline_monotonic=time.monotonic() + 180,
                                        on_output=lambda e, p: events.append((e, p)))
                context = runner.run()
                if stage == 9:
                    harness.session.save()
                    saved = harness.session.save_dir
                    harness = create_recipe(stage, workspace, session_dir=saved)
                    harness.session.load(saved)
                    followup = iter(['项目代号与验收日期是什么？'])
                    context = PipelineRunner(harness, get_input=lambda: next(followup, None),
                                             deadline_monotonic=time.monotonic() + 90).run()
            answers = [m.get('content', '') for m in harness.session.messages if m.get('role') == 'assistant']
            result.update(ok=bool(answers), last_answer=answers[-1] if answers else '', stats=context.stats.as_dict(),
                          curation_stats=context.data.get('curation_stats'), compaction_stats=context.data.get('compaction_stats'),
                          activated=context.data.get('support', {}).get('activation'),
                          saved=(workspace / '.egoagent/cookbook/answer.txt').exists())
            if stage == 1:
                result['ok'] &= len(answers) == 1 and context.stats.tool_calls == 0
            if stage in (2, 3, 4, 10):
                result['ok'] &= context.stats.tool_calls > 0 and '53.73' in json.dumps(harness.session.messages)
            if stage in (4, 10):
                result['ok'] &= result['saved']
            if stage == 5:
                result['ok'] &= 'review' in context.data.get('support', {})
            if stage == 6:
                result['ok'] &= bool(result['activated'] and result['activated'].get('ok')) and context.stats.tool_calls > 0
            if stage in (7, 8):
                component = 'component_context_curator' if stage == 7 else 'component_context_compactor'
                applications = [payload for event, payload in events
                                if event == 'conversation_applied' and payload.get('subflow') == component]
                result['context_applications'] = applications
                metric = max(applications, key=lambda value: value.get('saved_tokens_estimated', 0), default={})
                result['ok'] &= metric.get('saved_tokens_estimated', 0) > 0 and '青松' in result['last_answer'] and 'unittest' in result['last_answer']
            if stage == 9:
                result['ok'] &= '青松' in result['last_answer'] and '11' in result['last_answer']
        except Exception as error:
            result.update(ok=False, error=f'{type(error).__name__}: {error}')
        finally:
            harness.session.save()
        result['elapsed_seconds'] = round(time.monotonic() - started, 2)
        report.append(result)
        (workspace / 'events.json').write_text(json.dumps(events, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'Stage {stage}: {"PASS" if result["ok"] else "FAIL"} ({result["elapsed_seconds"]}s)', flush=True)
    return 0 if all(item['ok'] for item in report) else 1


if __name__ == '__main__':
    raise SystemExit(main())
