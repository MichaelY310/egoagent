#!/bin/bash
# === 每10秒轮询 Meilisearch 并输出到文件 ===
# 用法: bash watch_meilisearch.sh [地址] [输出文件]
# 示例: bash watch_meilisearch.sh http://127.0.0.1:7700 meilisearch_dump.json

URL="${1:-http://127.0.0.1:7700}"
OUTPUT="${2:-/home/tiger/egoagent/meilisearch_dump.json}"

# 确保 localhost 不走代理
export no_proxy="127.0.0.1,localhost"
export NO_PROXY="127.0.0.1,localhost"

echo "监控地址: $URL"
echo "输出文件: $OUTPUT"
echo "每10秒刷新一次，Ctrl+C 退出"
echo "---"

while true; do
    {
        echo "{"
        echo "  \"timestamp\": \"$(date '+%Y-%m-%d %H:%M:%S')\","
        echo "  \"tools\": $(curl -s "${URL}/indexes/tools/documents?limit=200" 2>/dev/null || echo '{"error":"连接失败"}'),"
        echo "  \"knowledges\": $(curl -s "${URL}/indexes/knowledges/documents?limit=200" 2>/dev/null || echo '{"error":"连接失败"}')"
        echo "}"
    } > "$OUTPUT"

    echo "[$(date '+%H:%M:%S')] 已更新 $OUTPUT"
    sleep 10
done
