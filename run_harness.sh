#!/bin/bash
# === EgoAgent 启动脚本 ===

# --- 聊天模式（coder + coder_react）---
python /home/tiger/egoagent/run_harness.py \
    --harness_dir /home/tiger/egoagent/harness/coder_react \
    --agents agent:/home/tiger/egoagent/identity/coder \
    --workspace /home/tiger/egoagent/playground

# --- 聊天模式（dante + react_single）---
# python /home/tiger/egoagent/run_harness.py \
#     --harness_dir /home/tiger/egoagent/harness/react_single \
#     --agents agent:/home/tiger/egoagent/identity/dante \
#     --workspace /home/tiger/egoagent/playground

# --- 辩论模式（turn_based）---
# python /home/tiger/egoagent/run_harness.py \
#     --harness_dir /home/tiger/egoagent/harness/turn_based \
#     --agents 正方:/home/tiger/egoagent/identity/id1 反方:/home/tiger/egoagent/identity/id1 裁判:/home/tiger/egoagent/identity/dante \
#     --workspace /home/tiger/egoagent/playground2 \
#     --prompts "task:你的辩题内容"

# --- 轻量模式（不启动 Meilisearch）---
# python /home/tiger/egoagent/run_harness.py \
#     --harness_dir /home/tiger/egoagent/harness/react_single \
#     --agents agent:/home/tiger/egoagent/identity/dante \
#     --workspace /home/tiger/egoagent/playground \
#     --no-meilisearch
