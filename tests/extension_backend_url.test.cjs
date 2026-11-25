const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../void_extension/egoagent-dag-chat/remote-workspaces.js'), 'utf8');
const start = source.indexOf('function backendUrl()');
const body = source.slice(start, source.indexOf('\n}', start) + 2);
function url(runtime, setting = {}) {
  const context = { runtime, vscode: { workspace: { getConfiguration: () => ({
    inspect: () => setting,
    get: () => 'http://127.0.0.1:8765',
  }) } } };
  vm.createContext(context);
  return vm.runInContext(body + '\nbackendUrl()', context);
}

test('launcher runtime port wins over package default after extension packaging', () => {
  assert.equal(url({ backendUrl: 'http://127.0.0.1:8875/' }, { defaultValue: 'http://127.0.0.1:8765' }), 'http://127.0.0.1:8875');
});
test('explicit local backend setting keeps folder/workspace/global precedence', () => {
  const runtime = { backendUrl: 'http://127.0.0.1:8875' };
  assert.equal(url(runtime, { globalValue: 'http://localhost:9000' }), 'http://localhost:9000');
  assert.equal(url(runtime, { globalValue: 'http://localhost:9000', workspaceValue: 'http://localhost:9001', workspaceFolderValue: 'http://localhost:9002' }), 'http://localhost:9002');
});
test('remote runtime does not inherit local workspace backend', () => {
  assert.equal(url({ id: 'remote-test', backendUrl: 'http://127.0.0.1:19000' }, { workspaceValue: 'http://localhost:8765' }), 'http://127.0.0.1:19000');
});
test('standalone extension still falls back to its default', () => {
  assert.equal(url({}), 'http://127.0.0.1:8765');
});

function socketUrl(runtime, apiUrl) {
  const start = source.indexOf('function webSocketUrl(');
  const body = source.slice(start, source.indexOf('\n}', start) + 2);
  return vm.runInNewContext(body + '\nwebSocketUrl(apiUrl)', { runtime, apiUrl, URL });
}

test('independently allocated WS port is used by local and remote windows', () => {
  for (const id of ['', 'remote']) {
    assert.equal(socketUrl({ id, backendUrl: 'http://127.0.0.1:50218', webSocketUrl: 'ws://127.0.0.1:8766/' },
      'http://127.0.0.1:50218/'), 'ws://127.0.0.1:8766');
  }
});

test('explicit backend override never borrows another runtime socket', () => {
  assert.equal(socketUrl({ backendUrl: 'http://127.0.0.1:50218', webSocketUrl: 'ws://127.0.0.1:8766' },
    'http://127.0.0.1:19101'), 'ws://127.0.0.1:19102');
});

test('older installations keep conventional socket fallback, including HTTPS', () => {
  assert.equal(socketUrl({}, 'http://localhost:8765'), 'ws://localhost:8766');
  assert.equal(socketUrl({}, 'https://localhost:19101'), 'wss://localhost:19102');
});
