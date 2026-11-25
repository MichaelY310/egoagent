const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../void_extension/egoagent-dag-chat/media/chat.js'), 'utf8');
const flush = () => new Promise(setImmediate);

function fixture(request) {
  const timers = new Map(), elements = new Map();
  let nextTimer = 1;
  const element = id => {
    if (!elements.has(id)) elements.set(id, { innerHTML: '', textContent: '', hidden: false,
      disabled: false, classList: {toggle(){}}, setAttribute(){}, addEventListener(type, fn) { this[type] = fn; } });
    return elements.get(id);
  };
  const c = {
    state: {harnesses:[],harnessCatalog:[],identities:[],harness:'cookbook_01_react',harnessVersion:'latest',
      config:null,configLoadGeneration:0,catalogGeneration:0,catalogLoaded:false,catalogBusy:false,
      catalogError:'',catalogRetryAttempt:0,catalogRetryTimer:null,messages:[{text:'keep history'}]},
    document:{hidden:false}, request, AbortController, DEFAULT_CODE_HARNESS:'code_agent_auto',
    $:element, escapeHtml:x=>String(x), setConnection(){}, persist(){}, renderSessionTabs(){},
    renderHarnessVersions(){}, renderSelectors(){ c.renderCatalogStatus(); }, buildAgents(){},
    setTimeout(fn,delay) {const id=nextTimer++;timers.set(id,{fn,delay});return id;},
    clearTimeout(id) {timers.delete(id);},
  };
  vm.createContext(c);
  for (const name of ['normalizeNames','requestCatalog','renderCatalogStatus','scheduleCatalogRetry','recoverCatalog','loadCatalog','loadHarness']) {
    let start=source.indexOf(`  function ${name}(`);
    if(start<0)start=source.indexOf(`  async function ${name}(`);
    assert.ok(start>=0,name);
    vm.runInContext(source.slice(start,source.indexOf('\n  }',start)+4),c);
  }
  return {c,timers,element,fire(id){const timer=timers.get(id);timers.delete(id);timer.fn();}};
}
function healthy(url) {
  if(url==='/api/harnesses')return ['cookbook_01_react','code_agent_auto'];
  if(url==='/api/harnesses/detailed'||url==='/api/identities')return [];
  if(url.includes('/api/harness-versions/'))return {latest:'v3',versions:[{id:'v1'},{id:'v3'}]};
  return {slots:{agent:{identity:'reader'}},pipeline:{nodes:{},mode:'agent'}};
}

test('initial failure displays a retry state and recovers names/config automatically',async()=>{
  let failed=true;
  const f=fixture(async url=>{if(failed)throw Error('offline');return healthy(url);});
  await f.c.loadCatalog();
  assert.match(f.element('harnessSelect').innerHTML,/请重试/);
  assert.match(f.element('agentConfigSummary').textContent,/加载失败/);
  assert.ok(f.c.state.catalogRetryTimer);
  failed=false;f.fire(f.c.state.catalogRetryTimer);await flush();
  assert.equal(f.c.state.catalogError,'');assert.equal(f.c.state.catalogLoaded,true);
  assert.equal(f.c.state.config.slots.agent.identity,'reader');assert.equal(f.c.state.harnessVersion,'v3');
  assert.equal(f.element('harnessSelect').disabled,false);
  assert.equal(f.c.state.messages[0].text,'keep history');
});

test('unused Identity API is not called; description failure never blocks choices',async()=>{
  const calls=[];
  const f=fixture(async url=>{
    calls.push(url);
    if(url==='/api/identities'||url==='/api/harnesses/detailed')throw Error('optional unavailable');
    return healthy(url);
  });
  await f.c.loadCatalog();await flush();
  assert.equal(f.c.state.catalogError,'');assert.equal(f.c.state.harnesses.length,2);
  assert.ok(f.c.state.config);assert.equal(f.c.state.catalogRetryTimer,null);
  assert.ok(!calls.includes('/api/identities'));
});

test('hung metadata requests are aborted and do not gate selected Flow',async()=>{
  const f=fixture((url,options)=>{
    if(url==='/api/identities'||url==='/api/harnesses/detailed')return new Promise((_,reject)=>options.signal.addEventListener('abort',()=>reject(Error('aborted'))));
    return Promise.resolve(healthy(url));
  });
  await f.c.loadCatalog();assert.ok(f.c.state.config);
  for(const id of [...f.timers.keys()])f.fire(id);
  await flush();assert.equal(f.c.state.catalogError,'');assert.equal(f.timers.size,0);
});

