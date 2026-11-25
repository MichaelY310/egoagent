const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('../harness_editor/node_modules/typescript');

const root = 'void_extension/egoagent-dag-chat';
const extension = fs.readFileSync(`${root}/extension-v21.js`, 'utf8');
const canonical = value => String(value || '').replaceAll('\\', '/').replace(/^\/([A-Za-z]:\/)/, '$1').replace(/\/+$/, '').replace(/^[A-Za-z]:.*/, x => x.toLowerCase());

function client({ workspace = 'C:/demo', native, bootstrap, local = new Map(), blocked = false } = {}) {
  let state = native;
  const posted = [];
  const modules = {};
  const context = vm.createContext({
    window: {
      __EGOAGENT_WORKBENCH__: { workbenchSession: bootstrap },
      localStorage: {
        getItem: key => { if (blocked) throw Error('blocked'); return local.get(key); },
        setItem: (key, value) => { if (blocked) throw Error('quota'); local.set(key, value); },
      },
      addEventListener() {}, dispatchEvent() {},
    },
    acquireVsCodeApi: () => ({ getState: () => state, setState: next => { state = next; }, postMessage: message => posted.push(message) }),
    require: name => name === './api/runtime' ? { WORKSPACE: workspace, canonicalWorkspace: canonical } : modules[name],
    Date, Map, JSON,
  });
  for (const name of ['ideBridge', 'workbenchSession']) {
    context.exports = {};
    const source = fs.readFileSync(`harness_editor/src/${name}.ts`, 'utf8');
    vm.runInContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, context);
    modules[`./${name}`] = context.exports;
  }
  return { api: modules['./workbenchSession'], native: () => state, posted, local };
}

const draft = {
  config: { name: 'unsaved', slots: { agent: { identity: 'coder' } }, pipeline: { start: 'input', nodes: { input: { op: 'wait_input', edges: [] } } } },
  positions: { input: { x: 123, y: 456 } }, harnessVersion: 'v1',
  viewport: { x: 30, y: 50, zoom: 0.6 }, selectedNodeId: 'input', showInspector: true, locked: true,
};
const plain = value => JSON.parse(JSON.stringify(value));

test('Build panels default open and migrate the old embedded collapsed defaults', () => {
  const { api } = client();
  assert.deepEqual(plain(api.builderPanelVisibility()), { palette: true, inspector: true });
  assert.deepEqual(plain(api.builderPanelVisibility({ ...draft, showPalette: false, showInspector: false })),
    { palette: true, inspector: true });
});

test('explicit panel choices survive refresh after the default-layout migration', () => {
  const first = client();
  first.api.updateWorkbenchSession({ builder: { ...draft, panelLayoutVersion: 1, showPalette: false, showInspector: true } });
  const second = client({ native: first.native() });
  assert.deepEqual(plain(second.api.builderPanelVisibility(second.api.loadWorkbenchSession().builder)),
    { palette: false, inspector: true });
  assert.deepEqual(plain(second.api.builderPanelVisibility({ ...draft, panelLayoutVersion: 1, showInspector: false })),
    { palette: true, inspector: false });
});

test('refresh restores route and unsaved draft without relying on the old webview origin', () => {
  const first = client();
  first.api.updateWorkbenchSession({ route: 'harness', builder: draft });
  const second = client({ native: first.native() });
  assert.equal(second.api.hasRestoredIdeSession(), true);
  assert.equal(second.api.loadWorkbenchSession().route, 'harness');
  assert.deepEqual(plain(second.api.loadWorkbenchSession().builder), draft);
  assert.equal(first.posted.at(-1).type, 'session-state');
});

test('host workspace backup restores a manually reopened panel', () => {
  const first = client();
  first.api.updateWorkbenchSession({ route: 'identity', builder: draft });
  const second = client({ bootstrap: first.posted.at(-1).session });
  assert.equal(second.api.hasRestoredIdeSession(), false); // explicit navigation still wins
  assert.equal(second.api.loadWorkbenchSession().route, 'identity');
  assert.deepEqual(plain(second.api.loadWorkbenchSession().builder), draft);
});

test('patches preserve builder, evaluation and observation independently', () => {
  const c = client();
  c.api.updateWorkbenchSession({ builder: draft, evaluation: { taskId: 'task1' } });
  c.api.updateWorkbenchSession({ route: 'observe', observation: { linkedRunId: 'exact-run' } });
  c.api.updateWorkbenchSession({ builder: { showOutput: true } });
  const session = c.api.loadWorkbenchSession();
  assert.equal(session.builder.config.name, 'unsaved');
  assert.equal(session.builder.showOutput, true);
  assert.equal(session.evaluation.taskId, 'task1');
  assert.equal(session.observation.linkedRunId, 'exact-run');
});

