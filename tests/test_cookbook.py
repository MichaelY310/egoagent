"""Deterministic integration tests of the real cookbook graphs, not model-quality claims."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import shutil

from examples.cookbook.run import ROOT, create_recipe, recipes
from capability_registry import CapabilityRegistry
from context_policy import conversation_turns, context_blocks
from capability_packs.cookbook_utilities.skills.quote.scripts.quote_total import quote_total
from llm.dummy_llm import DummyLLM
from pipeline_engine import PipelineRunner, PipelineInDoubt
from pipeline_schema import assert_valid_pipeline
from permissions import assess_tool_risk, classify_tool, PermissionClass, RiskLevel


class ScriptedProvider(DummyLLM):
    def __init__(self, script):
        super().__init__({'mode': 'scripted', 'script': script})
        self.requests = []

    def _log_to_session(self, direction, **data):
        if direction == 'input':
            self.requests.append(copy.deepcopy(data))


class CookbookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.events = []

    def tearDown(self):
        self.temp.cleanup()

    def make(self, stage, script=None):
        model = ScriptedProvider(script or [{'response': '你好！'}])
        harness = create_recipe(stage, self.root, provider=model, session_dir=self.root / '.egoagent' / f'session-{stage}')
        return harness, model

    def run_recipe(self, harness, messages=(), **kwargs):
        queue = iter(messages)
        return PipelineRunner(harness, get_input=lambda: next(queue, None),
                              on_output=lambda e, p: self.events.append((e, p)), **kwargs).run()

    def test_valid_progressive_graphs_with_live_default_models(self):
        known = {}
        for index, path in enumerate(recipes(), 1):
            config = json.loads(path.read_text(encoding='utf-8'))
            assert_valid_pipeline(config['pipeline'])
            self.assertEqual(config['cookbook']['step'], index)
            parent = config['cookbook'].get('based_on')
            if parent:
                self.assertIn(parent, known)
                self.assertTrue(known[parent] <= set(config['pipeline']['nodes']))
            known[config['name']] = set(config['pipeline']['nodes'])
            identity = json.loads((ROOT / 'identity' / config['slots']['agent']['identity'] / 'id.json').read_text(encoding='utf-8'))
            self.assertEqual(identity['llm']['type'], 'custom_llm')
            self.assertEqual(identity['llm']['base_url'], '')
            self.assertEqual(identity['llm']['model'], '')
        self.assertGreater(len(recipes()), 10)
        self.assertEqual(len(recipes()), config['cookbook']['total'])

    def test_every_recipe_answers_once_then_waits(self):
        for stage in range(1, 11):
            with self.subTest(stage=stage):
                harness, model = self.make(stage)
                context = self.run_recipe(harness, ['你好'])
                self.assertEqual(model._step_idx, 1)
                answers = [m for m in harness.session.messages if m.get('role') == 'assistant']
                self.assertEqual(len(answers), 1)
                self.assertEqual(answers[0]['content'], '你好！')
                self.assertEqual(context.stats.tool_calls, 0)

    def test_pre_recorded_chat_input_is_consumed(self):
        harness, model = self.make(1)
        for method in (harness.session.record, harness.session.record_full):
            method({'role': 'user', 'content': '你好'})
        self.run_recipe(harness)
        self.assertEqual(model._step_idx, 1)

    def test_custom_tool_runs_and_result_is_supplied_to_model(self):
        harness, model = self.make(2, [
            {'response': '', 'tool_calls': [{'id': 'quote-1', 'type': 'function', 'function': {
                'name': 'quote_total', 'arguments': '{"quantity":3,"unit_price":19.9,"discount_percent":10}'}}]},
            {'response': '53.73元'},
        ])
        result = self.run_recipe(harness, ['报价'])
        self.assertEqual(result.stats.tool_calls, 1)
        self.assertIn('53.73', json.dumps(model.requests[-1], ensure_ascii=False))

    def test_identity_changes_prompt_and_retains_custom_tool(self):
        harness, _ = self.make(3)
        prompt = harness.agents['agent'].build_system_prompt()
        self.assertIn('中文', prompt)
        self.assertIn('不编造', prompt)
        self.assertTrue(any('quote_total' in name for name in harness.agents['agent'].tools))

    def test_quote_rounding_and_invalid_inputs(self):
        self.assertEqual(quote_total(1, '0.005')['total'], '0.01')
        self.assertEqual(quote_total(2, 10, 100)['total'], '0.00')
        for args in [(True, 1), (0, 1), (1.5, 1), (1, float('nan')),
                     (1, float('inf')), (1, -1), (1, 10, 101), (1, 10, 'bad')]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                quote_total(*args)

    def test_custom_tool_declares_its_real_permission_class(self):
        metadata = json.loads((ROOT / 'capability_packs/cookbook_utilities/skills/quote/meta.json').read_text(encoding='utf-8'))
        self.assertEqual(classify_tool('quote_total', metadata), {PermissionClass.READ})
        self.assertEqual(assess_tool_risk('quote_total', metadata=metadata).level, RiskLevel.LOW)

    def test_approval_reject_and_accept(self):
        for stage in (4, 10):
            for decision in ('rejected', 'approved'):
                with self.subTest(stage=stage, decision=decision):
                    target = self.root / '.egoagent/cookbook/answer.txt'
                    target.unlink(missing_ok=True)
                    harness, model = self.make(stage)
                    harness.session.state['cookbook_last_answer'] = 'a known answer'
                    self.run_recipe(harness, ['/save'], get_approval=lambda *_: decision)
                    self.assertEqual(target.exists(), decision == 'approved')
                    if target.exists():
                        self.assertEqual(target.read_text(encoding='utf-8'), 'a known answer')
                    self.assertEqual(model._step_idx, 0)

    def test_save_without_previous_answer_explains_instead_of_writing(self):
        harness, model = self.make(4)
        self.run_recipe(harness, ['/save'])
        self.assertFalse((self.root / '.egoagent/cookbook/answer.txt').exists())
        self.assertIn('还没有', harness.session.messages[-1]['content'])
        self.assertEqual(model._step_idx, 0)

    def test_isolated_subflow_returns_review_without_parent_history(self):
        harness, model = self.make(5, [{'response': '{"approach":"边界测试","checks":["零价格"],"uncertainty":"未运行"}'}, {'response': '建议测试零价格。'}])
        harness.session.record({'role': 'user', 'content': 'PARENT_ONLY_PRIVATE_MARKER'})
        harness.session.record({'role': 'assistant', 'content': '已收到'})
        result = self.run_recipe(harness, ['/review 报价边界'])
        self.assertNotIn('PARENT_ONLY_PRIVATE_MARKER', json.dumps(model.requests[0], ensure_ascii=False))
        self.assertIn('边界测试', json.dumps(result.data['support'], ensure_ascii=False))
        self.assertTrue(any(e == 'subagent_spawned' for e, _ in self.events))

    def test_session_save_reload_keeps_history_and_state(self):
        harness, _ = self.make(9)
        self.run_recipe(harness, ['项目青松'])
        harness.session.save()
        resumed, model = self.make(9)
        resumed.session.load(harness.session.save_dir)
        self.assertEqual(resumed.session.state['cookbook_last_answer'], '你好！')
        self.run_recipe(resumed, ['项目叫什么？'])
        self.assertIn('项目青松', json.dumps(model.requests[-1], ensure_ascii=False))

    def seed_history(self, harness, turns):
        for question, answer in turns:
            for role, text in [('user', question), ('assistant', answer)]:
                message = {'role': role, 'content': text}
                harness.session.record(message)
                harness.session.record_full(message.copy())

    def test_real_catalog_search_activation_and_knowledge_call(self):
        # A real SQLite catalog, isolated from the user's usage counters.
        shutil.copytree(ROOT / 'identity/cookbook_library', self.root / 'identity/cookbook_library')
        registry = CapabilityRegistry(self.root, workspace=self.root, embedding_backend=None)
        harness, model = self.make(6, [
            {'response': '', 'tool_calls': [{'id': 'policy-1', 'type': 'function', 'function': {
                'name': 'cookbook_shipping_policy', 'arguments': '{}'}}]},
            {'response': '150+12=162元'},
        ])
        with patch('capability_registry.CapabilityRegistry', return_value=registry):
            context = self.run_recipe(harness, ['/discover cookbook_shipping_policy'])
        self.assertTrue(context.data['support']['activation']['ok'])
        self.assertIn('200.00', json.dumps(model.requests[-1], ensure_ascii=False))
        self.assertTrue(any(e == 'capability_search' for e, _ in self.events))
        self.assertTrue(any(e == 'capability_activated' for e, _ in self.events))

    def test_no_search_results_skips_activation(self):
        registry = CapabilityRegistry(self.root, embedding_backend=None)
        harness, _ = self.make(6, [{'response': '没有找到相关知识。'}])
        with patch('capability_registry.CapabilityRegistry', return_value=registry):
            context = self.run_recipe(harness, ['/discover nonexistent_cookbook_knowledge'])
        self.assertNotIn('activation', context.data['support'])

    def test_curator_elides_old_turn_but_preserves_audit(self):
        harness, model = self.make(7)
        self.seed_history(harness, [('WEATHER_NOISE ' * 100, 'sunny')] +
                          [(f'Keep project requirement {i}', 'noted') for i in range(6)])
        turn = conversation_turns(harness.session.messages)[0]
        model._script = [
            {'response': json.dumps({'decisions': [{'turn_id': turn.id, 'action': 'elide', 'reason': 'unrelated smalltalk'}]})},
            {'response': '保留项目要求。'},
        ]
        result = self.run_recipe(harness, ['回到项目'])
        self.assertTrue(result.data['curation_applied'])
        self.assertGreater(result.data['curation_stats']['saved_tokens_estimated'], 0)
        self.assertNotIn('WEATHER_NOISE', json.dumps(harness.session.messages))
        self.assertIn('WEATHER_NOISE', json.dumps(harness.session.full_messages))
        self.assertNotIn('WEATHER_NOISE', json.dumps(model.requests[-1]))

    def test_compactor_is_pressure_gated_and_preserves_facts_and_audit(self):
        harness, model = self.make(8)
        self.seed_history(harness, [
            ('Project code QINGSONG; test command python -m unittest. ' * 350, 'LOG_NOISE ' * 1800),
            ('recent request 1', 'noted'), ('recent request 2', 'noted'),
        ])
        blocks = context_blocks(harness.session.messages, protect_recent_turns=2)
        plan = {'blocks': [{'block_id': block.id, 'action': 'summarize',
                           'reason': 'redundant log', 'summary': 'Project QINGSONG; verify with python -m unittest.'}
                          for block in blocks if not block.protected],
                'continuation_summary': 'Project QINGSONG; verify with python -m unittest.'}
        model._script = [{'response': json.dumps(plan)}, {'response': 'Project QINGSONG.'}]
        result = self.run_recipe(harness, ['项目代号？'])
        self.assertTrue(result.data['compacted'])
        self.assertGreater(result.data['compaction_stats']['saved_tokens_estimated'], 128)
        self.assertIn('LOG_NOISE', json.dumps(harness.session.full_messages))
        # Exact-anchor preservation may keep the identifier once, not the log.
        self.assertLess(json.dumps(model.requests[-1]).count('LOG_NOISE'), 3)
        self.assertIn('QINGSONG', json.dumps(model.requests[-1]))
        self.assertIn('python -m unittest', json.dumps(model.requests[-1]))

    def test_invalid_curator_plan_keeps_original_context(self):
        harness, model = self.make(7)
        self.seed_history(harness, [('important fact', 'noted')] * 7)
        original = copy.deepcopy(harness.session.messages)
        model._script = [{'response': 'not json'}, {'response': '原事实仍在。'}]
        result = self.run_recipe(harness, ['继续'])
        self.assertFalse(result.data['curation_applied'])
        self.assertEqual(harness.session.messages[:len(original)], original)

    def test_durable_completed_save_does_not_rewrite_on_recovery(self):
        harness, _ = self.make(10)
        harness.session.state['cookbook_last_answer'] = 'write once'
        def crash(_ctx, node, _spec):
            if node == 'save_answer':
                raise RuntimeError('simulated process failure')
        with self.assertRaisesRegex(RuntimeError, 'simulated'):
            self.run_recipe(harness, ['/save'], get_approval=lambda *_: 'approved', after_node=crash)
        checkpoint = [p['path'] for e, p in self.events if e == 'checkpoint' and p.get('phase') == 'completed'][-1]
        target = self.root / '.egoagent/cookbook/answer.txt'
        before = target.stat().st_mtime_ns
        resumed, model = self.make(10)
        self.events.clear()
        self.run_recipe(resumed, resume_from=checkpoint)
        self.assertEqual(target.stat().st_mtime_ns, before)
        self.assertEqual(target.read_text(encoding='utf-8'), 'write once')
        self.assertEqual(model._step_idx, 0)
        self.assertFalse(any(e == 'node_enter' and p.get('node') == 'save_answer' for e, p in self.events))

    def test_durable_inflight_write_is_not_blindly_replayed(self):
        harness, _ = self.make(10)
        harness.session.state['cookbook_last_answer'] = 'needs inspection'

        class CrashAtWrite(PipelineRunner):
            def _execute_with_policy(self, node_id, node, op):
                if node_id == 'save_answer':
                    raise RuntimeError('worker lost during write')
                return super()._execute_with_policy(node_id, node, op)

        prompts = iter(['/save'])
        with self.assertRaisesRegex(RuntimeError, 'worker lost'):
            CrashAtWrite(harness, get_input=lambda: next(prompts, None),
                         get_approval=lambda *_: 'approved',
                         on_output=lambda e, p: self.events.append((e, p))).run()
        checkpoint = [p['path'] for e, p in self.events
                      if e == 'checkpoint' and p.get('phase') == 'in_flight'][-1]
        resumed, _ = self.make(10)
        with self.assertRaises(PipelineInDoubt):
            self.run_recipe(resumed, resume_from=checkpoint)
        self.assertFalse((self.root / '.egoagent/cookbook/answer.txt').exists())


if __name__ == '__main__':
    unittest.main()
