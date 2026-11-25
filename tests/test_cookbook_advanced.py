"""Mechanism tests for cookbook recipes. Scripted responses are NOT live-model evidence."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch

from examples.cookbook.run import ROOT, create_recipe
from examples.cookbook.build_recipes import all_configs
from pipeline_engine import PipelineRunner
from pipeline_schema import validate_json_schema
from capability_registry import CapabilityRegistry
from tests.test_cookbook import ScriptedProvider


def response(value):
    return {'response': json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value}


def tiny_flow():
    return {'name': 'cookbook_generated_test', 'prompts': {'answer': {'default': '给一句卖点。'}},
            'pipeline': {'start': 'model', 'max_steps': 8, 'workspace_preview': False,
                         'budget': {'max_model_calls': 3}, 'nodes': {
                             'model': {'op': '模型', 'agent': 'agent', 'prompt': 'answer', 'output_var': 'answer',
                                       'edges': [{'condition': 'has_text', 'to': 'end'}]},
                             'end': {'op': '结束', 'value': '$ctx.answer', 'edges': []}}}}


class CookbookAdvancedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        shutil.copytree(ROOT / 'examples/cookbook/workspace', self.root, dirs_exist_ok=True)
        self.events = []

    def tearDown(self):
        self.temp.cleanup()

    def make(self, stage, script):
        model = ScriptedProvider(script)
        harness = create_recipe(stage, self.root, provider=model, session_dir=self.root / f'session-{stage}')
        return harness, model

    def run_recipe(self, harness, messages, **kwargs):
        queue = iter(messages)
        return PipelineRunner(harness, get_input=lambda: next(queue, None),
                              on_output=lambda e, p: self.events.append((e, p)), **kwargs).run()

    def test_published_recipes_match_authoring_source(self):
        for relative, expected in all_configs().items():
            self.assertEqual(json.loads((ROOT / relative).read_text(encoding='utf-8')), expected, relative)

    def test_json_invalid_then_retry_and_typed_output(self):
        h, m = self.make(11, [response('not-json'), response({'quantity': 3, 'unit_price': 19.9, 'discount_percent': 10})])
        c = self.run_recipe(h, ['/extract 报价'])
        self.assertEqual(c.data['extract']['quantity'], 3)
        self.assertEqual(c.stats.retries, 1)
        self.assertTrue(any(e == 'node_retry' for e, _ in self.events))

    def test_invalid_schema_fails_visibly_not_silently(self):
        h, _ = self.make(11, [response({'quantity': -1})] * 2)
        self.run_recipe(h, ['/extract 报价'])
        self.assertIn('未通过校验', h.session.messages[-1]['content'])

    def test_plan_is_supplied_to_executor(self):
        h, m = self.make(12, [response({'goal': 'inspect', 'steps': ['READ_EVIDENCE'], 'verify': 'no writes'}), response('done')])
        self.run_recipe(h, ['/plan inspect'])
        self.assertIn('READ_EVIDENCE', json.dumps(m.requests[-1]))

    def test_delegation_is_real_and_context_isolated(self):
        h, m = self.make(13, [response({'role': 'calculator', 'task': 'ONLY_CHILD_REQUEST', 'reason': 'quote'}),
                              response('CHILD_RESULT'), response('PARENT_RESULT')])
        h.session.record({'role': 'user', 'content': 'PARENT_PRIVATE_CONTEXT'})
        h.session.record({'role': 'assistant', 'content': 'ok'})
        c = self.run_recipe(h, ['quote please'])
        self.assertNotIn('PARENT_PRIVATE_CONTEXT', json.dumps(m.requests[1]))
        self.assertIn('ONLY_CHILD_REQUEST', json.dumps(m.requests[1]))
        self.assertIn('CHILD_RESULT', json.dumps(m.requests[-1]))
        self.assertEqual(c.data['support']['child'], 'CHILD_RESULT')
        tools = [t['function']['name'] for t in m.requests[1]['tools']]
        self.assertEqual(tools, ['quote_total'])
        self.assertTrue(any(e == 'subagent_spawned' for e, _ in self.events))

    def test_self_route_has_no_subagent_and_clears_old_support(self):
        h, m = self.make(13, [response({'role': 'self', 'task': '你好', 'reason': '问候'}), response('你好！')])
        c = self.run_recipe(h, ['你好'], initial_data={'support': {'child': 'STALE_RESULT'}})
        self.assertFalse(any(e == 'subagent_spawned' for e, _ in self.events))
        self.assertEqual(c.data['support'], {})
        self.assertNotIn('STALE_RESULT', json.dumps(m.requests[-1]))

    def test_dispatch_rejects_arbitrary_identity(self):
        h, _ = self.make(13, [response({'role': '../../dante', 'task': 'x', 'reason': 'x'})] * 2)
        self.run_recipe(h, ['do something'])
        self.assertFalse(any(e == 'subagent_spawned' for e, _ in self.events))
        self.assertIn('校验', h.session.messages[-1]['content'])

    def test_parallel_progress_is_live_and_parent_gets_only_reports(self):
        h, _ = self.make(14, [response('parent summary')])
        barrier = threading.Barrier(2)
        live = threading.Event()
        class BlockingProvider(ScriptedProvider):
            def _get_scripted_response(self):
                barrier.wait(timeout=10)  # would fail if branches were serialized
                if not live.wait(timeout=10):
                    raise AssertionError('Child progress was buffered until join')
                return super()._get_scripted_response()
        for slot in ('files', 'calculator'):
            h.agents[slot].llm = BlockingProvider([response(slot + '_FINAL')])
        def progress(event, payload):
            self.events.append((event, payload))
            if payload.get('branch') and event == 'node_enter':
                live.set()
        queue = iter(['/team 两份任务'])
        c = PipelineRunner(h, get_input=lambda: next(queue, None), on_output=progress).run()
        reports = c.data['support']['team']
        self.assertEqual([r['value'] for r in reports], ['files_FINAL', 'calculator_FINAL'])
        self.assertTrue(all(set(r) == {'name', 'value', 'error'} for r in reports))
        self.assertEqual(len([1 for e, _ in self.events if e == 'subagent_spawned']), 2)

    def test_dynamic_map_cardinality_and_role_bindings(self):
        h, m = self.make(15, [response({'tasks': [{'role': 'files', 'task': 'A'}, {'role': 'calculator', 'task': 'B'}]}),
                              response('worker'), response('worker'), response('summary')])
        c = self.run_recipe(h, ['/team-auto A B'])
        self.assertEqual(len(c.data['support']['workers']), 2)
        self.assertEqual(c.stats.model_calls, 4)
        self.assertEqual(len([1 for e, _ in self.events if e == 'subagent_spawned']), 2)

    def test_parallel_failed_child_is_a_failure_report_not_a_success(self):
        h, _ = self.make(14, [response('parent summary')])
        class FailingProvider(ScriptedProvider):
            def _get_scripted_response(self):
                raise ValueError('worker failed deliberately')
        h.agents['files'].llm = FailingProvider([])
        h.agents['calculator'].llm = ScriptedProvider([response('calculated')])
        c = self.run_recipe(h, ['/team 两项任务'])
        failed, success = c.data['support']['team']
        self.assertIsNone(failed['value'])
        self.assertIn('worker failed', failed['error']['message'])
        self.assertEqual(success['value'], 'calculated')

    def test_skill_search_activates_and_runs_a_real_tool(self):
        shutil.copytree(ROOT / 'capability_packs/cookbook_utilities', self.root / 'capability_packs/cookbook_utilities')
        registry = CapabilityRegistry(self.root, workspace=self.root, embedding_backend=None)
        h, m = self.make(19, [response({'query': 'quote_total'}),
            {'response': '', 'tool_calls': [{'id': 'q', 'type': 'function', 'function': {
                'name': 'quote_total', 'arguments': '{"quantity":3,"unit_price":19.9,"discount_percent":10}'}}]},
            response('53.73')])
        with patch('capability_registry.CapabilityRegistry', return_value=registry):
            c = self.run_recipe(h, ['/skill quote_total 计算金额'])
        self.assertTrue(c.data['support']['activation']['ok'])
        self.assertEqual(c.stats.tool_calls, 1)
        self.assertIn('53.73', json.dumps(m.requests[-1]))

    def test_web_subagent_exposes_only_search_and_fetch(self):
        h, m = self.make(20, [response('child result'), response('parent result')])
        self.run_recipe(h, ['/web Python official docs'])
        names = {t['function']['name'] for t in m.requests[0]['tools']}
        self.assertEqual(names, {'web_search', 'fetch_url'})
        self.assertIn('child result', json.dumps(m.requests[-1]))

    def test_too_many_workers_rejected_before_spawning(self):
        h, _ = self.make(15, [response({'tasks': [{'role': 'files', 'task': 'A'}] * 4})] * 2)
        self.run_recipe(h, ['/team-auto many'])
        self.assertFalse(any(e == 'subagent_spawned' for e, _ in self.events))

    def test_evaluator_revises_and_stops_at_bound(self):
        for passed in (False, True):
            with self.subTest(passed=passed):
                script = [response('draft'), response({'passed': False, 'feedback': 'fix'})]
                script += [response('revised'), response({'passed': passed, 'feedback': 'review'})] * 2
                h, _ = self.make(16, script)
                c = self.run_recipe(h, ['/improve text'])
                self.assertEqual(c.data['revision'], 1 if passed else 2)
                self.assertEqual(c.data['feedback']['passed'], passed)

    def test_clarification_consumes_a_new_user_message(self):
        h, m = self.make(17, [response('数量是多少？'), response('done')])
        c = self.run_recipe(h, ['/clarify 报价', '3件'])
        self.assertEqual(c.data['support']['clarification']['original_request'], '/clarify 报价')
        self.assertEqual(c.data['clarification'], '3件')
        self.assertIn('3件', json.dumps(m.requests[-1], ensure_ascii=False))

    def test_memory_survives_new_session_only_after_approval(self):
        h, _ = self.make(18, [])
        self.run_recipe(h, ['/remember 青松 unittest'], get_approval=lambda *_: 'rejected')
        self.assertFalse((self.root / '.egoagent/memory/cookbook.json').exists())
        self.run_recipe(h, ['/remember 青松 unittest'], get_approval=lambda *_: 'approved')
        other, m = self.make(18, [response('unittest')])
        c = self.run_recipe(other, ['/recall 青松 unittest'])
        self.assertTrue(c.data['support']['memory'])
        self.assertIn('unittest', json.dumps(m.requests[-1]))

    def test_budget_finalizer_is_visible_and_second_call_does_not_run(self):
        h, m = self.make(21, [response('tip')])
        c = self.run_recipe(h, ['/budget test'])
        self.assertEqual(m._step_idx, 1)
        self.assertIn('第二次调用未执行', h.session.messages[-1]['content'])

    def test_generate_real_flow_and_save_after_approved_execution(self):
        h, m = self.make(22, [response(tiny_flow()), response('新工作流结果')])
        c = self.run_recipe(h, ['/design 一个工作流'], get_approval=lambda *_: 'approved')
        path = self.root / '.egoagent/cookbook/generated-flow.json'
        self.assertTrue(path.is_file())
        self.assertEqual(c.data['design_result'], '新工作流结果')
        self.assertIn('model', json.loads(path.read_text(encoding='utf-8'))['pipeline']['nodes'])

    def test_generate_rejected_executes_nothing_and_saves_nothing(self):
        h, m = self.make(22, [response(tiny_flow())])
        self.run_recipe(h, ['/design x'], get_approval=lambda *_: 'rejected')
        self.assertEqual(m._step_idx, 1)
        self.assertFalse((self.root / '.egoagent/cookbook/generated-flow.json').exists())

    def test_generated_nested_flow_or_tools_cannot_escape_allowlist(self):
        for op in ('子流程', 'Agent', 'Python', '工作区', '记忆'):
            with self.subTest(op=op):
                candidate = tiny_flow()
                candidate['pipeline']['nodes']['model']['op'] = op
                h, m = self.make(22, [response(candidate), response(candidate)])
                self.run_recipe(h, ['/design x'], get_approval=lambda *_: 'approved')
                self.assertEqual(m._step_idx, 2)
                self.assertFalse((self.root / '.egoagent/cookbook/generated-flow.json').exists())
                self.assertIn('失败', h.session.messages[-1]['content'])

    def test_flow_edit_preserves_original_and_runs_candidate(self):
        candidate = tiny_flow()
        path = self.root / '.egoagent/cookbook/generated-flow.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(candidate), encoding='utf-8')
        proposal = {'hypothesis': 'shorten', 'operations': [{'op': 'set_field', 'path': 'prompts.answer.default', 'value': '只说一个短句。'}]}
        h, m = self.make(23, [response(proposal), response('短句')])
        c = self.run_recipe(h, ['/evolve 更简短'], get_approval=lambda *_: 'approved')
        self.assertEqual(c.data['evolved_result'], '短句')
        self.assertEqual(json.loads(path.read_text(encoding='utf-8')), candidate)
        evolved = json.loads(path.with_name('evolved-flow.json').read_text(encoding='utf-8'))
        self.assertEqual(evolved['prompts']['answer']['default'], '只说一个短句。')

    def test_recipe_24_preserves_dynamic_team_and_adds_context_components(self):
        h, m = self.make(24, [response({'tasks': [{'role': 'calculator', 'task': 'quote'}]}), response('worker'), response('summary')])
        c = self.run_recipe(h, ['/team-auto quote'])
        self.assertEqual(len(c.data['support']['workers']), 1)
        self.assertIn('compaction_stats', c.data)
        self.assertIn('curation_stats', c.data)
        self.assertTrue(h.config['pipeline']['auto_checkpoint'])

    def test_flow_edit_accepts_normalized_string_prompt_representation(self):
        candidate = tiny_flow()
        candidate['prompts']['answer'] = '给一句卖点。'
        path = self.root / '.egoagent/cookbook/generated-flow.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(candidate), encoding='utf-8')
        proposal = {'hypothesis': 'shorten', 'operations': [
            {'op': 'set_field', 'path': 'prompts.answer', 'value': '只说一个短句。'}]}
        h, m = self.make(23, [response(proposal), response('短句')])
        c = self.run_recipe(h, ['/evolve 更简短'], get_approval=lambda *_: 'approved')
        self.assertEqual(c.data['evolved_result'], '短句')
        self.assertEqual(json.loads(path.read_text(encoding='utf-8')), candidate)
        self.assertIn('值是字符串', json.dumps(m.requests[0], ensure_ascii=False))

    def test_dictionary_schema_validates_generated_node_operations(self):
        h, _ = self.make(22, [])
        schema = h.config['pipeline']['nodes']['design']['output_schema']
        self.assertEqual(validate_json_schema(tiny_flow(), schema), [])
        candidate = tiny_flow()
        candidate['pipeline']['nodes']['model']['op'] = 'agent'
        errors = validate_json_schema(candidate, schema)
        self.assertTrue(any('nodes.model.op' in error for error in errors))


if __name__ == '__main__':
    unittest.main()
