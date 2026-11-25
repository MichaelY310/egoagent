const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.join(__dirname, '../void_extension/egoagent-dag-chat');
const extension = fs.readFileSync(path.join(root, 'extension-v21.js'), 'utf8');
const chat = fs.readFileSync(path.join(root, 'media/chat.js'), 'utf8');

function load(source, name, context, indent = '') {
  let start = source.indexOf(`${indent}async function ${name}(`);
  if (start < 0) start = source.indexOf(`${indent}function ${name}(`);
  assert.ok(start >= 0, name);
  vm.runInContext(source.slice(start, source.indexOf(`\n${indent}}`, start) + indent.length + 2), context);
}

test('folder context is available with Build/Identity open and no text editor', async () => {
  for (const [uriPath, expected] of [['/C:/demo', 'C:/demo'], ['/home/user/demo', '/home/user/demo']]) {
    const c = vm.createContext({ vscode: { window: {}, workspace: { workspaceFolders: [{ uri: { path: uriPath, toString: () => uriPath } }] } } });
    load(extension, 'fsPathForBackend', c);
    load(extension, 'captureEditorContext', c);
    assert.equal((await c.captureEditorContext()).workspacePath, expected);
  }
});

test('empty windows never invent a backend/repository default workspace', async () => {
  const c = vm.createContext({ vscode: { window: {}, workspace: {} } });
  load(extension, 'fsPathForBackend', c);
  load(extension, 'captureEditorContext', c);
  assert.equal((await c.captureEditorContext()).workspacePath, '');
});

test('submission captures the file and folder without calling slow language providers', async () => {
  const uri = { path: '/C:/demo/main.py', toString: () => 'file:///C:/demo/main.py' };
  const folder = { uri: { path: '/C:/demo', toString: () => 'file:///C:/demo' } };
  const c = vm.createContext({
    displayPath: () => 'main.py', extractLocalSymbols: () => [],
    selectionLineRange: () => ({ startLine: 1, endLine: 1, lineCount: 0 }),
    vscode: {
      window: { activeTextEditor: { document: { uri, lineCount: 1, languageId: 'python', version: 1,
        getText: () => 'print(1)', positionAt: () => ({ line: 0, character: 8 }) },
        selection: { active: { line: 0, character: 0 }, isEmpty: true } } },
      workspace: { workspaceFolders: [folder], getWorkspaceFolder: () => folder },
      commands: { executeCommand: () => { throw Error('must not query LSP during submission'); } },
      languages: { getDiagnostics: () => [] }, Range: class {}, Position: class {},
    },
  });
  load(extension, 'fsPathForBackend', c);
  load(extension, 'captureEditorContext', c);
  const result = await c.captureEditorContext({ includeLanguageFeatures: false });
  assert.equal(result.workspacePath, 'C:/demo');
  assert.equal(result.fileExcerpt, 'print(1)');
  assert.equal(result.definitions.length, 0);
});

function submission(workspacePath) {
  const events = [];
  const controls = new Map();
  const state = { pendingContextPastes: new Map(), pastedContexts: [], editorContext: { workspacePath }, messages: [] };
  const c = vm.createContext({ state, $: id => {
    if (!controls.has(id)) controls.set(id, { disabled: false, focus() {} });
    return controls.get(id);
  }, composerText: () => '你好', casualTurnText: () => '你好', canonicalWorkspace: value => value || '',
  requestFreshEditorContext: async () => state.editorContext,
  clearComposer: () => events.push('clear'), addMessage: () => events.push('message'),
  addEvent: () => events.push('error'), toast: () => events.push('hint'),
  renderWorkspace() {}, setAgentActivity() {}, currentProgressBubble() {}, renderMessagesNow() {},
  agentConfigSnapshot: () => ({}), renderContextPlan() {}, renderEditorContext() {}, pollExecution() {},
  startExecution: async () => { events.push('start'); return { initial_input_seeded: true }; },
  });
  load(chat, 'sendPrompt', c, '  ');
  return { c, events, state, controls };
}

test('missing workspace keeps draft and attachments, without posting a failed turn', async () => {
  const { c, events, state, controls } = submission('');
  state.pastedContexts.push({ content: 'keep me' });
  await c.sendPrompt();
  assert.deepEqual(events, ['hint']);
  assert.equal(state.pastedContexts.length, 1);
  assert.equal(state.submitting, false);
  assert.equal(controls.get('send').disabled, false);
});

test('valid workspace submits once even without an open source file', async () => {
  const { c, events } = submission('C:/demo');
  await c.sendPrompt();
  assert.deepEqual(events, ['clear', 'message', 'start']);
});

test('fresh submission context bypasses language services and open project is wired to native command', () => {
  assert.ok(extension.includes('captureEditorContext({ includeLanguageFeatures: !requestId })'));
  assert.ok(extension.includes("message.type === 'openProjectFolder'"));
  assert.ok(extension.includes("executeCommand('workbench.action.files.openFolder')"));
  assert.ok(chat.includes("postMessage({ type: 'openProjectFolder' })"));
});
