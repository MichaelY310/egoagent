
# 聊天
python run_harness.py --harness_dir harness/react_single --agents agent:identity/dante --workspace playground

# 组织辩论
python run_harness.py --harness_dir harness/react_single --agents agent:identity/dante --workspace playground
请帮我创建一个辩论 session。使用 /home/tiger/egoagent/harness/turn_based 模板，辩题是"高度真实的 AI 陪伴系统，是否应该被允许长期替代人类情感关系？"，规则：正方支持允许，反方支持限制或禁止，双方必须引用至少2条参考资料中的观点，不允许只重复观点需要回应对方论点，每轮发言不超过300字。正方和反方都用 /home/tiger/egoagent/identity/id1，裁判用 /home/tiger/egoagent/identity/dante。workspace 设置为 /home/tiger/egoagent/playground2。return_mode 用 all，我想看完整过程。

# 和狗聊天
python run_harness.py --harness_dir harness/react_single --agents agent:identity/dog --workspace playground

# 狗狗变猫猫
python run_harness.py --harness_dir harness/react_single --agents agent:identity/dog --workspace playground_malkuth
帮我创建一个新 identity，基于你自己(dog)，叫 cat，但每次说话要用"喵喵，"开头。创建好之后启动一个新的 react_single session 让 cat 当 agent。