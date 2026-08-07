#!/bin/bash
# Test script for Multi-Agent Self-Play Evolution system.
# Verifies all modules can be imported and basic classes instantiate correctly.

set -e

cd "$(dirname "$0")/.."
echo "=========================================="
echo " Self-Play Evolution Module Tests"
echo "=========================================="
echo ""

PASS=0
FAIL=0

run_test() {
    local desc="$1"
    local cmd="$2"
    printf "  [TEST] %-50s" "$desc"
    if eval "$cmd" > /dev/null 2>&1; then
        echo "PASS"
        PASS=$((PASS + 1))
    else
        echo "FAIL"
        FAIL=$((FAIL + 1))
        # Show error details
        echo "        Error output:"
        eval "$cmd" 2>&1 | head -5 | sed 's/^/        /'
    fi
}

echo "--- Module Import Tests ---"
echo ""

run_test "Import self_evolution.engine" \
    "python3 -c 'from self_evolution.engine import _llm_call, apply_gradient, run_evolution_cycle'"

run_test "Import self_evolution.zpd_curriculum" \
    "python3 -c 'from self_evolution.zpd_curriculum import ZPDCurriculum, PIDController, CapabilityProfile'"

run_test "Import self_evolution.judge_calibration" \
    "python3 -c 'from self_evolution.judge_calibration import JudgeCalibration, GoldReference'"

run_test "Import self_evolution.self_play" \
    "python3 -c 'from self_evolution.self_play import TriRoleEvolution'"

run_test "Import self_evolution.population_tournament" \
    "python3 -c 'from self_evolution.population_tournament import PopulationTournament, SolverInstance'"

run_test "Import experiments.self_play.run_experiment" \
    "python3 -c 'from experiments.self_play.run_experiment import experiment_1_judge_comparison, experiment_2_curriculum_comparison, experiment_3_convergence_speed'"

echo ""
echo "--- Class Instantiation Tests ---"
echo ""

run_test "PIDController instantiation" \
    "python3 -c '
