#!/bin/bash
# 复原辩论效果：使用 turn_based harness 进行 AI 陪伴辩论
# 所有 prompt 都作为参数传入，不依赖 prompts 文件夹

cd /home/tiger/egoagent

TASK='你们将围绕以下议题展开辩论：

"高度真实的 AI 陪伴系统，是否应该被允许长期替代人类情感关系？"

规则：
1. 正方支持允许，反方支持限制或禁止。
2. 双方必须引用至少 2 条参考资料中的观点。
3. 不允许只重复观点，需要回应对方论点。
4. 每轮发言不超过 300 字。
5. 共进行：
   - 开场陈述
   - 两轮攻防
   - 总结陈词'

python run_harness.py \
    --harness_dir harness/turn_based \
    --agents 正方:identity/id1 反方:identity/id1 裁判:identity/dante \
    --workspace playground2 \
    --prompts "task:${TASK}"
