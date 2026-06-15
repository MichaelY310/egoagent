"""查看 Meilisearch 中的所有数据"""
import os
import json
import sys

# 确保不走代理
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
os.environ["no_proxy"] = "127.0.0.1,localhost"

import meilisearch

url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:7700"
client = meilisearch.Client(url)

print(f"=== Meilisearch @ {url} ===\n")

# Stats
stats = client.get_all_stats()
print(f"数据库大小: {stats['databaseSize']} bytes")
print(f"上次更新: {stats.get('lastUpdate', 'N/A')}\n")

# Tools
try:
    tools_idx = client.index("tools")
    docs = tools_idx.get_documents({"limit": 200})
    print(f"--- Tools ({docs.total}) ---")
    for doc in docs.results:
        d = doc if isinstance(doc, dict) else doc.__dict__
        print(f"  [{d.get('short_name', '?')}] {d.get('description', '')[:80]}")
except Exception as e:
    print(f"Tools 索引不存在: {e}")

print()

# Knowledges
try:
    k_idx = client.index("knowledges")
    docs = k_idx.get_documents({"limit": 200})
    print(f"--- Knowledges ({docs.total}) ---")
    for doc in docs.results:
        d = doc if isinstance(doc, dict) else doc.__dict__
        print(f"  [{d.get('short_name', '?')}] {d.get('description', '')[:80]}")
except Exception as e:
    print(f"Knowledges 索引不存在: {e}")

# 可选：搜索测试
if len(sys.argv) > 2:
    query = sys.argv[2]
    print(f"\n--- 搜索: '{query}' ---")
    results = tools_idx.search(query)
    for hit in results["hits"]:
        print(f"  [{hit['short_name']}] score={hit.get('_rankingScore', '?')} | {hit['description'][:60]}")
    results_k = k_idx.search(query)
    for hit in results_k["hits"]:
        print(f"  [{hit['short_name']}] (knowledge) | {hit.get('description', '')[:60]}")