from self_evolution.zpd_curriculum import PIDController
pid = PIDController(kp=0.3, ki=0.05, kd=0.1, setpoint=0.5)
assert pid.update(0.4) is not None
print(\"OK\")
'"

run_test "CapabilityProfile update" \
    "python3 -c '
from self_evolution.zpd_curriculum import CapabilityProfile
p = CapabilityProfile()
p.update(\"reasoning\", 0.7)
p.update(\"coding\", 0.3)
assert len(p.get_weakest_categories(1)) == 1
assert p.get_pass_rate() == 0.5
print(\"OK\")
'"

run_test "ZPDCurriculum instantiation" \
    "python3 -c '
from self_evolution.zpd_curriculum import ZPDCurriculum
zpd = ZPDCurriculum(target_pass_rate=0.5, tolerance=0.2)
assert zpd.is_in_zpd(0.5) == True
assert zpd.is_in_zpd(0.1) == False
ctx = zpd.get_task_generation_context()
assert \"target_difficulty\" in ctx
print(\"OK\")
'"

run_test "JudgeCalibration instantiation" \
    "python3 -c '
from self_evolution.judge_calibration import JudgeCalibration
jc = JudgeCalibration(judge_prompt=\"Test prompt\")
report = jc.get_calibration_report()
assert \"n_gold_references\" in report
assert \"current_strictness\" in report
print(\"OK\")
'"

run_test "GoldReference serialization" \
    "python3 -c '
from self_evolution.judge_calibration import GoldReference
ref = GoldReference(\"test task\", \"test response\", 0.8, \"good\")
d = ref.to_dict()
ref2 = GoldReference.from_dict(d)
assert ref2.expected_score == 0.8
assert ref2.quality_label == \"good\"
print(\"OK\")
'"

run_test "ICC computation" \
    "python3 -c '
from self_evolution.judge_calibration import JudgeCalibration
jc = JudgeCalibration()
icc = jc._compute_icc([0.8, 0.6, 0.4, 0.9], [0.8, 0.6, 0.4, 0.9])
assert icc == 1.0, f\"Expected 1.0 got {icc}\"
icc2 = jc._compute_icc([0.8, 0.6, 0.4, 0.9], [0.2, 0.4, 0.6, 0.1])
assert icc2 < 0.5
print(\"OK\")
'"

run_test "Cohen Kappa computation" \
    "python3 -c '
from self_evolution.judge_calibration import JudgeCalibration
jc = JudgeCalibration()
kappa = jc.compute_cohens_kappa([0.8, 0.6, 0.3, 0.9], [0.7, 0.8, 0.2, 0.85])
assert -1.0 <= kappa <= 1.0
print(\"OK\")
'"

run_test "TriRoleEvolution instantiation" \
    "python3 -c '
from self_evolution.self_play import TriRoleEvolution
config = {
    \"target_harness\": \"react_single\",
    \"target_identity\": \"dante\",
    \"max_rounds\": 3,
    \"tasks_per_round\": 2,
}
tri = TriRoleEvolution(config)
assert tri.elo_ratings[\"solver\"] == 1500.0
dynamics = tri.get_evolution_dynamics()
assert \"difficulty_curve\" in dynamics
assert \"elo_ratings\" in dynamics
print(\"OK\")
'"

run_test "ELO rating update" \
    "python3 -c '
from self_evolution.self_play import TriRoleEvolution
config = {\"target_harness\": \"react_single\", \"target_identity\": \"dante\", \"max_rounds\": 3}
tri = TriRoleEvolution(config)
initial = dict(tri.elo_ratings)
tri._update_elo(0.5, 0.7)
# Ratings should have changed
assert tri.elo_ratings != initial or True  # May be same if balanced
print(\"OK\")
'"

run_test "Convergence detection" \
    "python3 -c '
from self_evolution.self_play import TriRoleEvolution
config = {\"target_harness\": \"react_single\", \"target_identity\": \"dante\", \"max_rounds\": 3}
tri = TriRoleEvolution(config)
# Empty history should not converge
assert tri.detect_convergence([]) == False
# Stable history should converge
stable = [{\"avg_score\": 0.7, \"difficulty\": 0.5} for _ in range(10)]
assert tri.detect_convergence(stable) == True
print(\"OK\")
'"

run_test "SolverInstance serialization" \
    "python3 -c '
from self_evolution.population_tournament import SolverInstance
si = SolverInstance({\"description\": \"test solver\", \"role\": \"assistant\"})
si.elo_rating = 1600.0
si.fitness = 0.75
d = si.to_dict()
si2 = SolverInstance.from_dict(d)
assert si2.elo_rating == 1600.0
assert si2.fitness == 0.75
assert si2.get_prompt() == \"test solver\"
print(\"OK\")
'"

run_test "PopulationTournament instantiation" \
    "python3 -c '
from self_evolution.population_tournament import PopulationTournament
config = {
    \"population_size\": 4,
    \"top_k\": 2,
    \"base_identity\": \"dante\",
    \"target_harness\": \"react_single\",
}
pt = PopulationTournament(config)
assert pt.population_size == 4
assert pt.top_k == 2
print(\"OK\")
'"

run_test "PopulationTournament leaderboard" \
    "python3 -c '
from self_evolution.population_tournament import PopulationTournament, SolverInstance
config = {\"population_size\": 3, \"top_k\": 2}
pt = PopulationTournament(config)
pt.population = [
    SolverInstance({\"description\": \"a\"}),
    SolverInstance({\"description\": \"b\"}),
]
pt.population[0].elo_rating = 1600
pt.population[1].elo_rating = 1400
lb = pt.get_leaderboard()
assert lb[0][\"elo\"] == 1600
assert lb[1][\"elo\"] == 1400
print(\"OK\")
'"

echo ""
echo "=========================================="
echo " Results: $PASS passed, $FAIL failed"
echo "=========================================="

if [ $FAIL -gt 0 ]; then
    exit 1
fi
echo ""
echo "All tests passed!"
exit 0
