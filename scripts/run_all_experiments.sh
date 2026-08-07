#!/bin/bash
# ============================================================
# EgoAgent 全方向实验运行脚本
# 
# 6个研究方向，每个方向独立运行，1小时超时
# 所有输出保存到 experiments/results/ 目录
# 最终汇总所有方向的结果（PASS/FAIL/TIMEOUT）
# ============================================================

set -o pipefail

# ============================================================
# 配置
# ============================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
EXPERIMENTS_DIR="$SCRIPT_DIR/experiments"
RESULTS_DIR="$PROJECT_ROOT/experiments/results"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
TIMEOUT_SECONDS=3600  # 每个方向1小时超时

# LLM 配置（供参考，实际由 Python 代码读取）
export LLM_BASE_URL="http://[fdbd:dc05:10:10a::27]:9638/v1"
export LLM_MODEL="Qwen3-8B-yangyuan"

# ============================================================
# 准备
# ============================================================
mkdir -p "$RESULTS_DIR"

echo "============================================================"
echo "  EgoAgent Full Experiment Run"
echo "  Timestamp: $TIMESTAMP"
echo "  Project:   $PROJECT_ROOT"
echo "  Results:   $RESULTS_DIR"
echo "  Timeout:   ${TIMEOUT_SECONDS}s per direction"
echo "============================================================"
echo ""

# 定义6个方向
DIRECTIONS=(
    "dir1:Meta-Evolution（元进化）:dir1_experiment.py"
    "dir2:Identity Persona（身份评估）:dir2_experiment.py"
    "dir3:Evolution Benchmark（进化基准）:dir3_experiment.py"
    "dir4:Pipeline Architecture Search（架构搜索）:dir4_experiment.py"
    "dir5:Lifelong Learning（持续学习）:dir5_experiment.py"
    "dir6:Multi-Agent Self-Play（多角色博弈）:dir6_experiment.py"
)

# 结果记录
declare -A DIR_STATUS
declare -A DIR_DURATION

# ============================================================
# 运行单个方向
# ============================================================
run_direction() {
    local dir_id="$1"
    local dir_name="$2"
    local dir_script="$3"
    local log_file="$RESULTS_DIR/${dir_id}_${TIMESTAMP}.log"
    local json_file="$RESULTS_DIR/${dir_id}_${TIMESTAMP}.json"

    echo "------------------------------------------------------------"
    echo "  [$dir_id] $dir_name"
    echo "  Script: $EXPERIMENTS_DIR/$dir_script"
    echo "  Log:    $log_file"
    echo "  Start:  $(date '+%Y-%m-%d %H:%M:%S')"
    echo "------------------------------------------------------------"

    local start_time=$(date +%s)

    # 运行实验，带超时（PYTHONUNBUFFERED 确保实时输出）
    timeout "$TIMEOUT_SECONDS" python3 -u "$EXPERIMENTS_DIR/$dir_script" \
        > >(tee "$log_file") 2>&1
    local exit_code=$?

    local end_time=$(date +%s)
    local duration=$((end_time - start_time))

    # 判断结果
    local status="FAIL"
    if [ $exit_code -eq 0 ]; then
        # 从输出中提取 JSON 结果
        local json_output=$(grep -A 9999 "^EXPERIMENT RESULTS:" "$log_file" | tail -n +3)
        if [ -n "$json_output" ]; then
            echo "$json_output" > "$json_file"
            # 检查 status 字段
            local exp_status=$(python3 -c "
import json, sys
try:
    data = json.loads('''$json_output''')
    print(data.get('status', 'UNKNOWN'))
except:
    # 尝试从文件读取
    try:
        with open('$json_file') as f:
            data = json.load(f)
        print(data.get('status', 'UNKNOWN'))
    except:
        print('UNKNOWN')
" 2>/dev/null)
            status="${exp_status:-PASS}"
        else
            status="PASS"
        fi
    elif [ $exit_code -eq 124 ]; then
        status="TIMEOUT"
    else
        status="FAIL"
    fi

    DIR_STATUS[$dir_id]="$status"
    DIR_DURATION[$dir_id]="$duration"

    echo ""
    echo "  [$dir_id] Result: $status (${duration}s)"
    echo ""
}

# ============================================================
# 依次运行所有方向
# ============================================================
TOTAL_START=$(date +%s)

for dir_info in "${DIRECTIONS[@]}"; do
    IFS=':' read -r dir_id dir_name dir_script <<< "$dir_info"
    run_direction "$dir_id" "$dir_name" "$dir_script"
done

TOTAL_END=$(date +%s)
TOTAL_DURATION=$((TOTAL_END - TOTAL_START))

# ============================================================
# 汇总结果
# ============================================================
echo ""
echo "============================================================"
echo "  EXPERIMENT SUMMARY"
echo "  Timestamp: $TIMESTAMP"
echo "  Total Duration: ${TOTAL_DURATION}s ($(( TOTAL_DURATION / 60 ))m $(( TOTAL_DURATION % 60 ))s)"
echo "============================================================"
echo ""
printf "  %-8s %-45s %-10s %s\n" "ID" "Direction" "Status" "Duration"
printf "  %-8s %-45s %-10s %s\n" "--------" "---------------------------------------------" "----------" "--------"

PASS_COUNT=0
FAIL_COUNT=0
TIMEOUT_COUNT=0

for dir_info in "${DIRECTIONS[@]}"; do
    IFS=':' read -r dir_id dir_name dir_script <<< "$dir_info"
    status="${DIR_STATUS[$dir_id]:-UNKNOWN}"
    duration="${DIR_DURATION[$dir_id]:-0}"
    printf "  %-8s %-45s %-10s %ss\n" "$dir_id" "$dir_name" "$status" "$duration"

    case "$status" in
        PASS) ((PASS_COUNT++)) ;;
        TIMEOUT) ((TIMEOUT_COUNT++)) ;;
        *) ((FAIL_COUNT++)) ;;
    esac