test('state never leaks from another workspace and Windows paths are normalized', () => {
  const a = client();
  a.api.updateWorkbenchSession({ builder: draft, route: 'harness' });
  const b = client({ workspace: '/home/user/project', native: a.native(), bootstrap: a.native().workbenchSession });
  assert.equal(b.api.loadWorkbenchSession().builder, undefined);
  const same = client({ workspace: '/C:/DEMO/', native: a.native() });
  assert.equal(same.api.loadWorkbenchSession().builder.config.name, 'unsaved');
});

test('blocked localStorage and corrupt/old state do not prevent IDE persistence', () => {
  const c = client({ blocked: true, native: { workbenchSession: { version: 999, workspace: 'C:/demo' } } });
  assert.equal(c.api.loadWorkbenchSession().builder, undefined);
  c.api.updateWorkbenchSession({ builder: draft });
  assert.deepEqual(plain(c.api.loadWorkbenchSession().builder), draft);
});

test('newest valid snapshot wins over stale bootstrapped state', () => {
  const c = client({
    native: { workbenchSession: { version: 1, workspace: 'C:/demo', route: 'identity', updatedAt: 20 } },
    bootstrap: { version: 1, workspace: 'C:/demo', route: 'home', updatedAt: 10 },
  });
  assert.equal(c.api.loadWorkbenchSession().route, 'identity');
});

function host(backup) {
  const storage = new Map(backup ? [['egoagent.workbench.route:C:/demo:session', backup]] : []);
  let receive, dispose;
  const panel = {
    title: '',
    webview: { cspSource: 'test', asWebviewUri: value => value, onDidReceiveMessage: fn => { receive = fn; } },
    onDidDispose: fn => { dispose = fn; },
  };
  const context = vm.createContext({
    vscode: {
      workspace: { workspaceFolders: [{ uri: 'C:/demo' }], fs: { readFile: async () => Buffer.from('<html><head></head></html>') } },
      Uri: { joinPath: (...parts) => parts.join('/') },
      window: { createWebviewPanel: () => { throw Error('must reuse restored panel'); } },
    },
    remoteWorkspaces: { backendUrl: () => 'http://localhost:8875', webSocketUrl: () => 'ws://localhost:8876' },
    normalizedFsPath: value => value, fsPathForBackend: value => value || '',
    testContext: { extensionUri: 'extension', workspaceState: { get: (key, fallback) => storage.get(key) ?? fallback, update: async (key, value) => storage.set(key, value) } },
    TextDecoder, URL, console, escapeHtml: value => value,
  });
  vm.runInContext(extension.slice(extension.indexOf('let workbenchPanel;'), extension.indexOf('async function openCodeMap()')) + '\nworkbenchContext = testContext;', context);
  return { context, panel, storage, receive: msg => receive(msg), dispose: () => dispose() };
}

test('serializer revives the supplied editor and wires its navigation and state handlers', async () => {
  const session = { version: 1, workspace: 'C:/demo', route: 'identity', builder: draft };
  const h = host();
  await h.context.restoreWorkbenchPanel(h.panel, { workbenchSession: session });
  assert.equal(h.panel.title, 'EgoAgent · Identity');
  assert.equal(h.panel.webview.options.enableScripts, true);
  assert.ok(h.panel.webview.html.includes('"workbenchSession":'));
  await h.receive({ source: 'egoagent-workbench', type: 'route-change', tab: 'observe' });
  assert.equal(h.panel.title, 'EgoAgent · 运行相簿');
  await h.receive({ source: 'egoagent-workbench', type: 'session-state', session });
  assert.equal(h.storage.get('egoagent.workbench.route:C:/demo:session'), session);
  await h.receive({ source: 'egoagent-workbench', type: 'session-state', session: { ...session, workspace: '/other' } });
  assert.equal(h.storage.get('egoagent.workbench.route:C:/demo:session'), session);
  h.dispose();
  assert.equal(vm.runInContext('workbenchPanel', h.context), undefined);
});

test('serializer can use a workspace backup when browser state is missing', async () => {
  const h = host({ version: 1, workspace: 'C:/demo', route: 'harness', builder: draft });
  await h.context.restoreWorkbenchPanel(h.panel, undefined);
  assert.equal(h.panel.title, 'EgoAgent · Build');
  assert.ok(h.panel.webview.html.includes('"name":"unsaved"'));
});

test('extension declares reload activation and registers a native serializer', () => {
  const manifest = JSON.parse(fs.readFileSync(`${root}/package.json`, 'utf8'));
  assert.ok(manifest.activationEvents.includes('onWebviewPanel:egoagent.workbench'));
  assert.match(extension, /registerWebviewPanelSerializer\('egoagent\.workbench'/);
  const app = fs.readFileSync('harness_editor/src/App.tsx', 'utf8');
  assert.match(app, /initialEditHandled = useRef\(restoredView.native\)/);
  assert.match(app, /window.addEventListener\('pagehide', flushDraft\)/);
  assert.match(app, /fitView=\{!viewport\}/);
});
