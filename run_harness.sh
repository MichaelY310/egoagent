# 聊天
python /home/tiger/egoagent/run_harness.py \
    --harness_dir /home/tiger/egoagent/harness/react_single \
    --agents agent:/home/tiger/egoagent/identity/dante \
    --workspace /home/tiger/egoagent/playground

# 辩论（使用默认 prompts）
# python /home/tiger/egoagent/run_harness.py \
#     --harness_dir /home/tiger/egoagent/harness/turn_based \
#     --agents 正方:/home/tiger/egoagent/identity/id1 反方:/home/tiger/egoagent/identity/id1 裁判:/home/tiger/egoagent/identity/dante \
#     --workspace /home/tiger/egoagent/playground2 \
#     --prompts "task:你的辩题内容"

# 完整辩论复原见 run_debate.sh
