const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const { render } = require('../void_extension/egoagent-dag-chat/media/markdown.js');
const extensionRoot = path.resolve('void_extension/egoagent-dag-chat');

const debugTable = `## 4 个 debug 配置

| # | 名称 | 入口 | 干什么 |
|---|------|------|--------|
| 1 | \`FastVideo: 1 - tiny Wan training (CUDA)\` | \`scripts/debug/training_smoke.py\` | 用**随机权重的 2 层 tiny Wan DiT**走**真实的 \`Trainer\`**，运行 backward 和 AdamW。 |
| 2 | \`FastVideo: 2 - Triton kernel forward/backward\` | \`scripts/debug/triton_kernel_smoke.py\` | 对比 PyTorch 参考实现（\`atol/rtol=1e-2\`）。 |
| 3 | \`FastVideo: 3 - Trainer unit test\` | \`pytest -s -q fastvideo/tests/train/trainer/test_validation.py\` | 单步调试测试。 |
| 4 | \`FastVideo: 4 - fused kernel pytest\` | \`pytest -s -q fastvideo-kernel/tests/test_fused_compress_topk.py\` | 单步调试 kernel。 |

四个配置的共同点：

- **解释器**：\`/home/aa310/.venvs/fastvideo/bin/python\`
  - 原生 WSL 文件系统。
  - \`justMyCode: false\`。
`;

test('FastVideo regression: four real table rows, code and nested bold remain structured', () => {
  const html = render(debugTable);
  assert.match(html, /<h2>4 个 debug 配置<\/h2>/);
  assert.equal((html.match(/<th\b/g) || []).length, 4);
  assert.equal((html.match(/<td\b/g) || []).length, 16);
  assert.match(html, /<strong>真实的 <code>Trainer<\/code><\/strong>/);
  assert.match(html, /role="region".*aria-label="表格（可横向滚动）"/);
  assert.doesNotMatch(html, /\|---/);
});

test('aligned table cells use CSP-safe classes, never inline styles', () => {
  const html = render('| L | C | R |\n|:---|:---:|---:|\n| a | b | c |');
  for (const alignment of ['left', 'center', 'right']) assert.match(html, new RegExp(`class="align-${alignment}"`));
  assert.doesNotMatch(html, /style=/);
});

test('escaped pipes inside cells and code do not split extra columns', () => {
  const html = render('| a | b |\n|---|---|\n| one\\|two | `left\\|right` |');
  assert.equal((html.match(/<td\b/g) || []).length, 2);
  assert.match(html, /one\|two/);
  assert.match(html, /<code>left\|right<\/code>/);
});

test('nested lists, ordered start, multiline paragraphs, quotes, HR, strike and headings', () => {
  const html = render('##### Small title\n\n3. first\n   - nested **bold**\n   - another\n4. second\n\n> quote\n>\n> second paragraph\n\n---\n\n~~old~~ and *new*');
  assert.match(html, /<h5>Small title<\/h5>/);
  assert.match(html, /<ol start="3">/);
  assert.match(html, /<li>first\n<ul>/);
  assert.match(html, /<blockquote>[\s\S]*<p>quote<\/p>[\s\S]*second paragraph/);
  assert.match(html, /<hr>/);
  assert.match(html, /<s>old<\/s>/);
  assert.match(html, /<em>new<\/em>/);
});