test('a hung primary request times out, releases busy state and schedules retry',async()=>{
  const f=fixture((url,options)=>new Promise((_,reject)=>options.signal.addEventListener('abort',()=>reject(Error('aborted')))));
  const pending=f.c.loadCatalog();
  const [id,timer]=[...f.timers.entries()][0];assert.equal(timer.delay,10000);f.fire(id);
  await pending;assert.equal(f.c.state.catalogBusy,false);
  assert.match(f.c.state.catalogError,/超时/);assert.ok(f.c.state.catalogRetryTimer);
});

test('HTML or invalid JSON shape does not erase previous choices',async()=>{
  for(const response of ['<!DOCTYPE html>wrong server',{error:'not a catalog'}]) {
    const f=fixture(async()=>response);
    f.c.state.harnesses=['cookbook_01_react'];f.c.state.catalogLoaded=true;
    f.c.state.config={pinned:true};f.c.state.harnessVersion='v1';
    await f.c.loadCatalog(false);
    assert.ok(f.c.state.catalogError);assert.equal(f.c.state.harnesses[0],'cookbook_01_react');
    assert.equal(f.c.state.config.pinned,true);assert.equal(f.c.state.harnessVersion,'v1');
  }
});

test('reconnect recovery is single-flight and does not overwrite pinned configuration',async()=>{
  let resolveNames,calls=0;
  const f=fixture(url=>{
    if(url==='/api/harnesses'){calls++;return new Promise(resolve=>{resolveNames=resolve;});}
    return Promise.resolve(healthy(url));
  });
  f.c.state.config={pinned:true};f.c.state.harnessVersion='v1';
  f.c.recoverCatalog();f.c.recoverCatalog();assert.equal(calls,1);
  resolveNames(healthy('/api/harnesses'));await flush();
  assert.equal(f.c.state.config.pinned,true);assert.equal(f.c.state.harnessVersion,'v1');
});

test('background tabs suspend retry and visibility recovery resumes it',async()=>{
  let calls=0;
  const f=fixture(async()=>{calls++;throw Error('offline');});
  await f.c.loadCatalog();f.c.document.hidden=true;f.fire(f.c.state.catalogRetryTimer);
  f.c.recoverCatalog();assert.equal(calls,1);
  f.c.document.hidden=false;f.c.recoverCatalog();await flush();assert.equal(calls,2);
});

test('a failed configuration load recovers automatically as well as the catalog',async()=>{
  let failConfig=true;
  const f=fixture(async url=>{if(failConfig&&url.includes('/api/harness-version/'))throw Error('snapshot unavailable');return healthy(url);});
  await f.c.loadCatalog();assert.equal(f.c.state.catalogLoaded,true);assert.equal(f.c.state.config,null);
  failConfig=false;f.fire(f.c.state.catalogRetryTimer);await flush();assert.ok(f.c.state.config);
  assert.equal(f.c.state.catalogError,'');
});

test('genuinely empty catalog is distinguished from loading failure',async()=>{
  const f=fixture(async()=>[]);await f.c.loadCatalog();
  assert.equal(f.c.state.catalogError,'');assert.equal(f.c.state.catalogRetryTimer,null);
  assert.match(f.element('harnessSelect').innerHTML,/暂无 Harness/);
});

test('removed selection resets its version before selecting a different Flow',async()=>{
  const calls=[];const f=fixture(async url=>{calls.push(url);return healthy(url);});
  f.c.state.harness='removed';f.c.state.harnessVersion='old-flow-version';
  await f.c.loadCatalog();
  assert.equal(f.c.state.harness,'code_agent_auto');assert.equal(f.c.state.harnessVersion,'v3');
  assert.ok(!calls.some(url=>url.includes('old-flow-version')));
});

test('retry is capped and websocket/visibility/online paths invoke recovery',()=>{
  const f=fixture(async()=>[]);f.c.state.catalogRetryAttempt=20;f.c.scheduleCatalogRetry();
  assert.equal(f.timers.get(f.c.state.catalogRetryTimer).delay,30000);
  assert.match(source,/addEventListener\('open',[\s\S]*?recoverCatalog\(\)/);
  assert.match(source,/addEventListener\('visibilitychange',[\s\S]*?recoverCatalog\(\)/);
  assert.match(source,/addEventListener\('online', recoverCatalog\)/);
});
