#!/usr/bin/env bash
# test_meta_evolution.sh — Verify meta-evolution module imports and basic logic.
set -e

cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"

echo "============================================="
echo "  Meta-Evolution Test Suite"
echo "  Project root: $PROJECT_ROOT"
echo "============================================="
echo ""

# Test 1: Import succeeds
echo "[Test 1] Import meta_evolution module..."
python3 -c "
import sys
sys.path.insert(0, '$PROJECT_ROOT')
from self_evolution.meta_evolution import MetaEvolutionEngine, DEFAULT_STRATEGY, PARAM_BOUNDS, MAX_PARAMS_PER_STEP
print('  OK: Module imported successfully')
print(f'  DEFAULT_STRATEGY keys: {list(DEFAULT_STRATEGY.keys())}')
print(f'  MAX_PARAMS_PER_STEP: {MAX_PARAMS_PER_STEP}')
"
echo ""

# Test 2: Engine instantiation and get_current_strategy
echo "[Test 2] Engine instantiation and get_current_strategy..."
python3 -c "
import sys
sys.path.insert(0, '$PROJECT_ROOT')
from self_evolution.meta_evolution import MetaEvolutionEngine

engine = MetaEvolutionEngine()
strategy = engine.get_current_strategy()
assert 'gradient_temperature' in strategy
assert 'frontier_range' in strategy
assert 'gate_threshold' in strategy
assert 'distill_strategy' in strategy
assert 'max_eval_tasks' in strategy
assert 'loop_iterations' in strategy
assert 'judge_prompt' in strategy
print('  OK: All strategy keys present')
print(f'  gradient_temperature={strategy[\"gradient_temperature\"]}')
print(f'  gate_threshold={strategy[\"gate_threshold\"]}')
"
echo ""

# Test 3: Safety bounds enforcement
echo "[Test 3] apply_meta_gradient with safety bounds..."
python3 -c "
import sys
sys.path.insert(0, '$PROJECT_ROOT')
from self_evolution.meta_evolution import MetaEvolutionEngine

engine = MetaEvolutionEngine()
gradient = {'gradient_temperature': 99.0, 'gate_threshold': -5.0}
result = engine.apply_meta_gradient(gradient)
assert result['gradient_temperature'] == 1.5, f'Got {result[\"gradient_temperature\"]}'
assert result['gate_threshold'] == 1.0, f'Got {result[\"gate_threshold\"]}'
print('  OK: Bounds enforced correctly')

gradient2 = {'frontier_range': [0.0, 1.0]}
result2 = engine.apply_meta_gradient(gradient2)
assert result2['frontier_range'][0] >= 0.05
assert result2['frontier_range'][1] <= 0.95
print(f'  frontier_range clamped to {result2[\"frontier_range\"]}')

gradient3 = {'distill_strategy': 'invalid_value'}
result3 = engine.apply_meta_gradient(gradient3)
assert result3['distill_strategy'] != 'invalid_value'
print('  OK: Invalid categorical rejected')
"
echo ""

# Test 4: reset_to_default
echo "[Test 4] reset_to_default..."
python3 -c "
import sys
sys.path.insert(0, '$PROJECT_ROOT')
from self_evolution.meta_evolution import MetaEvolutionEngine, DEFAULT_STRATEGY

engine = MetaEvolutionEngine()
engine.apply_meta_gradient({'gradient_temperature': 1.2})
assert engine.get_current_strategy()['gradient_temperature'] == 1.2
engine.reset_to_default()
assert engine.get_current_strategy()['gradient_temperature'] == DEFAULT_STRATEGY['gradient_temperature']
print('  OK: reset_to_default works')
"
echo ""

# Test 5: analyze_evolution_history
echo "[Test 5] analyze_evolution_history..."
python3 -c "
import sys
sys.path.insert(0, '$PROJECT_ROOT')
from self_evolution.meta_evolution import MetaEvolutionEngine

engine = MetaEvolutionEngine()
analysis = engine.analyze_evolution_history()
assert 'total_attempts' in analysis
assert 'accept_rate' in analysis
assert 'avg_improvement' in analysis
assert 'score_trend' in analysis
assert 'failure_patterns' in analysis
print(f'  OK: {analysis[\"total_attempts\"]} attempts, accept_rate={analysis[\"accept_rate\"]:.2%}')
"
echo ""

# Test 6: meta_gate_decision logic
echo "[Test 6] meta_gate_decision..."
python3 -c "
import sys
sys.path.insert(0, '$PROJECT_ROOT')
from self_evolution.meta_evolution import MetaEvolutionEngine

engine = MetaEvolutionEngine()

d1 = engine.meta_gate_decision({}, {},
    {'final_score': 0.5, 'total_accepted': 2, 'total_rejected': 1, 'total_rollbacks': 0},
    {'final_score': 0.6, 'total_accepted': 3, 'total_rejected': 0, 'total_rollbacks': 0})
assert d1 == 'accept', f'Expected accept, got {d1}'

d2 = engine.meta_gate_decision({}, {},
    {'final_score': 0.7, 'total_accepted': 3, 'total_rejected': 0, 'total_rollbacks': 0},
    {'final_score': 0.5, 'total_accepted': 1, 'total_rejected': 2, 'total_rollbacks': 0})
assert d2 == 'rollback', f'Expected rollback, got {d2}'

d3 = engine.meta_gate_decision({}, {},
    {'final_score': 0.5, 'total_accepted': 2, 'total_rejected': 1, 'total_rollbacks': 0},
    {'final_score': 0.49, 'total_accepted': 2, 'total_rejected': 1, 'total_rollbacks': 0})
assert d3 == 'reject', f'Expected reject, got {d3}'

print('  OK: gate decisions correct (accept/rollback/reject)')
"
echo ""

# Test 7: get_meta_archive
echo "[Test 7] get_meta_archive..."
python3 -c "
import sys
sys.path.insert(0, '$PROJECT_ROOT')
from self_evolution.meta_evolution import MetaEvolutionEngine

engine = MetaEvolutionEngine()
archive = engine.get_meta_archive()
assert isinstance(archive, list)
print(f'  OK: Meta archive has {len(archive)} entries')
"
echo ""

# Test 8: DAG config validation
echo "[Test 8] Validate meta_evolution_cycle/config.json..."
python3 -c "
import sys, json
from pathlib import Path

PROJECT_ROOT = '$PROJECT_ROOT'
config_path = Path(PROJECT_ROOT) / 'harness' / 'meta_evolution_cycle' / 'config.json'
assert config_path.exists(), f'Config not found'

config = json.loads(config_path.read_text())
assert config['name'] == 'meta_evolution_cycle'
assert 'pipeline' in config
nodes = config['pipeline']['nodes']
assert 'init' in nodes
assert 'meta_gate' in nodes
assert 'final_report' in nodes

for node_id, node in nodes.items():
    for edge in node.get('edges', []):
        target = edge.get('to')
        if target is not None:
            assert target in nodes, f'{node_id} -> {target} invalid'

print(f'  OK: DAG valid with {len(nodes)} nodes')
"
echo ""

echo "============================================="
echo "  All tests passed!"
echo "============================================="
