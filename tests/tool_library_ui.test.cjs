const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('../harness_editor/node_modules/typescript');
const React = require('../harness_editor/node_modules/react');
const jsx = require('../harness_editor/node_modules/react/jsx-runtime');
const { renderToStaticMarkup } = require('../harness_editor/node_modules/react-dom/server');

const items = [
  { id: 'one', ref: 'repo:capability_packs/read/skills/read', name: 'read_file', type: 'tool', source: '公共能力包 · read', description: 'Read a file', usable: true, entry_file: 'C:/repo/read_file.py', files: [{ name: 'scripts/read_file.py', path: 'C:/repo/read_file.py' }], parameters: {}, usage_count: 1 },
  { id: 'two', ref: 'repo:identity/coder/ego/skills/read', name: 'read_file', type: 'tool', source: 'Identity · coder', description: 'Other source', usable: true, entry_file: 'C:/repo/other.py', files: [], parameters: {}, usage_count: 0 },
  { id: 'three', ref: 'workspace:.agents/skills/review', name: 'review', type: 'skill', source: '当前项目', description: 'Review instructions', usable: true, entry_file: 'C:/project/SKILL.md', files: [], parameters: {}, usage_count: 0 },
];

function mount(options = {}) {
  const hooks = [], effects = [], calls = { edits: [], saves: [], saved: [] };
  let index = 0;
  const next = initial => { const i = index++; if (!(i in hooks)) hooks[i] = typeof initial === 'function' ? initial() : initial; return i; };
  const context = { exports: {}, window: { confirm: () => true }, require(name) {
    if (name === 'react') return { ...React,
      useState(initial) { const i = next(initial); return [hooks[i], value => { hooks[i] = typeof value === 'function' ? value(hooks[i]) : value; }]; },
      useRef(initial) { return hooks[next(() => ({ current: initial }))]; },
      useMemo(fn) { return fn(); },
      useEffect(fn, deps) { const i = index++; const key = JSON.stringify(deps); if (hooks[i] !== key) { hooks[i] = key; effects.push(fn); } },
    };
    if (name === 'react/jsx-runtime') return jsx;
    if (name === './ToolLibrary.css') return {};
    if (name === '../ideBridge') return { editCapabilityFileInIde: async path => { calls.edits.push(path); if (options.editError) throw Error(options.editError); } };
    if (name === '../api/client') return {
      listToolLibrary: async () => ({ items }), listIdentities: async () => ['reader'],
      readIdentityCapabilities: async () => ({ identity: 'reader', selection: options.selection ?? null, defaults: [items[0].ref], revision: 'revision1' }),
      saveIdentityCapabilities: async (identity, selection, revision) => { calls.saves.push({ identity, selection, revision }); if (options.saveError) throw Error(options.saveError); return { identity, selection, defaults: [], revision: 'revision2' }; },
    };
    throw Error(name);
  } };
  const source = fs.readFileSync('harness_editor/src/components/ToolLibrary.tsx', 'utf8');
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 } }).outputText, context);
  const render = () => { index = 0; return context.exports.default({ identity: options.identity === undefined ? 'reader' : options.identity, onSaved: value => calls.saved.push(value) }); };
  return { render, calls, async settle() { render(); while (effects.length) effects.shift()(); await new Promise(setImmediate); return render(); } };
}
function find(node, predicate) {
  if (!node || typeof node !== 'object') return;
  if (predicate(node)) return node;
  for (const child of React.Children.toArray(node.props?.children)) { const result = find(child, predicate); if (result) return result; }
}
const button = (tree, name) => find(tree, node => node.type === 'button' && node.props.children === name);
const label = (tree, name) => find(tree, node => node.props?.['aria-label'] === name);

