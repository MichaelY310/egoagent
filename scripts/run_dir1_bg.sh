#!/bin/bash
# 后台运行方向1实验
# 直接运行: bash scripts/run_dir1_bg.sh

cd /home/tiger/egoagent

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="/home/tiger/egoagent/experiments/results/dir1_rerun_${TIMESTAMP}.log"

mkdir -p /home/tiger/egoagent/experiments/results

echo "Starting dir1 experiment at $(date), log: $LOG_FILE" >> /home/tiger/egoagent/experiments/results/monitor.log

# 清理 pycache
find /home/tiger/egoagent -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
true  # 保证上一步不会中断

# 运行
timeout 3600 python3 -u /home/tiger/egoagent/scripts/experiments/dir1_experiment.py > "$LOG_FILE" 2>&1
EXIT_CODE=$?

echo "Dir1 finished at $(date), exit=$EXIT_CODE, log=$LOG_FILE" >> /home/tiger/egoagent/experiments/results/monitor.log
