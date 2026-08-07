#!/bin/bash
# 重新跑方向1实验（后台执行）
# 用法: nohup bash scripts/rerun_dir1.sh &

set -e
cd /home/tiger/egoagent

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="experiments/results/dir1_rerun_${TIMESTAMP}.log"
JSON_FILE="experiments/results/dir1_rerun_${TIMESTAMP}.json"

mkdir -p experiments/results

echo "============================================================"
echo "  Rerunning Direction 1: Meta-Evolution"
echo "  Timestamp: $TIMESTAMP"
echo "  Log: $LOG_FILE"
echo "  Timeout: 3600s"
echo "============================================================"

# 清理 pycache 确保用最新代码
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# 运行实验
timeout 3600 python3 -u scripts/experiments/dir1_experiment.py > "$LOG_FILE" 2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    STATUS="PASS"
elif [ $EXIT_CODE -eq 124 ]; then
    STATUS="TIMEOUT"
else
    STATUS="FAIL (exit=$EXIT_CODE)"
fi

# 提取 JSON 结果（如果脚本产出了的话）
if grep -q "EXPERIMENT RESULTS:" "$LOG_FILE"; then
    sed -n '/EXPERIMENT RESULTS:/,$ p' "$LOG_FILE" | tail -n +3 > "$JSON_FILE"
fi

echo ""
echo "============================================================"
echo "  Direction 1 completed: $STATUS"
echo "  Duration: ${SECONDS}s"
echo "  Log: $LOG_FILE"
echo "  JSON: $JSON_FILE"
echo "============================================================"
