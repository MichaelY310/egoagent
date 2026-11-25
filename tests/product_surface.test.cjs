const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { createRequire } = require('node:module');
const ts = require('../harness_editor/node_modules/typescript');
const React = require('../harness_editor/node_modules/react');
const jsx = require('../harness_editor/node_modules/react/jsx-runtime');
const { renderToStaticMarkup } = require('../harness_editor/node_modules/react-dom/server');

function load(relative, mocks = {}) {
  const file = path.resolve(relative);
  const native = createRequire(file);
  const context = { exports: {}, require(name) { return Object.hasOwn(mocks, name) ? mocks[name] : native(name); } };
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
  }).outputText, context);
  return context.exports;
}
const features = load('harness_editor/src/productFeatures.ts');

test('main navigation rejects unreleased and restored experimental routes', () => {
  for (const route of ['tasks', 'evolution', 'research', 'ir', 'background', 'packages', 'coc', 'flow']) assert.equal(features.routeEnabled(route), false, route);
  for (const route of ['harness', 'identity', 'tools', 'sessions', 'observe', 'changes', 'settings']) assert.equal(features.routeEnabled(route), true, route);
  const source = fs.readFileSync('harness_editor/src/App.tsx', 'utf8');
  assert.match(source, /ALL_STUDIO_TABS.filter\(item => routeEnabled/);
  assert.match(source, /setTabState\(routeEnabled\(next\)/);
});

test('cookbook hides disabled stages and links while retaining core examples', () => {
  assert.equal(features.flowEnabled('cookbook_01_react'), true);
  for (const name of ['cookbook_10_durable', 'cookbook_22_flow_designer', 'arc_direct_baseline', 'aider_replica']) assert.equal(features.flowEnabled(name), false, name);
});

test('home renders product tasks, not experimental metrics or activation buttons', () => {
  const Home = load('harness_editor/src/components/StudioHome.tsx', {
    react: React, 'react/jsx-runtime': jsx, '../api/client': {}, '../api/runtime': { API_BASE: '' },
    '../productFeatures': features, './CookbookRecipe.css': {},
  }).default;
  const html = renderToStaticMarkup(React.createElement(Home, { onNavigate() {}, onOpenHarness() {} }));
  assert.match(html, /打开推荐代码助手/);
  assert.match(html, /运行相簿/);
  assert.doesNotMatch(html, /最近评测|从这次失败创建实验|CoC|<h2>Evaluate|<h2>Improve/);
});

test('new session cannot override Flow Identity or strategy', () => {
  const source = fs.readFileSync('harness_editor/src/components/SessionCreateDialog.tsx', 'utf8');
  assert.match(source, /flow_selection: \{ harness, version \}/);
  assert.doesNotMatch(source, /listIdentities|setIdentity|setMode|setBindings/);
});

test('identity factory is hidden when evolution is unreleased', () => {
  const source = fs.readFileSync('harness_editor/src/components/IdentityManager.tsx', 'utf8');
  assert.match(source, /featureEnabled\('evolution'\) && <div/);
});

test('native remote status and commands respect the release gate', () => {
  const source = fs.readFileSync('void_extension/egoagent-dag-chat/remote-workspaces.js', 'utf8');
  assert.match(source, /response.json\(\)\).remote === true/);
  assert.match(source, /if \(!runtime.id && !await remoteFeatureEnabled\(\)\)/);
  assert.match(source, /if \(enabled\) status.show\(\)/);
});

test('all Build headers participate in layout so wrapped controls cannot cover Run', () => {
  const css = fs.readFileSync('harness_editor/src/components/CookbookRecipe.css', 'utf8');
  assert.match(css, /\.flow-area > \.builder-context-bar \{ position: relative;/);
  assert.match(css, /\.flow-area > \.builder-canvas-stage \{ display: block; position: relative;/);
  assert.doesNotMatch(css, /\.builder-canvas-stage \{ display: contents;/);
});
