const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('../harness_editor/node_modules/typescript');
const React = require('../harness_editor/node_modules/react');
const jsx = require('../harness_editor/node_modules/react/jsx-runtime');
const { renderToStaticMarkup } = require('../harness_editor/node_modules/react-dom/server');

function editor(id, tab = 'id', superego = {}) {
  const state = [[], id.name || 'minimal', id, superego, [], [], tab];
  let cursor = 0;
  let saved;
  const context = { exports: {}, require: name => {
    if (name === 'react') return { ...React, useEffect() {}, useCallback: fn => fn,
      useRef: () => ({ current: 0 }), useState: initial => {
        const index = cursor++;
        if (!(index in state)) state[index] = typeof initial === 'function' ? initial() : initial;
        return [state[index], value => { state[index] = typeof value === 'function' ? value(state[index]) : value; }];
      } };
    if (name === 'react/jsx-runtime') return jsx;
    if (name === '../api/client') return { listIdentities: async () => [], saveIdentity: async (name, data) => { saved = { name, data }; } };
    if (name === './ToolLibrary') return { default: () => null, __esModule: true };
    throw Error(name);
  } };
  const source = fs.readFileSync(path.join(__dirname, '../harness_editor/src/components/IdentityManager.tsx'), 'utf8');
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022,
  } }).outputText, context);
  return { render() { cursor = 0; return context.exports.default(); }, saved: () => saved };
}

function find(node, predicate) {
  if (!node || typeof node !== 'object') return undefined;
  if (predicate(node)) return node;
  for (const child of React.Children.toArray(node.props?.children)) {
    const match = find(child, predicate);
    if (match) return match;
  }
}

test('all checked-in Identity ID forms render, including partial cookbook personalities', () => {
  let count = 0;
  const dir = path.join(__dirname, '../identity');
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const file = path.join(dir, entry.name, 'id.json');
    if (!entry.isDirectory() || !fs.existsSync(file)) continue;
    const id = JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, ''));
    assert.doesNotThrow(() => renderToStaticMarkup(editor(id).render()), entry.name);
    count++;
  }
  assert.ok(count >= 30);
});

test('missing/null optional sections and legacy string lists do not crash', () => {
  for (const id of [{ name: 'minimal' }, { name: 'null', personality: null, llm: null },
    { name: 'legacy', personality: { traits: 'concise, patient' }, llm: {} }]) {
    assert.doesNotThrow(() => renderToStaticMarkup(editor(id).render()));
  }
  assert.doesNotThrow(() => renderToStaticMarkup(editor({ name: 'legacy' }, 'superego', {
    tool_access: { whitelist: 'read_file', blacklist: null }, knowledge_access: {},
  }).render()));
});

test('editing a role preserves absent model settings and unknown Identity fields', async () => {
  const original = { name: 'partial', personality: { language: '中文' }, ego_inherits: ['@pack/filesystem_readonly'], custom: { keep: 1 } };
  const c = editor(original);
  find(c.render(), node => node.props?.label === '角色 (role)').props.onChange('new role');
  const tree = c.render();
  const save = find(tree, node => node.type === 'button' && String(node.props.children).includes('保存 id.json'));
  await save.props.onClick();
  assert.deepEqual(JSON.parse(JSON.stringify(c.saved())), { name: 'partial', data: { ...original, role: 'new role' } });
});
