#!/bin/bash
# test_lifelong_learning.sh
# 验证 Lifelong Learning 系统的所有模块可以正确 import 并基本运行

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=============================================="
echo "  Lifelong Learning System — Import Tests"
echo "=============================================="
echo "  Project root: $PROJECT_ROOT"
echo ""

cd "$PROJECT_ROOT"

# Test 1: PrincipleManager import
echo "[Test 1] Importing PrincipleManager..."
python3 -c "
import sys
sys.path.insert(0, '.')
from self_evolution.principle_manager import PrincipleManager
pm = PrincipleManager()
stats = pm.get_stats()
print(f'  OK - PrincipleManager loaded, {stats[\"total_count\"]} principles in library')
print(f'  Methods: detect_conflicts, resolve_conflict, compute_principle_value, prune,')
print(f'           detect_clusters, merge_cluster, build_hierarchy, add_context_tag,')
print(f'           retrieve_contextual, evaluate_transfer, compute_transferability_matrix,')
print(f'           detect_forgetting, get_stats')
"
echo ""

# Test 2: PredictiveDistiller import
echo "[Test 2] Importing PredictiveDistiller..."
python3 -c "
import sys
sys.path.insert(0, '.')
from self_evolution.predictive_distill import PredictiveDistiller
pd = PredictiveDistiller(novelty_threshold=0.3)
print(f'  OK - PredictiveDistiller loaded, threshold={pd.novelty_threshold}')
print(f'  Methods: predictive_distill, compute_novelty, compute_information_gain,')
print(f'           predict_coverage, filter_batch, get_distill_stats')

# Quick test: novelty computation
candidate = {'type': 'guiding', 'description': 'A completely unique and novel principle for testing purposes xyz123.'}
novelty = pd.compute_novelty(candidate)
info_gain = pd.compute_information_gain(candidate)
coverage = pd.predict_coverage(candidate)
print(f'  Test candidate novelty: {novelty:.3f}, info_gain: {info_gain:.3f}, covered: {coverage[\"is_covered\"]}')
"
echo ""

# Test 3: ExperienceBuffer import
echo "[Test 3] Importing ExperienceBuffer..."
python3 -c "
import sys
sys.path.insert(0, '.')
from self_evolution.experience_buffer import ExperienceBuffer, Experience
from pathlib import Path

# Use temp file
buf = ExperienceBuffer(max_size=10, buffer_file=Path('/tmp/_test_buffer.json'))
buf.clear()

# Add test experience
exp = Experience(
    trajectory_summary='Test trajectory: attempted coding task.',
    task_description='Write a hello world program',
    outcome='success',
    score=0.9,
    domain='coding',
)
buf.add(exp)

stats = buf.get_stats()
print(f'  OK - ExperienceBuffer loaded, size={stats[\"size\"]}/{stats[\"max_size\"]}')
print(f'  Methods: add, add_from_session, sample, replay_distill, should_replay,')
print(f'           get_stats, get_experiences_by_domain, get_failures, export, import_buffer')

# Test sampling
samples = buf.sample(1, strategy='priority')
print(f'  Sampled {len(samples)} experience(s): outcome={samples[0].outcome}')

buf.clear()
print(f'  Buffer cleared successfully')
"
echo ""

# Test 4: Experiment module import
echo "[Test 4] Importing experiment module..."
python3 -c "
import sys
sys.path.insert(0, '.')
from experiments.lifelong_learning.run_experiment import (
    experiment_growth_and_pruning,
    experiment_conflict_detection,
    experiment_transfer_matrix,
    experiment_forgetting_replay,
    run_all_experiments,
)
print('  OK - All experiment functions imported successfully')
print('  Functions: experiment_growth_and_pruning, experiment_conflict_detection,')
print('             experiment_transfer_matrix, experiment_forgetting_replay, run_all_experiments')
"
echo ""

# Test 5: Integration with existing engine.py
echo "[Test 5] Integration with existing engine.py..."
python3 -c "
import sys
sys.path.insert(0, '.')
from self_evolution.engine import distill_principles, retrieve_principles, update_scores
from self_evolution.principle_manager import PrincipleManager
from self_evolution.predictive_distill import PredictiveDistiller
from self_evolution.experience_buffer import ExperienceBuffer

# Verify they can work together
pm = PrincipleManager()
pd = PredictiveDistiller()
buf = ExperienceBuffer(max_size=50)

# PrincipleManager uses same data as engine
assert len(pm.principles) == len(pd.principles), 'Principle counts should match'
print(f'  OK - All modules share the same principle library ({len(pm.principles)} principles)')
print(f'  Integration verified: engine.py <-> principle_manager <-> predictive_distill <-> experience_buffer')
"
echo ""

# Test 6: Serialization/Deserialization
echo "[Test 6] Serialization tests..."
python3 -c "
import sys
sys.path.insert(0, '.')
from self_evolution.experience_buffer import Experience
import json

# Test Experience serialization roundtrip
exp = Experience(
    trajectory_summary='Test summary',
    task_description='Test task',
    outcome='failure',
    score=0.3,
    domain='debugging',
    principles_used=['abc123', 'def456'],
)
exp.replay_count = 2

# Serialize
data = exp.to_dict()
assert isinstance(data, dict), 'to_dict should return dict'
assert data['outcome'] == 'failure'

# Deserialize
exp2 = Experience.from_dict(data)
assert exp2.outcome == 'failure'
assert exp2.replay_count == 2
assert exp2.domain == 'debugging'
assert exp2.principles_used == ['abc123', 'def456']
print('  OK - Experience serialization roundtrip passed')

# Test JSON serialization
json_str = json.dumps(data)
data_back = json.loads(json_str)
exp3 = Experience.from_dict(data_back)
assert exp3.task_description == 'Test task'
print('  OK - JSON serialization roundtrip passed')
"
echo ""

echo "=============================================="
echo "  All tests PASSED!"
echo "=============================================="
echo ""
echo "  Module locations:"
echo "    - self_evolution/principle_manager.py"
echo "    - self_evolution/predictive_distill.py"
echo "    - self_evolution/experience_buffer.py"
echo "    - experiments/lifelong_learning/run_experiment.py"
echo ""
echo "  To run experiments:"
echo "    python3 experiments/lifelong_learning/run_experiment.py --experiment all"
echo "    python3 experiments/lifelong_learning/run_experiment.py --experiment growth"
echo "    python3 experiments/lifelong_learning/run_experiment.py --experiment conflict"
echo "    python3 experiments/lifelong_learning/run_experiment.py --experiment transfer"
echo "    python3 experiments/lifelong_learning/run_experiment.py --experiment forgetting"
echo ""
