const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../void_extension/egoagent-dag-chat/media/chat.js'), 'utf8');
const html = fs.readFileSync(path.join(__dirname, '../void_extension/egoagent-dag-chat/extension-v21.js'), 'utf8');
function load(names, extra = {}) {
  const context = {state: {config: {slots: {}, pipeline: {nodes: {}}}, identity:'test_bot', bindings:{agent:'test_bot'}, mode:'chat'}, ...extra};
  vm.createContext(context);
  for (const name of names) {
    let start = source.indexOf(`  function ${name}(`);
    if (start < 0) start = source.indexOf(`  async function ${name}(`);
    assert.ok(start >= 0, name);
    vm.runInContext(source.slice(start, source.indexOf('\n  }', start) + 4), context);
  }
  return context;
}
test('Chat exposes Flow and version, not runtime or Identity overrides', () => {
  for (const id of ['modeSelect','identitySelect','slotBindings','bindingsDetails','dagNodes']) {
    assert.ok(!html.includes(`id="${id}"`));
    assert.ok(!source.includes(`$('${id}')`));
  }
  for (const id of ['harnessSelect','harnessVersionSelect','editSelectedFlow']) assert.ok(html.includes(`id="${id}"`));
});
test('single and multi-role bindings come exclusively from saved Flow', () => {
  const c = load(['buildAgents']);
  c.state.config.slots = {agent:{identity:'real'},reviewer:{identity:'identity/reviewer'}};
  assert.equal(JSON.stringify(c.buildAgents()), JSON.stringify({agent:'identity/real',reviewer:'identity/reviewer'}));
});
test('missing required or referenced role fails without fallback', () => {
  const c = load(['buildAgents']);
  c.state.config.slots.agent = {required:true};
  assert.throws(() => c.buildAgents(), /Build/);
  c.state.config.slots = {};
  c.state.config.pipeline.nodes.model = {agent:'missing'};
  assert.throws(() => c.buildAgents(), /missing/);
});
test('optional unbound roles and model-free Flows do not invent Identities', () => {
  const c = load(['buildAgents']);
  c.state.config.slots.optional = {required:false};
  assert.equal(JSON.stringify(c.buildAgents()), '{}');
});
test('an old run with Chat overrides is not reused', () => {
  const c = load(['sortedRecord','buildAgents','executionUsesSavedFlow']);
  c.state.config.slots = {agent:{identity:'real'}};
  c.state.config.pipeline.mode = 'plan';
  assert.equal(c.executionUsesSavedFlow({mode:'chat',agents:{agent:'identity/test_bot'}}),false);
  assert.equal(c.executionUsesSavedFlow({mode:'plan',agents:{agent:'identity/real'}}),true);
});
test('Chat start sends no Identity, mode or evolution-scope overrides', async () => {
  let sent;
  const c = load(['startExecution'], {
    state:{harness:'demo',harnessVersion:'v1',editorContext:{workspacePath:'C:/demo'},approvalMode:'manual',messages:[]},
    canonicalWorkspace:x=>x,buildAgents:()=>({agent:'identity/real'}),
    request:async (url,options)=>{sent=JSON.parse(options.body);return {run_id:'new',state:{}};},
    postBackendReviewSnapshot(){},persist(){},renderSelectors(){},refreshExecutionSessions(){},renderRuntime(){},toast(){},
  });
  await c.startExecution(true,{initialInput:'hello'});
  assert.equal(sent.harness,'demo'); assert.equal(sent.harness_version,'v1');
  for (const name of ['agents','mode','mutation_targets']) assert.equal(name in sent,false);
});
test('latest selection loads its pinned version instead of a mutable draft', async () => {
  const calls=[];
  const element={classList:{toggle(){}},textContent:''};
  const c=load(['loadHarness','buildAgents'],{
    state:{configLoadGeneration:0}, $:()=>element,
    requestCatalog:async url=>{calls.push(url);return url.includes('harness-versions')?{latest:'v2',versions:[]}:{slots:{agent:{identity:'real'}},pipeline:{mode:'plan',nodes:{}}};},
    renderSelectors(){},renderHarnessVersions(){},renderSessionTabs(){},persist(){},
  });
  await c.loadHarness('demo','latest');
  assert.deepEqual(calls,['/api/harness-versions/demo','/api/harness-version/demo/v2']);
  assert.equal(c.state.identity,'real'); assert.equal(c.state.mode,'plan');
});

test('catalog refresh after saving a new Flow does not change the selected version', async () => {
  const c = load(['loadCatalog'], {
    state: {harness:'existing',harnessVersion:'v1',config:{marker:'pinned'}},
    requestCatalog:async url=>url==='/api/harnesses'?['existing','new_flow']:[],
    normalizeNames:value=>value, renderSelectors(){}, setConnection(){}, persist(){},
    renderCatalogStatus(){}, scheduleCatalogRetry(){},
    loadHarness(){throw new Error('must not silently reload or change the selected Flow');},
    toast(message){throw new Error(message);},
  });
  await c.loadCatalog(false);
  assert.ok(c.state.harnesses.includes('new_flow'));
  assert.equal(c.state.harnessVersion,'v1');
  assert.equal(c.state.config.marker,'pinned');
});