test('default Identity view exposes inherited checked source; editing opens its real file', async () => {
  const view = mount(); const tree = await view.settle();
  assert.ok(renderToStaticMarkup(tree).includes('公共能力包 · read'));
  const checked = label(tree, '使用 read_file · 公共能力包 · read');
  assert.equal(checked.props.checked, true); assert.equal(checked.props.disabled, true);
  button(tree, '编辑').props.onClick(); await new Promise(setImmediate);
  assert.deepEqual(view.calls.edits, ['C:/repo/read_file.py']);
});
test('explicit empty selection persists, and save callback updates the parent Identity form', async () => {
  const view = mount(); let tree = await view.settle();
  label(tree, '能力加载方式').props.onChange({ target: { value: 'custom' } });
  tree = view.render();
  label(tree, '使用 read_file · 公共能力包 · read').props.onChange({ target: { checked: false } });
  tree = view.render(); button(tree, '保存能力选择').props.onClick(); await new Promise(setImmediate);
  assert.deepEqual(JSON.parse(JSON.stringify(view.calls.saves)), [{ identity: 'reader', selection: { version: 1, tools: [] }, revision: 'revision1' }]);
  assert.equal(view.calls.saved.length, 1);
  assert.match(renderToStaticMarkup(view.render()), /新建 Session/);
});
test('same-name source conflicts explain which selection must be removed', async () => {
  const view = mount({ selection: { version: 1, tools: [items[0].ref] } });
  let tree = await view.settle();
  label(tree, '使用 read_file · Identity · coder').props.onChange({ target: { checked: true } });
  tree = view.render();
  assert.match(renderToStaticMarkup(tree), /同名能力 read_file/);
  assert.equal(label(tree, '使用 read_file · Identity · coder').props.checked, false);
});
test('search/type filter preserves selections and distinguishes SKILL.md from Python tools', async () => {
  const view = mount({ selection: { version: 1, tools: [items[0].ref] } });
  let tree = await view.settle();
  label(tree, '能力类型').props.onChange({ target: { value: 'skill' } });
  tree = view.render();
  assert.ok(label(tree, '使用 review · 当前项目'));
  assert.equal(label(tree, '使用 read_file · 公共能力包 · read'), undefined);
  label(tree, '能力类型').props.onChange({ target: { value: 'all' } });
  assert.equal(label(view.render(), '使用 read_file · 公共能力包 · read').props.checked, true);
});
test('IDE open failure is visible instead of silently claiming success', async () => {
  const view = mount({ editError: 'File does not exist' });
  const tree = await view.settle(); button(tree, '编辑').props.onClick(); await new Promise(setImmediate);
  assert.match(renderToStaticMarkup(view.render()), /File does not exist/);
});

test('opening source cannot discard unsaved capability selections', async () => {
  const view = mount(); let tree = await view.settle();
  label(tree, '能力加载方式').props.onChange({ target: { value: 'custom' } });
  tree = view.render(); button(tree, '编辑').props.onClick(); await new Promise(setImmediate);
  assert.deepEqual(view.calls.edits, []);
  assert.match(renderToStaticMarkup(view.render()), /还有未保存的能力选择/);
  button(view.render(), '撤销未保存选择').props.onClick();
  button(view.render(), '编辑').props.onClick(); await new Promise(setImmediate);
  assert.deepEqual(view.calls.edits, ['C:/repo/read_file.py']);
});

test('failed save retains selection and does not update the parent', async () => {
  const view = mount({ saveError: 'Identity was modified in another window' });
  let tree = await view.settle();
  label(tree, '能力加载方式').props.onChange({ target: { value: 'custom' } });
  tree = view.render(); button(tree, '保存能力选择').props.onClick(); await new Promise(setImmediate);
  assert.match(renderToStaticMarkup(view.render()), /Identity was modified in another window/);
  assert.equal(view.calls.saved.length, 0);
  assert.equal(label(view.render(), '能力加载方式').props.value, 'custom');
});
test('new Tools tab is primary and survives IDE route restore', () => {
  const app = fs.readFileSync('harness_editor/src/App.tsx', 'utf8');
  assert.match(app, /id: 'tools'.*group: 'primary'/);
  const extension = fs.readFileSync('void_extension/egoagent-dag-chat/extension-v21.js', 'utf8');
  assert.match(extension, /WORKBENCH_TABS = new Set\([^\n]*'tools'/);
  assert.match(extension, /message.type === 'open-file'[\s\S]*?request-result/);
});
