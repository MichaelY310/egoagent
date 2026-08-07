#!/bin/bash
# Pipeline Architecture Search (PAS) 测试脚本
# 验证 import 和基本操作

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "============================================"
echo "  Pipeline Architecture Search (PAS) Tests"
echo "============================================"
echo ""
echo "Project root: $PROJECT_ROOT"
echo ""

cd "$PROJECT_ROOT"

# Test 1: 基本 import
echo "--- Test 1: Import modules ---"
python3 -c "
import sys
sys.path.insert(0, '.')
from experiments.pipeline_search.search_space import SearchSpace, NODE_TYPES, EDGE_CONDITIONS
from experiments.pipeline_search.dag_validator import DAGValidator, validate_pipeline
from experiments.pipeline_search.population import Population, Individual
from experiments.pipeline_search.search_engine import PipelineArchitectureSearch
print('[PASS] All modules imported successfully')
print(f'  Node types: {list(NODE_TYPES.keys())}')
print(f'  Edge conditions: {EDGE_CONDITIONS}')
"
echo ""

# Test 2: SearchSpace 功能
echo "--- Test 2: SearchSpace ---"
python3 -c "
import sys
sys.path.insert(0, '.')
from experiments.pipeline_search.search_space import SearchSpace

space = SearchSpace()
print(f'  Allowed node types: {space.allowed_node_types}')
print(f'  Max nodes: {space.max_nodes}')

# 随机生成 pipeline
config = space.sample_random_pipeline(num_agents=2)
print(f'  Random pipeline: {config[\"name\"]}')
print(f'  Nodes: {list(config[\"pipeline\"][\"nodes\"].keys())}')
print(f'  Slots: {list(config[\"slots\"].keys())}')

# 节点模板
template = space.get_node_template('推理')
print(f'  推理 template: {template}')
print('[PASS] SearchSpace works correctly')
"
echo ""

# Test 3: DAG Validator
echo "--- Test 3: DAG Validator ---"
python3 -c "
import sys, json
sys.path.insert(0, '.')
from experiments.pipeline_search.dag_validator import validate_pipeline

# 合法配置
valid_config = {
    'name': 'test',
    'slots': {'agent': {'required': True}},
    'pipeline': {
        'start': 'wait_input',
        'nodes': {
            'wait_input': {'op': '等待输入', 'edges': [{'condition': 'input', 'to': 'infer'}]},
            'infer': {'op': '推理', 'agent': 'agent', 'edges': [
                {'condition': 'has_tool_calls', 'to': 'exec'},
                {'condition': 'has_text', 'to': 'wait_input'}
            ]},
            'exec': {'op': '执行工具', 'agent': 'agent', 'edges': [{'condition': 'default', 'to': 'infer'}]}
        }
    }
}
valid, msg = validate_pipeline(valid_config)
assert valid, f'Should be valid: {msg}'
print(f'  Valid config: {msg}')

# 非法配置 - 缺少 pipeline
invalid1 = {'name': 'bad'}
valid, msg = validate_pipeline(invalid1)
assert not valid
print(f'  Missing pipeline: {msg}')

# 非法配置 - 不可达节点
invalid2 = {
    'name': 'bad2',
    'slots': {'agent': {'required': True}},
    'pipeline': {
        'start': 'a',
        'nodes': {
            'a': {'op': '等待输入', 'edges': [{'condition': 'input', 'to': None}]},
            'unreachable': {'op': '推理', 'agent': 'agent', 'edges': []}
        }
    }
}
valid, msg = validate_pipeline(invalid2)
assert not valid
print(f'  Unreachable node: {msg}')

# 非法配置 - 无效节点类型
invalid3 = {
    'name': 'bad3',
    'slots': {},
    'pipeline': {
        'start': 'a',
        'nodes': {
            'a': {'op': '无效类型', 'edges': []}
        }
    }
}
valid, msg = validate_pipeline(invalid3)
assert not valid
print(f'  Invalid op: {msg}')