test('fences, unfinished streaming fences, literal markup, code indentation', () => {
  const code = '```python\nif a < b:\n    print("**literal** | <script>")\n';
  const html = render(code);
  assert.match(html, /<pre><code class="language-python">/);
  assert.match(html, /if a &lt; b:\n    print/);
  assert.match(html, /\*\*literal\*\* \| &lt;script&gt;/);
  assert.doesNotMatch(html, /<strong>|<script>/);
  assert.equal(render(code + '```'), html);
  assert.match(render('~~~js\nconst a = 1;\n~~~'), /language-js/);
  assert.match(render('``code ` inside``'), /<code>code ` inside<\/code>/);
});

test('partial table stream becomes a table as soon as the delimiter arrives', () => {
  const pieces = ['| A | B |', '\n|---|---|', '\n| 1 | 2 |'];
  assert.doesNotMatch(render(pieces[0]), /<table>/);
  assert.match(render(pieces.slice(0,2).join('')), /<table>/);
  assert.match(render(pieces.join('')), /<td>2<\/td>/);
  for (let i = 0; i < debugTable.length; i += 19) assert.doesNotThrow(() => render(debugTable.slice(0, i)));
});

test('entities are decoded once in prose but preserved literally in code', () => {
  assert.match(render('x&#xA0;y &amp; z'), /x\u00a0y &amp; z/);
  assert.match(render('`&#xA0; &amp;`'), /<code>&amp;#xA0; &amp;amp;<\/code>/);
  assert.doesNotMatch(render('&#x3c;script&#x3e;alert(1)'), /<script>/);
});

test('literal backslashes, dollars and CRLF are not rewritten as model repair', () => {
  const source = String.raw`C:\Users\test\project and $HOME and @@EGO_INLINE_CODE_0@@`;
  assert.match(render(source), /C:\\Users\\test\\project and \$HOME and @@EGO_INLINE_CODE_0@@/);
  assert.equal(render(debugTable.replaceAll('\n', '\r\n')), render(debugTable));
  assert.doesNotMatch(render('\\| a \\| b \\|\n\\|---|---|\\'), /<table>/);
});

test('raw HTML, event handlers, SVG, script and iframe stay escaped', () => {
  const html = render('<script>alert(1)</script>\n<img src=x onerror="alert(1)">\n<svg/onload=alert(1)>\n<iframe srcdoc="evil"></iframe>');
  assert.doesNotMatch(html, /<(script|img|svg|iframe)\b/i);
  assert.match(html, /&lt;script&gt;/);
});

test('dangerous link schemes including encoded and mixed-case variants cannot become anchors', () => {
  for (const url of ['javascript:alert(1)', 'JaVaScRiPt:alert(1)', 'jav&#x61;script:alert(1)',
    'data:text/html;base64,PHNjcmlwdD4=', 'vbscript:evil', 'command:workbench.action.terminal.new',
    'file:///etc/passwd', '//tracker.example/a', '/api/execution/stop']) {
    assert.doesNotMatch(render(`[click](${url})`), /<a\b/, url);
  }
});

test('safe links preserve escaped query strings and are isolated from opener', () => {
  const html = render('[docs](https://example.com/path?a=1&b=2) and https://example.com/readme');
  assert.match(html, /href="https:\/\/example.com\/path\?a=1&amp;b=2"/);
  assert.doesNotMatch(html, /amp;amp/);
  assert.match(html, /target="_blank" rel="noopener noreferrer"/);
});

test('model-supplied remote images do not make automatic network requests', () => {
  const html = render('![preview](https://example.com/tracker.png) ![x](data:image/svg+xml,bad)');
  assert.doesNotMatch(html, /<img|<svg/i);
  assert.match(html, /class="markdown-image-link"/);
  assert.match(html, /🖼 preview/);
});

test('cache does not reuse stale streamed content; repeated large history stays responsive', () => {
  const large = debugTable.repeat(15);
  const expected = render(large);
  const started = performance.now();
  for (let i=0; i<1000; i++) assert.equal(render(large), expected);
  assert.ok(performance.now() - started < 2000);
  for (let i=0; i<110; i++) render(`answer ${i}`);
  assert.equal(render(large), expected);
  assert.notEqual(render('stream'), render('stream continues'));
});

test('browser UMD and Node test adapter produce identical output with no network', () => {
  const context = vm.createContext({atob});
  vm.runInContext(fs.readFileSync(path.join(extensionRoot, 'media/vendor/markdown-it.umd.min.js'), 'utf8'), context);
  vm.runInContext(fs.readFileSync(path.join(extensionRoot, 'media/markdown.js'), 'utf8'), context);
  assert.equal(context.EgoMarkdown.render(debugTable), render(debugTable));
});

test('Chat delegates to the shared renderer and safely exposes missing bundles', () => {
  const source = fs.readFileSync(path.join(extensionRoot, 'media/chat.js'), 'utf8');
  const start = source.indexOf('  function renderMarkdown(');
  const context = vm.createContext({EgoMarkdown: {render}, escapeHtml: value => String(value).replaceAll('<', '&lt;')});
  vm.runInContext(source.slice(start, source.indexOf('\n  }',start)+4), context);
  assert.equal(context.renderMarkdown(debugTable), render(debugTable));
  delete context.EgoMarkdown;
  assert.match(context.renderMarkdown('<script>'), /请重新加载窗口/);
  assert.doesNotMatch(context.renderMarkdown('<script>'), /<script>/);
});

test('webview loads local vendor and adapter before Chat; dependency is pinned and licensed', () => {
  const html = fs.readFileSync(path.join(extensionRoot, 'extension-v21.js'), 'utf8');
  assert.ok(html.indexOf('/vendor/markdown-it.umd.min.js?v=15.0.2') < html.indexOf('/markdown.js?v=1'));
  assert.ok(html.indexOf('/markdown.js?v=1') < html.indexOf('/chat.js?v='));
  assert.match(fs.readFileSync(path.join(extensionRoot,'media/vendor/markdown-it.LICENSE'),'utf8'), /Permission is hereby granted/);
});
