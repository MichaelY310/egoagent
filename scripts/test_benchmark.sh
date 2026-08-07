#!/bin/bash
set -e
cd /home/tiger/egoagent
echo "Testing benchmark imports..."
python3 -c "import sys; sys.path.insert(0,'.'); from experiments.evo_benchmark.metrics import EvolutionTrace, compute_all_metrics; print('metrics OK')"
python3 -c "import sys; sys.path.insert(0,'.'); from experiments.evo_benchmark.benchmark import EvoBenchmark; print('benchmark OK')"
python3 -c "import sys; sys.path.insert(0,'.'); from experiments.evo_benchmark.analyze import bootstrap_confidence_interval; print('analyze OK')"
python3 -c "import sys; sys.path.insert(0,'.'); from experiments.evo_benchmark.run_benchmark import main; print('run_benchmark OK')"
echo "All imports passed!"
