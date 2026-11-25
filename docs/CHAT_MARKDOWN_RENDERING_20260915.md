# Chat Markdown 渲染修复（2026-09-15）

## 问题与范围

FastVideo 调试配置回复的原始历史消息包含有效的 Markdown 表格，但旧 Chat 正则渲染器没有表格解析功能。这是显示层缺失，不需要更换模型或改写模型提示词。

Chat 现在通过统一的 `media/markdown.js` 适配器，使用随扩展打包的 [markdown-it 15.0.2](https://github.com/markdown-it/markdown-it)。实时回复和重新打开的历史回复使用同一实现，不依赖 CDN。

支持表格、表格列对齐、标题、嵌套列表、引用、分隔线、加粗、斜体、删除线、行内代码、围栏代码块和 HTTP(S) 链接。宽表格在自己的区域内横向滚动；样式使用 IDE 主题变量。公式、Mermaid 和代码语法着色不在本次新增范围。

## 用户如何生效

1. 在 EgoAgent IDE 中按 `Ctrl+Shift+P`。
2. 选择 `Developer: Reload Window`（开发人员：重新加载窗口）。网页版也可以刷新页面。
3. 重新打开原来的 Session。已有回复直接重新渲染，不需要再次发送问题，也不产生模型 API 费用。

2026-09-15 已同步到本机 Void 扩展，以及当时正在使用的四个 Ubuntu WSL 连接的运行扩展和应用源目录。无需重启后端。其他既有 SSH 安装需要正常更新其扩展才能获得本次修改。

## 数据与安全边界

- 不修改保存的消息或模型输入输出，不影响 Flow、Identity、回放和训练导出。
- 原始 HTML 当作文字，不执行模型提供的脚本、事件处理器或 iframe。
- Markdown 链接只接受 HTTP(S)，拒绝 `javascript:`、`command:`、`file:` 和 `data:` 等方案。
- 外部链接隔离 opener；模型生成的图片地址显示为可点击链接，不自动请求远程图片。用户上传附件仍由独立附件渲染器处理。
- 表格对齐使用固定 CSS 类，不放宽 Webview CSP。
- 缓存限制为 96 条、最多约 2M 字符的源文本与 HTML；流式变化会重新解析，旧回复复用缓存。
- 上游版本、许可证和更新方法见扩展 `media/vendor/README.md`。

## 验证

```powershell
node --test tests/chat_markdown.test.cjs tests/chat_approval_mode.test.cjs tests/chat_progress.test.cjs tests/chat_delivery.test.cjs tests/workspace_window.test.cjs
```

结果：37/37 通过，其中 16 项为新增 Markdown 回归测试，覆盖表格、嵌套结构、转义、流式未闭合代码块、恶意 HTML/URL、安全图片策略、缓存和浏览器包加载。

实际前端验证：在 WSL FastVideo 项目的原 Session 中打开用户之前的真实回复，DOM 中出现 4 列、4 条数据行的表格，截图确认浅色主题下的表头、单元格、加粗与行内代码正常显示。还检查了窄面板的表格独立横向溢出。没有为了测试重新调用模型；深色主题使用主题变量，但本次没有单独做深色截图验证。
