const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { createCompletionProvider, normalizeSuggestion, localWord, matchesGlob, containsCredential } = require('../void_extension/egoagent-dag-chat/completion');

function event() {
  const listeners = new Set();
  return { on: fn => { listeners.add(fn); return { dispose: () => listeners.delete(fn) }; }, fire: value => [...listeners].forEach(fn => fn(value)) };
}
class CancellationTokenSource {
  constructor() { this.event = event(); this.token = { isCancellationRequested: false, onCancellationRequested: this.event.on }; }
  cancel() { if (!this.token.isCancellationRequested) { this.token.isCancellationRequested = true; this.event.fire(); } }
  dispose() {}
}
function doc(text = 'def add(a, b):\n    return ', path = '/project/main.py', root = '/project') {
  return { text, version: 1, languageId: 'python', root, uri: { scheme: 'file', path, toString: () => `file://${path}` },
    getText() { return this.text; }, lineAt(line) { return { text: this.text.split('\n')[line] }; },
    offsetAt(p) { return this.text.split('\n').slice(0, p.line).reduce((n, s) => n + s.length + 1, 0) + p.character; } };
}
function fixture(options = {}) {
  const changes = event(), selection = event(), configChange = event(), activeChange = event();
  const settings = { 'ai.completionDelayMs': 0, ...options.settings };
  const counts = {}, calls = [], commands = [];
  const vscode = {
    CancellationTokenSource, InlineCompletionTriggerKind: { Invoke: 0, Automatic: 1 },
    InlineCompletionItem: class { constructor(insertText, range) { Object.assign(this, { insertText, range }); } },
    Range: class { constructor(start, end) { Object.assign(this, { start, end }); } },
    commands: { executeCommand: async name => commands.push(name) },
    workspace: { isTrusted: true, getConfiguration: () => ({ get: (key, fallback) => settings[key] ?? fallback }), getWorkspaceFolder: d => ({ uri: { toString: () => d.path.startsWith('/other/') ? '/other' : '/project' } }), onDidChangeTextDocument: changes.on, onDidChangeConfiguration: configChange.on },
    window: { visibleTextEditors: [], onDidChangeTextEditorSelection: selection.on, onDidChangeActiveTextEditor: activeChange.on },
  };
  const ai = { enabled: options.enabled ?? true, backendUrl: 'http://backend-one', request: async (...args) => { calls.push(args); return options.request ? options.request(...args) : { completion: 'a + b' }; } };
  const context = { subscriptions: [], globalState: { get: (_, def) => def, update: async () => {} } };
  const provider = new (createCompletionProvider(vscode, uri => uri.path))(context, { bump: (key, n = 1) => { counts[key] = (counts[key] || 0) + n; } }, ai);
  const run = (document = doc(), token, triggerKind = 1) => {
    const lines = document.text.split('\n'); const p = { line: lines.length - 1, character: lines.at(-1).length };
    return provider.provideInlineCompletionItems(document, p, { triggerKind }, token);
  };
  return { provider, run, calls, counts, changes, selection, configChange, activeChange, settings, vscode, ai, commands };
}
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
function deferred() { let resolve; const promise = new Promise(r => { resolve = r; }); return { resolve, promise }; }

