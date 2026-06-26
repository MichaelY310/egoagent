#!/bin/bash
# SWE-bench 评估脚本
# 用法: bash swebench_eval/run_eval.sh <predictions_file> [instance_id]
#
# 示例:
#   # 用 gold patch 测试单条（验证环境正常）
#   bash swebench_eval/run_eval.sh swebench_eval/gold_prediction.jsonl
#
#   # 用你的 agent 生成的 prediction 评估
#   bash swebench_eval/run_eval.sh swebench_eval/my_predictions.jsonl
#
#   # 只评估特定 instance
#   bash swebench_eval/run_eval.sh swebench_eval/my_predictions.jsonl astropy__astropy-12907

set -e

# 代理设置
export HTTP_PROXY=http://sys-proxy-rd-relay.byted.org:8118
export http_proxy=http://sys-proxy-rd-relay.byted.org:8118
export https_proxy=http://sys-proxy-rd-relay.byted.org:8118

# Docker socket（如果用自定义位置）
# export DOCKER_HOST=unix:///tmp/docker.sock

PREDICTIONS_FILE="${1:?请指定 predictions 文件路径}"
INSTANCE_ID="${2:-}"
RUN_ID="egoagent_eval_$(date +%Y%m%d_%H%M%S)"
DATASET="SWE-bench/SWE-bench_Verified"

echo "=== SWE-bench 评估 ==="
echo "Predictions: $PREDICTIONS_FILE"
echo "Run ID: $RUN_ID"
echo "Dataset: $DATASET"

CMD="python -m swebench.harness.run_evaluation \
    --dataset_name $DATASET \
    --split test \
    --predictions_path $PREDICTIONS_FILE \
    --max_workers 4 \
    --run_id $RUN_ID \
    --timeout 1800"

if [ -n "$INSTANCE_ID" ]; then
    CMD="$CMD --instance_ids $INSTANCE_ID"
    echo "Instance: $INSTANCE_ID"
fi

echo ""
echo "执行: $CMD"
echo ""

eval $CMD

echo ""
echo "=== 评估完成 ==="
echo "日志目录: logs/run_evaluation/$RUN_ID/"