done

echo ""
echo "  Total: PASS=$PASS_COUNT  FAIL=$FAIL_COUNT  TIMEOUT=$TIMEOUT_COUNT"
echo "============================================================"

# ============================================================
# 输出 JSON 格式的结果摘要
# ============================================================
SUMMARY_FILE="$RESULTS_DIR/summary_${TIMESTAMP}.json"

python3 -c "
import json
from datetime import datetime

summary = {
    'timestamp': '$TIMESTAMP',
    'total_duration_seconds': $TOTAL_DURATION,
    'pass_count': $PASS_COUNT,
    'fail_count': $FAIL_COUNT,
    'timeout_count': $TIMEOUT_COUNT,
    'directions': {}
}

directions_info = [
    ('dir1', 'Meta-Evolution'),
    ('dir2', 'Identity Persona'),
    ('dir3', 'Evolution Benchmark'),
    ('dir4', 'Pipeline Architecture Search'),
    ('dir5', 'Lifelong Learning'),
    ('dir6', 'Multi-Agent Self-Play'),
]

status_map = {
$(for dir_info in "${DIRECTIONS[@]}"; do
    IFS=':' read -r dir_id dir_name dir_script <<< "$dir_info"
    echo "    '$dir_id': '${DIR_STATUS[$dir_id]:-UNKNOWN}',"
done)
}

duration_map = {
$(for dir_info in "${DIRECTIONS[@]}"; do
    IFS=':' read -r dir_id dir_name dir_script <<< "$dir_info"
    echo "    '$dir_id': ${DIR_DURATION[$dir_id]:-0},"
done)
}

for dir_id, dir_name in directions_info:
    summary['directions'][dir_id] = {
        'name': dir_name,
        'status': status_map.get(dir_id, 'UNKNOWN'),
        'duration_seconds': duration_map.get(dir_id, 0),
        'log_file': f'${RESULTS_DIR}/{dir_id}_${TIMESTAMP}.log',
        'json_file': f'${RESULTS_DIR}/{dir_id}_${TIMESTAMP}.json',
    }

    # 尝试读取详细结果
    json_path = f'${RESULTS_DIR}/{dir_id}_${TIMESTAMP}.json'
    try:
        with open(json_path) as f:
            detail = json.load(f)
        summary['directions'][dir_id]['detail'] = detail.get('summary', {})
    except (FileNotFoundError, json.JSONDecodeError):
        pass

print(json.dumps(summary, indent=2, ensure_ascii=False))
" > "$SUMMARY_FILE"

echo ""
echo "  Summary JSON: $SUMMARY_FILE"
echo ""
cat "$SUMMARY_FILE"
echo ""
echo "============================================================"
echo "  All experiments completed."
echo "============================================================"

# 返回非零退出码如果有失败
if [ $FAIL_COUNT -gt 0 ] || [ $TIMEOUT_COUNT -gt 0 ]; then
    exit 1
fi
exit 0
