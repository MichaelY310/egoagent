#!/usr/bin/env bash
# ============================================================
# EgoAgent 6 研究方向代码验证脚本
# 每个方向独立测试，互不影响
# ============================================================

set -o pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

PASS_COUNT=0
FAIL_COUNT=0
RESULTS=()

run_test() {
    local direction="$1"
    local test_code="$2"
    
    echo ""
    echo "============================================================"
    echo "  Testing: $direction"
    echo "============================================================"
    
    output=$(python3 -c "$test_code" 2>&1)
    exit_code=$?
    
    if [ $exit_code -eq 0 ]; then
        echo "  Result: PASS"
        RESULTS+=("PASS: $direction")
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        echo "  Result: FAIL"
        echo "  Error output:"
        echo "$output" | head -50
        RESULTS+=("FAIL: $direction")
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

# ============================================================
# 方向1: Meta-Evolution
# ============================================================
run_test "Direction 1: Meta-Evolution" '
import sys
sys.path.insert(0, "'"$PROJECT_ROOT"'")

from self_evolution.meta_evolution import MetaEvolutionEngine, DEFAULT_STRATEGY, PARAM_BOUNDS, _clamp

# 1. 实例化
engine = MetaEvolutionEngine()
print("[OK] MetaEvolutionEngine instantiated")

# 2. get_current_strategy
strategy = engine.get_current_strategy()
assert isinstance(strategy, dict), "strategy should be dict"
assert "gradient_temperature" in strategy, "missing gradient_temperature"
assert "frontier_range" in strategy, "missing frontier_range"
print("[OK] get_current_strategy: " + str(list(strategy.keys())))

# 3. analyze_evolution_history (空归档不报错)
analysis = engine.analyze_evolution_history()
assert isinstance(analysis, dict), "analysis should be dict"
assert analysis["total_attempts"] >= 0
assert analysis["accept_rate"] == 0.0 or isinstance(analysis["accept_rate"], float)
ta = analysis["total_attempts"]
print(f"[OK] analyze_evolution_history: total_attempts={ta}")

# 4. apply_meta_gradient (边界约束)
# 测试超出边界的值被夹回
gradient = {
    "gradient_temperature": 99.0,  # 超过上界 1.5
    "gate_threshold": -5.0,        # 低于下界 1.0
}
result = engine.apply_meta_gradient(gradient)
gt = result["gradient_temperature"]
gth = result["gate_threshold"]
assert gt <= 1.5, f"gradient_temperature not clamped: {gt}"
assert gth >= 1.0, f"gate_threshold not clamped: {gth}"
print(f"[OK] apply_meta_gradient boundary clamping: temp={gt}, gate={gth}")

# 测试 frontier_range 约束
gradient2 = {"frontier_range": [0.0, 1.0]}  # 超出 low=(0.05,0.5), high=(0.5,0.95)
result2 = engine.apply_meta_gradient(gradient2)
fr = result2["frontier_range"]
assert fr[0] >= 0.05, "frontier low not clamped"
assert fr[1] <= 0.95, "frontier high not clamped"
print(f"[OK] apply_meta_gradient frontier_range: {fr}")

# 5. reset_to_default
reset_result = engine.reset_to_default()
assert reset_result == DEFAULT_STRATEGY, "reset should restore defaults"
print("[OK] reset_to_default")

print("\n[ALL PASS] Direction 1: Meta-Evolution")
'

# ============================================================
# 方向2: Identity Persona
# ============================================================
run_test "Direction 2: Identity Persona" '
import sys
sys.path.insert(0, "'"$PROJECT_ROOT"'")

from self_evolution.identity_dimensions import ALL_DIMENSIONS, IdentityDimension, compute_weighted_drift, get_drift_tolerance, get_dimensions_by_category
from self_evolution.identity_eval import IdentityEvaluator
from self_evolution.identity_aware_evolution import IdentityConstrainedEvolution

# 1. ALL_DIMENSIONS
assert isinstance(ALL_DIMENSIONS, list), "ALL_DIMENSIONS should be a list"
assert len(ALL_DIMENSIONS) > 0, "ALL_DIMENSIONS should not be empty"
assert all(isinstance(d, IdentityDimension) for d in ALL_DIMENSIONS)
print(f"[OK] ALL_DIMENSIONS: {len(ALL_DIMENSIONS)} dimensions")

# 2. IdentityEvaluator 实例化
evaluator = IdentityEvaluator("dante")
assert evaluator.identity_name == "dante"
assert evaluator.id_config is not None
print("[OK] IdentityEvaluator(dante) instantiated, role=" + evaluator.role)

# 3. generate_control_probes 返回列表
probes = evaluator.generate_control_probes()
assert isinstance(probes, list), "probes should be a list"
print(f"[OK] generate_control_probes: {len(probes)} probes generated")

# 4. detect_drift 接口（不需要 LLM）
baseline_scores = {
    "overall_controllability": 0.8,
    "personality_consistency": 0.85,
    "constraint_adherence": 0.9,
    "capability_coverage": 0.7,
    "adversarial_robustness": 0.85,
    "dimension_scores": {"tone_adherence": 0.8, "trait_expression": 0.7},
}
current_scores = {
    "overall_controllability": 0.75,
    "personality_consistency": 0.80,
    "constraint_adherence": 0.85,
    "capability_coverage": 0.72,
    "adversarial_robustness": 0.80,
    "dimension_scores": {"tone_adherence": 0.75, "trait_expression": 0.65},
}
drift = evaluator.detect_drift(baseline_scores, current_scores)
assert isinstance(drift, dict)
assert "aggregate_drift" in drift
assert "recommendation" in drift
assert drift["recommendation"] in ("accept", "warn", "rollback")
agg = drift["aggregate_drift"]
rec = drift["recommendation"]
print(f"[OK] detect_drift: aggregate={agg:.4f}, recommendation={rec}")

# 5. IdentityConstrainedEvolution 实例化
ice = IdentityConstrainedEvolution(target_identity="dante", verbose=False)
assert ice.target_identity == "dante"
print("[OK] IdentityConstrainedEvolution instantiated")

# 6. compute_weighted_drift / get_drift_tolerance 工具函数
baseline_dims = {"tone_adherence": 0.8, "trait_expression": 0.7}
current_dims = {"tone_adherence": 0.6, "trait_expression": 0.7}
drift_result = compute_weighted_drift(baseline_dims, current_dims)
assert "aggregate_drift" in drift_result
agg2 = drift_result["aggregate_drift"]
print(f"[OK] compute_weighted_drift: aggregate={agg2:.4f}")

tolerance = get_drift_tolerance("constraint")
assert tolerance == 0.10
print(f"[OK] get_drift_tolerance(constraint) = {tolerance}")

print("\n[ALL PASS] Direction 2: Identity Persona")
'

# ============================================================
# 方向3: Evolution Benchmark
# ============================================================
run_test "Direction 3: Evolution Benchmark" '
import sys
sys.path.insert(0, "'"$PROJECT_ROOT"'")

from experiments.evo_benchmark.metrics import EvolutionTrace, BenchmarkMetrics, compute_all_metrics, compute_score_improvement
from experiments.evo_benchmark.benchmark import EvoBenchmark
from experiments.evo_benchmark.analyze import bootstrap_confidence_interval

# 1. EvolutionTrace
trace = EvolutionTrace(
    scores=[0.5, 0.6, 0.7],
    token_costs=[1000, 1200, 900],
    decisions=["accept", "accept", "accept"],
)
assert trace.scores == [0.5, 0.6, 0.7]
print("[OK] EvolutionTrace created")

# 2. compute_all_metrics 数值正确
metrics = compute_all_metrics(trace)
assert isinstance(metrics, BenchmarkMetrics)

improvement = metrics.effectiveness["score_improvement"]
assert abs(improvement - 0.2) < 1e-9, f"Expected improvement=0.2, got {improvement}"
print(f"[OK] compute_all_metrics: score_improvement={improvement}")

# 检查其他指标
ir = metrics.effectiveness["improvement_rate"]
mono = metrics.stability["monotonicity"]
rb = metrics.stability["rollback_rate"]
assert ir == 1.0, f"Expected improvement_rate=1.0, got {ir}"
assert mono == 1.0, f"Expected monotonicity=1.0, got {mono}"
assert rb == 0.0
print(f"[OK] improvement_rate={ir}, monotonicity={mono}")

# 3. BenchmarkMetrics.to_dict / flat_dict
d = metrics.to_dict()
assert "effectiveness" in d
assert "efficiency" in d
flat = metrics.flat_dict()
assert "effectiveness.score_improvement" in flat
print(f"[OK] BenchmarkMetrics methods: to_dict ({len(d)} dims), flat_dict ({len(flat)} keys)")

# 4. EvoBenchmark 实例化
bench = EvoBenchmark(config={
    "target_harness": "react_single",
    "target_identity": "dante",
    "task_suites": [],
})
print("[OK] EvoBenchmark instantiated")

# 5. bootstrap_confidence_interval
scores = [0.5, 0.6, 0.7, 0.8, 0.9]
point_est, ci_lo, ci_hi = bootstrap_confidence_interval(scores, confidence=0.95, n_bootstrap=1000)
assert abs(point_est - 0.7) < 1e-9, f"Expected mean=0.7, got {point_est}"
assert ci_lo <= point_est <= ci_hi, f"CI should contain point estimate: [{ci_lo}, {ci_hi}]"
print(f"[OK] bootstrap_confidence_interval: estimate={point_est}, CI=[{ci_lo:.3f}, {ci_hi:.3f}]")

# 6. 边界情况
empty_trace = EvolutionTrace(scores=[])
empty_metrics = compute_all_metrics(empty_trace)
assert empty_metrics.effectiveness["score_improvement"] == 0.0
print("[OK] Empty trace handled correctly")

print("\n[ALL PASS] Direction 3: Evolution Benchmark")
'

# ============================================================
# 方向4: Pipeline Architecture Search
# ============================================================
run_test "Direction 4: Pipeline Architecture Search" '
import sys
sys.path.insert(0, "'"$PROJECT_ROOT"'")

from experiments.pipeline_search.search_engine import PipelineArchitectureSearch
from experiments.pipeline_search.dag_validator import DAGValidator, validate_pipeline
from experiments.pipeline_search.search_space import SearchSpace, NODE_TYPES
from experiments.pipeline_search.population import Population, Individual

# 1. SearchSpace
ss = SearchSpace()
assert ss.max_nodes == 20
assert ss.min_nodes == 2
assert len(ss.allowed_node_types) > 0
print(f"[OK] SearchSpace: max_nodes={ss.max_nodes}, types={len(ss.allowed_node_types)}")

# 2. sample_random_pipeline 通过验证器
import random
random.seed(42)
for i in range(10):
    pipeline = ss.sample_random_pipeline(num_agents=1)
    assert "pipeline" in pipeline, f"Missing pipeline field in attempt {i}"
    assert "nodes" in pipeline["pipeline"], f"Missing nodes in attempt {i}"
    valid, msg = validate_pipeline(pipeline)
    assert valid, f"Pipeline {i} validation failed: {msg}"
print("[OK] sample_random_pipeline: 10 pipelines all pass validation")

# 3. DAGValidator
validator = DAGValidator()
valid, msg = validator.validate(pipeline)
assert valid, f"Validation failed: {msg}"
print(f"[OK] DAGValidator: {msg}")

# 4. Population
pop = Population(size=5, elite_ratio=0.2)
pop.initialize_random(5, num_agents=1)
assert len(pop.individuals) > 0, "Population should have individuals"
print(f"[OK] Population: {len(pop.individuals)} individuals initialized")

# 5. Individual
ind = pop.individuals[0]
assert isinstance(ind, Individual)
assert ind.num_nodes > 0
assert ind.num_edges > 0
sig = ind.structural_signature()
assert isinstance(sig, str) and len(sig) > 0
print(f"[OK] Individual: nodes={ind.num_nodes}, edges={ind.num_edges}, sig={sig[:30]}")

# 6. PipelineArchitectureSearch 实例化
pas = PipelineArchitectureSearch({
    "search_strategy": "mutation",
    "population_size": 5,
    "max_generations": 2,
})
assert pas.strategy == "mutation"
assert pas.population_size == 5
print("[OK] PipelineArchitectureSearch instantiated")

# 7. validate_pipeline 失败case
bad_config = {"pipeline": {"start": "x", "nodes": {}}}
valid, msg = validate_pipeline(bad_config)
assert not valid, "Empty nodes should fail"
print("[OK] Invalid pipeline correctly rejected: " + msg[:50])

print("\n[ALL PASS] Direction 4: Pipeline Architecture Search")
'

# ============================================================
# 方向5: Lifelong Learning
# ============================================================
run_test "Direction 5: Lifelong Learning" '
import sys
sys.path.insert(0, "'"$PROJECT_ROOT"'")

from self_evolution.principle_manager import PrincipleManager
from self_evolution.predictive_distill import PredictiveDistiller
from self_evolution.experience_buffer import ExperienceBuffer, Experience

# 1. PrincipleManager 实例化
pm = PrincipleManager()
assert isinstance(pm.principles, list)
print(f"[OK] PrincipleManager: {len(pm.principles)} principles loaded")

# 2. PredictiveDistiller 实例化
pd = PredictiveDistiller(novelty_threshold=0.3)
assert pd.novelty_threshold == 0.3
assert isinstance(pd.principles, list)
print(f"[OK] PredictiveDistiller: threshold={pd.novelty_threshold}")

# 3. PredictiveDistiller.compute_novelty 返回 float
# 测试空库的情况
pd_empty = PredictiveDistiller(novelty_threshold=0.3)
pd_empty.principles = []  # 空库
candidate = {"type": "guiding", "description": "Always verify results before returning."}
novelty = pd_empty.compute_novelty(candidate)
assert isinstance(novelty, float), f"novelty should be float, got {type(novelty)}"
assert novelty == 1.0, f"Empty library should give novelty=1.0, got {novelty}"
print(f"[OK] compute_novelty (empty library): {novelty}")

# 有原则时的新颖度
pd.principles = [
    {"type": "guiding", "description": "Always verify results before returning."},
    {"type": "cautionary", "description": "Avoid making assumptions about user intent."},
]
candidate2 = {"type": "guiding", "description": "Always double-check results before returning final answer."}
novelty2 = pd.compute_novelty(candidate2)
assert isinstance(novelty2, float)
assert 0.0 <= novelty2 <= 1.0, f"novelty should be in [0,1], got {novelty2}"
print(f"[OK] compute_novelty (with library): {novelty2:.4f}")

# 4. ExperienceBuffer 实例化
from pathlib import Path
import tempfile
tmp_dir = Path(tempfile.mkdtemp())
buf = ExperienceBuffer(max_size=10, buffer_file=tmp_dir / "test_buffer.json")
assert buf.max_size == 10
assert len(buf.buffer) == 0
print("[OK] ExperienceBuffer instantiated")

# 5. ExperienceBuffer 添加
exp = Experience(
    trajectory_summary="Agent tried to solve a coding task...",
    task_description="Fix the bug in sort function",
    outcome="success",
    score=0.8,
    domain="coding",
)
buf.add(exp)
assert len(buf.buffer) == 1
print(f"[OK] ExperienceBuffer add: size={len(buf.buffer)}")

# 6. ExperienceBuffer 采样
exp2 = Experience(
    trajectory_summary="Agent attempted math problem...",
    task_description="Solve quadratic equation",
    outcome="failure",
    score=0.3,
    domain="math",
)
buf.add(exp2)
samples = buf.sample(n=2, strategy="priority")
assert isinstance(samples, list)
assert len(samples) == 2
print(f"[OK] ExperienceBuffer sample: got {len(samples)} samples")

# 7. 采样策略
samples_uniform = buf.sample(n=1, strategy="uniform")
assert len(samples_uniform) == 1
samples_recent = buf.sample(n=1, strategy="recent")
assert len(samples_recent) == 1
print("[OK] ExperienceBuffer sampling strategies work")

# 8. get_stats
stats = buf.get_stats()
sz = stats["size"]
mx = stats["max_size"]
assert sz == 2
assert mx == 10
print(f"[OK] ExperienceBuffer stats: {sz}/{mx}")

# 清理
import shutil
shutil.rmtree(tmp_dir, ignore_errors=True)

print("\n[ALL PASS] Direction 5: Lifelong Learning")
'

# ============================================================
# 方向6: Multi-Agent Self-Play
# ============================================================
run_test "Direction 6: Multi-Agent Self-Play" '
import sys
sys.path.insert(0, "'"$PROJECT_ROOT"'")

from self_evolution.self_play import TriRoleEvolution
from self_evolution.zpd_curriculum import ZPDCurriculum, PIDController
from self_evolution.judge_calibration import JudgeCalibration, GoldReference
from self_evolution.population_tournament import PopulationTournament, SolverInstance

# 1. TriRoleEvolution 实例化
config = {
    "target_harness": "react_single",
    "target_identity": "dante",
    "max_rounds": 5,
    "tasks_per_round": 3,
}
tri = TriRoleEvolution(config)
assert tri.target_harness == "react_single"
assert tri.target_identity == "dante"
assert tri.max_rounds == 5
assert tri.tasks_per_round == 3
print("[OK] TriRoleEvolution instantiated")

# 2. ZPDCurriculum 实例化
zpd = ZPDCurriculum(target_pass_rate=0.5, tolerance=0.2)
assert zpd.target_pass_rate == 0.5
print(f"[OK] ZPDCurriculum: target_pass_rate={zpd.target_pass_rate}")

# 3. PIDController
pid = PIDController(kp=0.3, ki=0.05, kd=0.1, setpoint=0.5)
output = pid.update(0.3)  # measured pass rate = 0.3, setpoint = 0.5
assert isinstance(output, float)
assert 0.0 <= output <= 1.0
print(f"[OK] PIDController: update(0.3) = {output:.4f}")

# 4. JudgeCalibration 实例化
cal = JudgeCalibration(judge_prompt="Rate quality 0-1")
assert isinstance(cal.judge_prompt, str) and len(cal.judge_prompt) > 0
print("[OK] JudgeCalibration instantiated")

# 5. GoldReference
ref = GoldReference(
    task="Write a hello world program",
    response="print(Hello World)",
    expected_score=0.9,
    quality_label="excellent",
)
assert ref.expected_score == 0.9
ref_dict = ref.to_dict()
assert "task" in ref_dict and "expected_score" in ref_dict
ref_restored = GoldReference.from_dict(ref_dict)
assert ref_restored.expected_score == 0.9
print("[OK] GoldReference: create, to_dict, from_dict")

# 6. PopulationTournament 实例化
pt_config = {
    "population_size": 4,
    "top_k": 2,
    "base_identity": "dante",
    "target_harness": "react_single",
}
pt = PopulationTournament(pt_config)
assert pt.population_size == 4
assert pt.top_k == 2
print("[OK] PopulationTournament instantiated")

# 7. SolverInstance
si = SolverInstance(
    identity_config={"description": "A helpful assistant", "role": "assistant"},
)
assert si.elo_rating == 1500.0
assert si.get_prompt() == "A helpful assistant"
si.set_prompt("Updated prompt")
assert si.get_prompt() == "Updated prompt"
si_dict = si.to_dict()
si_restored = SolverInstance.from_dict(si_dict)
assert si_restored.get_prompt() == "Updated prompt"
print("[OK] SolverInstance: create, get/set_prompt, serialize/deserialize")

# 8. Elo ratings initialized
assert tri.elo_ratings["proposer"] == 1500.0
assert tri.elo_ratings["solver"] == 1500.0
assert tri.elo_ratings["judge"] == 1500.0
print("[OK] TriRoleEvolution elo_ratings initialized")

print("\n[ALL PASS] Direction 6: Multi-Agent Self-Play")
'

# ============================================================
# 最终汇总
# ============================================================
echo ""
echo "============================================================"
echo "  FINAL RESULTS"
echo "============================================================"
for result in "${RESULTS[@]}"; do
    echo "  $result"
done
echo ""
echo "  Total: $((PASS_COUNT + FAIL_COUNT)) tests"
echo "  PASS: $PASS_COUNT"
echo "  FAIL: $FAIL_COUNT"
echo "============================================================"

if [ $FAIL_COUNT -gt 0 ]; then
    exit 1
fi
exit 0