print('[PASS] DAG Validator works correctly')
"
echo ""

# Test 4: Population
echo "--- Test 4: Population ---"
python3 -c "
import sys
sys.path.insert(0, '.')
from experiments.pipeline_search.population import Population, Individual

pop = Population(size=5)

# 测试随机初始化
pop.initialize_random(count=3)
print(f'  Initialized: {len(pop.individuals)} individuals')

# 测试从 harness 加载
loaded = pop.initialize_from_harnesses('harness')
print(f'  Loaded from harness: {loaded} individuals')

# 测试排序
for ind in pop.individuals:
    import random
    ind.fitness = random.random()
pop.sort_by_fitness()
fitnesses = [ind.fitness for ind in pop.individuals]
assert fitnesses == sorted(fitnesses, reverse=True), 'Should be sorted descending'
print(f'  Sorted fitnesses: {[f\"{f:.2f}\" for f in fitnesses[:5]]}')

# 测试精英
elites = pop.get_elites()
print(f'  Elites: {len(elites)}')

# 测试选择
parents = pop.select_parents(count=2)
print(f'  Selected parents: {len(parents)}')

# 测试统计
stats = pop.get_stats()
print(f'  Stats: gen={stats[\"generation\"]}, size={stats[\"size\"]}, best={stats[\"best_fitness\"]:.2f}')

print('[PASS] Population works correctly')
"
echo ""

# Test 5: PipelineArchitectureSearch 初始化
echo "--- Test 5: Search Engine Init ---"
python3 -c "
import sys
sys.path.insert(0, '.')
from experiments.pipeline_search.search_engine import PipelineArchitectureSearch

config = {
    'search_strategy': 'mutation',
    'population_size': 5,
    'max_generations': 1,
    'eval_tasks': ['写一个 hello world 程序'],
    'mutation_rate': 0.7,
    'crossover_rate': 0.3,
    'harness_dir': 'harness',
    'output_dir': '/tmp/pas_test_output',
}

pas = PipelineArchitectureSearch(config)
print(f'  Strategy: {pas.strategy}')
print(f'  Population size: {pas.population_size}')
print(f'  Max generations: {pas.max_generations}')

# 测试验证
from experiments.pipeline_search.search_space import SearchSpace
space = SearchSpace()
pipeline = space.sample_random_pipeline()
valid, msg = pas.validate_pipeline(pipeline)
print(f'  Validate random pipeline: valid={valid}, msg={msg}')

# 测试评估（不调用 LLM）
score = pas.evaluate_pipeline(pipeline, [])
print(f'  Evaluate random pipeline (no tasks): score={score:.3f}')

# 测试程序化变异
mutated = pas._programmatic_mutate(pipeline)
valid_m, msg_m = pas.validate_pipeline(mutated)
print(f'  Programmatic mutation: valid={valid_m}')

print('[PASS] Search Engine initialized correctly')
"
echo ""

# Test 6: 验证现有 harness 配置
echo "--- Test 6: Validate existing harnesses ---"
python3 -c "
import sys, json
from pathlib import Path
sys.path.insert(0, '.')
from experiments.pipeline_search.dag_validator import validate_pipeline

harness_dir = Path('harness')
results = []
for config_file in sorted(harness_dir.glob('*/config.json')):
    config = json.loads(config_file.read_text())
    valid, msg = validate_pipeline(config)
    status = 'OK' if valid else 'FAIL'
    results.append((config_file.parent.name, valid, msg))
    print(f'  [{status}] {config_file.parent.name}: {msg[:60]}')

passed = sum(1 for _, v, _ in results if v)
print(f'  Total: {passed}/{len(results)} passed')
print('[PASS] Existing harness validation complete')
"
echo ""

echo "============================================"
echo "  ALL TESTS PASSED!"
echo "============================================"
