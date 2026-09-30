const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../void_extension/egoagent-dag-chat/media/chat.js'), 'utf8');
function loadFunctions(names, context) {
  vm.createContext(context);
  for (const name of names) {
    const regular = source.indexOf(`  function ${name}(`);
    const start = regular < 0 ? source.indexOf(`  async function ${name}(`) : regular;
    assert.ok(start >= 0, name);
    vm.runInContext(source.slice(start, source.indexOf('\n  }', start) + 4), context);
  }
  return context;
}
function fixture() {
  let polls = 0;
  const state = { runId: 'run-a', harness: 'adaptive_code_agent', harnessVersion: 'v1', mode: 'chat',
    config: {}, editorContext: { workspacePath: 'C:\\project' }, messages: [],
    ws: {readyState: 1}, lastExecutionPoll: 0 };
  const context = loadFunctions(['canonicalWorkspace', 'currentWorkspace', 'sortedRecord',
    'executionMatchesSelection', 'handleEvent', 'reconcileExecution'], {
    state, Date: {now: () => 20000}, document: { hidden: false }, WebSocket: { OPEN: 1 },
    buildAgents: () => ({agent: 'coder'}), setAgentActivity() {}, renderRuntime() {},
    executionConfigSnapshot: s => s,
    addMessage: (agent, text) => state.messages.push({agent, text}),
    pollExecution: () => { polls++; },
  });
  return { context, state, polls: () => polls, scope: {run_id:'run-a', surface:'chat', workspace:'C:/project',
    harness:'adaptive_code_agent', harness_version:'v1', mode:'chat', agents:{agent:'coder'}} };
}
test('a versioned live reply is rendered without waiting for HTTP', () => {
  const {context, state, scope} = fixture();
  context.handleEvent({type:'token', scope, data:{agent:'agent', text:'你好'}});
  assert.deepEqual(state.messages, [{agent:'agent',text:'你好'}]);
});
test('legacy events missing only version are recovered for this exact run', () => {
  const {context, state, scope} = fixture();
  delete scope.harness_version;
  context.handleEvent({type:'token',scope,data:{text:'legacy'}});
  assert.equal(state.messages[0].text, 'legacy');
  state.runId = '';
  assert.equal(context.executionMatchesSelection(scope), false);
});
test('never mix a different session, workspace, version, mode, identity or builder', () => {
  const {context, state, scope} = fixture();
  for (const mismatch of [{run_id:'other'}, {workspace:'C:/other'}, {harness_version:'v2'},
    {mode:'agent'}, {agents:{agent:'other'}}, {surface:'builder'}, {harness:'other'}]) {
    context.handleEvent({type:'token',scope:{...scope,...mismatch},data:{text:'wrong'}});
  }
  assert.equal(state.messages.length, 0);
});
test('healthy WebSocket still reconciles dropped events, without rapid full polling', () => {
  const {context, state, polls} = fixture();
  context.reconcileExecution();
  assert.equal(polls(), 1);
  state.lastExecutionPoll = 19000;
  context.reconcileExecution();
  assert.equal(polls(), 1);
  state.ws.readyState = 3;
  context.reconcileExecution();
  assert.equal(polls(), 2);
  context.document.hidden = true;
  context.reconcileExecution();
  assert.equal(polls(), 2);
});

test('a missing run after restart keeps session history and allows resuming', async () => {
  const {context,state}=fixture();
  state.sessionName='saved-session';state.messages.push({agent:'user',text:'keep me'});
  Object.assign(context,{AbortController,setTimeout,clearTimeout,runQuery:()=>'?run_id=run-a',
    request:async()=>{throw Object.assign(new Error('not found'),{status:404});},persist(){},
    setConnection(){},setAgentActivity(){}});
  // Context is already contextified; load only this async function into it.
  const start=source.indexOf('  async function pollExecution(');
  vm.runInContext(source.slice(start,source.indexOf('\n  }',start)+4),context);
  await context.pollExecution();
  assert.equal(state.runId,'');assert.equal(state.sessionName,'saved-session');
  assert.equal(state.messages[0].text,'keep me');assert.equal(state.runStatus,'interrupted');
  assert.equal(state.pollBusy,false);
});
test('a late 404 for the old session cannot clear the newly selected run', async () => {
  const {context,state}=fixture();
  Object.assign(context,{AbortController,setTimeout,clearTimeout,runQuery:()=>'?run_id=run-a',
    request:async()=>{state.runId='new-run';throw Object.assign(new Error('not found'),{status:404});}});
  const start=source.indexOf('  async function pollExecution(');
  vm.runInContext(source.slice(start,source.indexOf('\n  }',start)+4),context);
  await context.pollExecution();
  assert.equal(state.runId,'new-run');assert.equal(state.pollBusy,false);
});