test('native ghost item is insertion-only and accepted once', async () => {
  const f = fixture(), d = doc(); const items = await f.run(d);
  assert.equal(items[0].insertText, 'a + b'); assert.equal(d.text, 'def add(a, b):\n    return ');
  assert.deepEqual(items[0].range.start, items[0].range.end);
  assert.equal(items[0].command.command, 'egoagent.completionAccepted');
  assert.equal(f.provider.accept(items[0].command.arguments[0]), true); assert.equal(f.provider.accept(), false);
  assert.equal(f.counts.completionsAccepted, 1);
});
test('debounce coalesces rapid typing before any network request', async () => {
  const f = fixture({ settings: { 'ai.completionDelayMs': 30 } }), d = doc();
  const first = f.run(d); d.text += 'a'; d.version++; const second = f.run(d);
  assert.deepEqual(await first, []); await second; assert.equal(f.calls.length, 1);
});
test('explicit trigger bypasses debounce', async () => {
  const f = fixture({ settings: { 'ai.completionDelayMs': 3000 } });
  await f.run(doc(), null, 0); assert.equal(f.calls.length, 1);
});
test('editing cancels in-flight requests even before the next provider invocation', async () => {
  const pending = deferred(), f = fixture({ request: () => pending.promise }), d = doc();
  const run = f.run(d, null, 0); await pause(1); d.version++; f.changes.fire({ document: d, contentChanges: [{}] });
  assert.deepEqual(await run, []); assert.equal(f.calls[0][3].isCancellationRequested, true); pending.resolve({ completion: 'stale' });
});
test('moving the cursor cancels in-flight work', async () => {
  const pending = deferred(), f = fixture({ request: () => pending.promise });
  const run = f.run(doc(), null, 0); await pause(1); f.selection.fire({}); assert.deepEqual(await run, []); pending.resolve({ completion: 'stale' });
});
test('cancelled older request cannot clear the newer loading indicator', async () => {
  const first = deferred(), second = deferred(); let calls = 0;
  const f = fixture({ request: () => (++calls === 1 ? first.promise : second.promise) }), d = doc();
  const a = f.run(d, null, 0); const b = f.run(d, null, 0);
  await a; assert.equal(f.provider.state, 'loading');
  second.resolve({ completion: 'a + b' }); await b; assert.equal(f.provider.state, 'suggested');
  first.resolve({ completion: 'old' });
});
test('external cancellation drops results', async () => {
  const pending = deferred(), f = fixture({ request: () => pending.promise }), token = new CancellationTokenSource();
  const run = f.run(doc(), token.token, 0); token.cancel(); assert.deepEqual(await run, []); pending.resolve({ completion: 'stale' });
});
test('stale document versions cannot receive a result', async () => {
  const pending = deferred(), f = fixture({ request: () => pending.promise }), d = doc();
  const run = f.run(d, null, 0); d.version++; pending.resolve({ completion: 'stale' }); assert.deepEqual(await run, []);
});
test('cache survives undo/backspace version changes', async () => {
  const f = fixture(), d = doc(); await f.run(d); d.version += 2; await f.run(d);
  assert.equal(f.calls.length, 1); assert.equal(f.counts.completionCacheHits, 1);
});
test('typing through a suggestion reuses its remaining text', async () => {
  const f = fixture(), d = doc(); await f.run(d); d.text += 'a '; d.version++;
  assert.equal((await f.run(d))[0].insertText, '+ b'); assert.equal(f.calls.length, 1);
});
test('Esc suppression persists until content changes or explicit invocation', async () => {
  const f = fixture(), d = doc(); await f.run(d); f.provider.reject(); assert.deepEqual(await f.run(d), []);
  assert.equal((await f.run(d, null, 0))[0].insertText, 'a + b'); assert.equal(f.calls.length, 1);
});
test('cache is isolated by backend and configuration changes', async () => {
  const f = fixture(), d = doc(); await f.run(d); f.ai.backendUrl = 'http://backend-two'; await f.run(d);
  f.configChange.fire({ affectsConfiguration: () => true }); await f.run(d); assert.equal(f.calls.length, 3);
});
test('cache is bounded and expires', () => {
  const f = fixture(); for (let i = 0; i < 100; i++) f.provider.cacheSet(String(i), { text: 'a' });
  assert.equal(f.provider.cache.size, 64); assert.equal(f.provider.cacheGet('0'), undefined);
  f.provider.cache.set('old', { text: 'x', at: 0 }); assert.equal(f.provider.cacheGet('old'), undefined);
});
test('empty model response is respected and cached, not replaced by fake TODO code', async () => {
  const f = fixture({ request: async () => ({ completion: '' }) }), d = doc('# TODO: implement payment\n');
  assert.deepEqual(await f.run(d), []); assert.deepEqual(await f.run(d), []); assert.equal(f.calls.length, 1);
});
test('offline fallback only reuses existing identifiers', async () => {
  const f = fixture({ enabled: false });
  assert.equal((await f.run(doc('customer_total = 0\ncustomer_')))[0].insertText, 'total');
  assert.equal(f.provider.state, 'local'); assert.equal(f.calls.length, 0);
  assert.deepEqual(await f.run(doc('# TODO: implement payments')), []);
});
test('provider errors do not break typing and can disable fallback', async () => {
  const f = fixture({ request: async () => { throw Error('offline'); }, settings: { 'localCompletion.localWordFallback': false } });
  assert.deepEqual(await f.run(), []); assert.equal(f.counts.completionErrors, 1); assert.equal(f.provider.state, 'unavailable');
});
test('timeout terminates client waiting even if transport ignores cancellation', async () => {
  const pending = deferred(), f = fixture({ request: () => pending.promise, settings: { 'ai.completionTimeoutMs': 1000 } });
  assert.deepEqual(await f.run(doc(), null, 0), []); assert.equal(f.provider.state, 'timeout'); assert.equal(f.counts.completionTimeouts, 1);
  pending.resolve({ completion: 'late' });
});
test('sensitive files and credentials are never sent', async () => {
  const f = fixture();
  for (const path of ['/project/.env', '/project/.env.local', '/project/id_rsa', '/project/key.pem', '/project/secrets/config.py', '/project/node_modules/a.py']) assert.deepEqual(await f.run(doc('x = ', path)), []);
  assert.deepEqual(await f.run(doc('key = "sk-' + 'x'.repeat(30) + '"\nx = ')), []);
  assert.equal(f.calls.length, 0);
});
test('user exclusions and untrusted workspace are honored', async () => {
  const f = fixture({ settings: { 'localCompletion.exclude': ['**/internal/**'] } });
  assert.deepEqual(await f.run(doc('x = ', '/project/internal/a.py')), []);
  f.vscode.workspace.isTrusted = false; assert.deepEqual(await f.run(), []); assert.equal(f.calls.length, 0);
});
test('large documents, nonfile documents and selections are skipped', async () => {
  const f = fixture(); assert.deepEqual(await f.run(doc('a'.repeat(500001))), []);
  const d = doc(); d.uri.scheme = 'git'; assert.deepEqual(await f.run(d), []); d.uri.scheme = 'file';
  f.vscode.window.activeTextEditor = { document: d, selections: [{}, {}] }; assert.deepEqual(await f.run(d), []);
  assert.equal(f.calls.length, 0);
});
test('open-file context is opt-in, bounded, same-workspace and filtered', async () => {
  const f = fixture(), d = doc();
  f.vscode.window.visibleTextEditors = [doc('safe_helper = 1', '/project/helper.py'), doc('private = 1', '/other/b.py'), doc('bad = 1', '/project/.env')].map(document => ({ document }));
  await f.run(d); assert.deepEqual(f.calls[0][1].open_files, []);
  f.settings['localCompletion.includeOpenFiles'] = true; await f.run(d);
  assert.deepEqual(f.calls[1][1].open_files.map(x => x.path), ['/project/helper.py']);
});
test('model receives bounded prefix/suffix and no unrelated history', async () => {
  const f = fixture(), d = doc('x'.repeat(10000)); await f.run(d);
  assert.equal(f.calls[0][1].prefix.length, 6000); assert.equal(f.calls[0][1].recent_edits, undefined);
});
test('toggle cancels pending work, hides preview and disables requests', async () => {
  const f = fixture({ settings: { 'ai.completionDelayMs': 40 } }), run = f.run();
  await f.provider.toggle(); assert.deepEqual(await run, []); assert.deepEqual(await f.run(), []);
  assert.equal(f.calls.length, 0); assert.deepEqual(f.commands, ['editor.action.inlineSuggest.hide']);
});
test('normalization preserves indentation and avoids corrupting single-character overlaps', () => {
  assert.equal(normalizeSuggestion('```python\n    return a\n```', 'def f():\n', ''), '    return a');
  assert.equal(normalizeSuggestion('item', 'x = ', 'more'), 'item');
  assert.equal(normalizeSuggestion('value)', 'call(', ')'), 'value');
  assert.equal(normalizeSuggestion('42\nnext()', 'x = ', '\nnext()'), '42');
  assert.equal(normalizeSuggestion({ code: 'x' }, '', ''), '');
  assert.equal(normalizeSuggestion('    ', '', ''), '');
  assert.equal(normalizeSuggestion('    evens = []\n    odds = []', 'def f():\n    ', ''), 'evens = []\n    odds = []');
  assert.equal(normalizeSuggestion('        nested()\n    done()', 'if ready:\n    ', ''), '    nested()\n    done()');
  assert.equal(normalizeSuggestion('evens = []\n    odds = []', 'def f():\n    ', ''), 'evens = []\n    odds = []');
  assert.equal(localWord('hello_world', 'hello_', 'world'), '');
  assert.ok(matchesGlob('/x/a.key', '**/*.key')); assert.ok(containsCredential('-----BEGIN PRIVATE KEY-----'));
});
test('native shortcuts preserve suggest-widget, snippets and ordinary indentation', () => {
  const manifest = require('../void_extension/egoagent-dag-chat/package.json');
  const tab = manifest.contributes.keybindings.find(x => x.key === 'tab');
  assert.equal(tab.command, 'editor.action.inlineSuggest.commit');
  for (const condition of ['inlineSuggestionVisible', '!suggestWidgetVisible', '!inSnippetMode', '!editorTabMovesFocus']) assert.ok(tab.when.includes(condition));
  assert.ok(manifest.contributes.keybindings.some(x => x.command.endsWith('acceptNextWord')));
  assert.ok(manifest.contributes.keybindings.some(x => x.command.endsWith('acceptNextLine')));
});
test('retired tutorial has no runtime entrypoints or build hooks', () => {
  for (const path of ['harness_editor/src/App.tsx', 'void_extension/egoagent-dag-chat/extension-v21.js', 'void_extension/egoagent-dag-chat/media/chat.js']) assert.doesNotMatch(fs.readFileSync(path, 'utf8'), /RecordingTutorial|tutorialGraphPolicy|tutorialQuick|tutorialCommand/);
  assert.equal(fs.existsSync('harness_editor/src/components/RecordingTutorial.tsx'), false);
  assert.doesNotMatch(fs.readFileSync('harness_editor/package.json', 'utf8'), /validate:tutorials/);
});
test('AI status deduplicates requests and scopes cache by backend', async () => {
  let backend = 'one', calls = 0;
  const source = fs.readFileSync('void_extension/egoagent-dag-chat/extension-v21.js', 'utf8');
  const c = { vscode: { workspace: { getConfiguration: () => ({ get: () => true }) } }, remoteWorkspaces: { backendUrl: () => backend }, AbortController, setTimeout, clearTimeout, fetch: async () => { calls++; await pause(2); return { ok: true, json: async () => ({ configured: true }) }; } };
  vm.createContext(c); vm.runInContext(source.slice(source.indexOf('class AIClient'), source.indexOf('\nfunction fsPathForBackend')) + '\nthis.client = new AIClient();', c);
  await Promise.all([c.client.status(false, 'autocomplete'), c.client.status(false, 'autocomplete')]); assert.equal(calls, 1);
  await c.client.status(false, 'autocomplete'); assert.equal(calls, 1); backend = 'two'; await c.client.status(false, 'autocomplete'); assert.equal(calls, 2);
});
