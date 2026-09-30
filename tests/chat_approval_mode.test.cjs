const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('void_extension/egoagent-dag-chat/media/chat.js', 'utf8');

function fixture() {
  const elements = {approvalMode: {classList: {toggle() {}}, disabled: false}, approvalModeHint: {}};
  const calls = [];
  const c = {state: {runId: 'one', sessionName: 's1', approvalMode: 'manual'},
    $: name => elements[name], currentWorkspace: () => '/test', persist() {},
    runBody: value => ({run_id: c.state.runId, ...value}), toast() {},
    request: async (path, payload) => calls.push({path, payload}), calls, elements};
  vm.createContext(c);
  for (const name of ['renderApprovalMode', 'changeApprovalMode']) {
    let start = source.indexOf(`  function ${name}(`);
    if (start < 0) start = source.indexOf(`  async function ${name}(`);
    vm.runInContext(source.slice(start, source.indexOf('\n  }', start) + 4), c);
  }
  return c;
}

test('draft switch is local until a run is started', async () => {
  const c = fixture(); c.state.runId = '';
  await c.changeApprovalMode('auto', ':s1:/test');
  assert.equal(c.calls.length, 0);
  assert.equal(c.state.approvalMode, 'auto');
  assert.equal(c.elements.approvalMode.textContent, '工具审批：自动批准');
});

test('live switch sends the exact run and explicit confirmation, without restarting', async () => {
  const c = fixture();
  await c.changeApprovalMode('auto', 'one:s1:/test');
  assert.equal(c.calls.length, 1);
  assert.equal(c.calls[0].path, '/api/execution/approval-mode');
  assert.equal(c.calls[0].payload.body.run_id, 'one');
  assert.equal(c.calls[0].payload.body.confirmed, true);
  await c.changeApprovalMode('manual', 'one:s1:/test');
  assert.equal(c.state.approvalMode, 'manual');
});

test('failed API request leaves the mode unchanged and button usable', async () => {
  const c = fixture(); c.request = async () => { throw Error('offline'); };
  await c.changeApprovalMode('auto', 'one:s1:/test');
  assert.equal(c.state.approvalMode, 'manual');
  assert.equal(c.elements.approvalMode.disabled, false);
});

test('confirmation from a different session never changes this session', async () => {
  const c = fixture();
  await c.changeApprovalMode('auto', 'other:s2:/test');
  assert.equal(c.calls.length, 0);
  assert.equal(c.state.approvalMode, 'manual');
});

test('changing session while request is in flight does not overwrite its mode', async () => {
  const c = fixture();
  c.request = async () => { c.state.runId = 'other'; c.state.sessionName = 's2'; };
  await c.changeApprovalMode('auto', 'one:s1:/test');
  assert.equal(c.state.approvalMode, 'manual');
});
