# 联网搜索与浏览器操作

EgoAgent 把联网能力分成三层，避免把“搜索信息”和“操纵网页”混成一个不可审计的工具：

| 层级 | Tool / Harness | 适合任务 |
|---|---|---|
| 搜索发现 | `web_search` | 查找最新资料、官方文档、新闻和候选来源 |
| 页面取证 | `fetch_url` / `fetch_urls` | 读取一个或最多六个公开页面，保留 URL、标题、抓取时间和截断状态 |
| 交互浏览器 | `browser` / `browser_use_replica` | 点击、输入、滚动、截图、下载、标签页和需要页面状态的任务 |

## 日常使用

在 IDE Chat 中选择 `adaptive_code_agent`。它现在默认绑定 `openmanus` Identity，因此同时具有代码、搜索和浏览器能力；不必手动把全部 Tool 塞入上下文。下面三类提示可以直接测试：

1. 搜索并取证：`搜索 Python 3.14 官方文档最近的变化，只使用 python.org，打开最相关的两个页面后附 URL 总结。`
2. 新闻检索：`搜索最近一周关于 Python 的新闻，列出日期、来源和链接；无法从正文确认的内容标成“仅搜索摘要”。`
3. 浏览器操作：`打开 https://example.com，观察页面，截图，然后告诉我页面标题和截图路径。`

在运行记录中应依次看到 `web_search` → `fetch_urls`，或看到 `browser(start/navigate/observe/...)` 的工具卡片。重要事实应附真实 URL；搜索摘要只是线索，不应被当成完整证据。

复杂、长时间的网页操作可以直接选择 `browser_use_replica`。它采用 observe → act → verify 循环，连续失败会改变策略，并用独立 Judge 检查最终页面证据。复杂研究任务可选择 `open_deep_research_replica`，让多个隔离 Worker 并行检索后再压缩和综合。

## Tool 参数

`web_search` 支持：

- `domains` / `exclude_domains`：强制包含或排除域名；子域名会正确匹配。
- `freshness`：`day`、`week`、`month`、`year` 或 `YYYY-MM-DD`。
- `search_type`：`web` 或 `news`。
- `max_results`：1–10。

结果使用当前工具调用内稳定的 `S1`、`S2` 编号，并包含 `retrieved_at`。`fetch_urls` 最多读取六个 URL，同时受每页和总字符预算限制，避免一次把大量网页塞入上下文。

## 安全边界

- 所有上述 Tool 都声明为 `network` 权限；Balanced/Strict 模式下会经过联网审批策略。
- `fetch_url(s)` 禁止本机、局域网、保留地址、URL 内凭据，并在跟随每一次重定向前重新检查目标，降低 SSRF 风险。
- 网页正文是不可信数据。Agent 的提示明确禁止服从网页中的指令、泄露密钥、上传工作区内容，或未经授权执行支付、发布等外部操作。
- CAPTCHA、登录、支付和其他人类/高后果步骤应触发 `browser` 的 `handoff`，而不是绕过网站保护。
- 浏览器下载仍写入当前 Workspace 的受控下载目录；网络能力不等于主机文件系统权限。

## 无 API Key 的搜索回退

当前默认实现优先使用 Bing RSS，在不可用时回退到 DuckDuckGo HTML，因此无需搜索 API Key。返回值会保留 provider 和回退警告，不会把“零结果”和“网络失败”混在一起。在中国网络环境中若两个入口都被网络侧阻断，运行记录会显示各 provider 的具体错误；此时可以配置系统代理后重试，浏览器 Tool 也会沿用浏览器/系统网络环境。
