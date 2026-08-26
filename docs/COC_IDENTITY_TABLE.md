# CoC Identity Table

EgoAgent 的 CoC 跑团实现把人物卡视为可复用的 **Identity**，而不是某个模组 Session 里的临时 actor JSON。

## 状态边界

| 状态 | 唯一权威来源 | 生命周期 |
|---|---|---|
| 姓名、职业、特征、HP、SAN、MP、Luck、技能、状态 | `identity/<card>/id.json` 的 `game_profiles.coc7` | 跨模组、跨 Session |
| 随身物品与弹药/次数 | 同一人物卡的 `game_profiles.coc7.equipment` | 跨模组、跨 Session |
| 可使用的物品能力 | `identity/<card>/ego/skills/coc_use_<item>` | 随装备获得/失去同步安装或移除 |
| 地点、线索、地面物品、NPC/怪物、回合与剧情事件 | Harness Session 的 `coc_state` | 仅当前模组 |
| 性格与行为倾向 | Identity 的 `personality`、`description`、EGO、SEGO | KP 无权修改 |

人物卡因此可以在 `coc_lightless_beacon`、`coc_the_haunting` 或之后的模组之间反复绑定；地点不会错误地跟着人物卡跨模组，但受伤、理智、成长和装备会保留。

## KP 如何修改人物卡

KP 不是直接编辑文件。每回合经过以下可视化节点：

1. `normalize_actions`：弱模型只负责把三名玩家的自然语言提取为候选 JSON。
2. `enforce_player_intent`：确定性地重建人类玩家的动词；若模型把“开枪”擅自改成“等待”，会记录 `model_rewrite_detected`，裁决仍使用玩家原话。
3. `adjudicate`：根据人物卡、地点与规则生成世界事务和人物卡事务，不产生副作用。
4. `commit_round`：先验证世界 schema 和全部人物卡 revision，再批量提交人物卡；失败会回滚人物卡与物品 Tool。
5. `refresh_public_view`：从磁盘重新载入人物卡，绑定 Agent 热重载后立即看到新数值与 Tool。
6. `kp_narrates`：只叙述确定性裁决；被拒绝的行动不能写成成功。

KP 事务仅允许：

- 修改 `derived.hp/san/mp/luck/alive/conscious`；
- 添加或移除 condition、追加 note；
- 修改已拥有物品的 `ammo/charges/quantity/shots/uses`；
- 从受信物品目录 grant/remove item。

KP 不能借人物卡事务修改 personality、prompt、LLM、SEGO、任意技能代码或物品定义。所有修改带 optimistic revision；同一回合的全部事务会先验证后写入，写入失败会恢复备份。

## Studio 使用方法

1. 打开 `http://127.0.0.1:8765/`。
2. 首页选择 **人物卡与开团**，或在 **More → CoC Table** 打开人物卡工作台。
3. 填写 Identity ID、角色名、职业、HP/SAN/Luck 和初始装备，保存人物卡。
4. 打开一个模组。在 Build 右侧 Slots 中把人物卡绑定到：
   - `人类调查员`：只校验玩家本人声明的动作，模型不会替玩家决定；
   - `调查员A` / `调查员B`：由对应 Identity 的性格与人物卡驱动 AI 玩家；
   - `KP` 与 `规则裁判` 使用系统 Identity。
5. 点击执行。DAG 会在 `human_turn` 等待输入；运行观测面板可查看每个节点的输入、模型输出、玩家意图锁、骰点、事务与 revision。

物品 Tool 只产生“使用物品”的行动提案，不能绕过 KP 自行扣弹、造成伤害或改人物卡。

## 已验证的真实运行

使用已配置的 `deepseek-v4-flash`，通过 Studio/Void 相同的 `/api/execution/*` 路径运行：

- 9 回合剧情推进：海岸开场 → 丢枪/捡枪 → 调查岸边 → 到达灯塔 → 进入起居室 → 发现无线电被人为破坏 → 登塔 → 发现透镜机构被铁钎蓄意卡死；同时另一名调查员在油料间发现异常人形轮廓。
- 人物卡事务：人类卡的左轮 Tool 在丢枪时移除，捡枪时恢复；弹药保持 6；personality 未改变。
- 反作弊复跑：模型再次把玩家的“用已丢的枪开枪”改写成 `wait`，`enforce_player_intent` 检出改写并恢复为 `firearm_attack`，确定性裁决返回 `firearm_not_carried_in_identity`，KP 明确叙述没有开枪；下一回合捡枪后 Tool 与 6 发弹药恢复。

本地完整轨迹保存在 `.runtime/coc_identity_live_*.json`，正式 Session 也保存在 `sessions/coc_lightless_beacon_*`。可重复运行：

```powershell
python scripts/test_live_coc_identity.py
python scripts/test_live_coc_identity.py --intent-guard-smoke
python -m unittest discover -s tests -p test_coc7_runtime.py -v
```

这些场景适配器只保存结构化摘要和官方来源链接，不复制受版权保护的完整模组文本；完整叙事、手册与 handout 仍需使用 Chaosium 官方免费材料。
