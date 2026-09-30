const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('void_extension/egoagent-dag-chat/media/chat.js','utf8');
function fixture() {
  const state = {messages:[{agent:'user',text:'read debug configurations'}]};
  const context = {state, Date, AbortController, setTimeout, clearTimeout,
    agentConfigSnapshot:()=>({harness:'code_agent_auto'}),renderMessages(){},renderAgentActivity(){},
    escapeHtml: v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),
    pretty: v=>typeof v==='string'? v:JSON.stringify(v)};
  vm.createContext(context);
  for(const name of ['currentProgressBubble','syncChatProgress','renderProgressBubble','setAgentActivity','requestWithDeadline']) {
    let start=source.indexOf(`  function ${name}(`);
    if(start<0) start=source.indexOf(`  async function ${name}(`);
    vm.runInContext(source.slice(start,source.indexOf('\n  }',start)+4),context);
  }
  return context;
}
test('immediate bubble before network or first model token',()=>{
  const c=fixture(); const bubble=c.currentProgressBubble(true);
  c.setAgentActivity('正在读取编辑器状态','running');
  assert.equal(c.state.messages.length,2);
  assert.match(c.renderProgressBubble(bubble),/正在读取编辑器状态/);
  assert.match(c.renderProgressBubble(bubble),/aria-busy="true"/);
});
test('live tool and reasoning appear in bubble, never raw HTML',()=>{
  const c=fixture(); c.state.running=true;
  c.syncChatProgress({status:'running',title:'正在执行', tools:[{name:'run_command',status:'running',arguments:{command:'python -m unittest'}}],
    thinking:[{agent:'planner',text:'<script>bad()</script>'}]});
  const html=c.renderProgressBubble(c.currentProgressBubble());
  assert.match(html,/python -m unittest/);assert.match(html,/执行中/);
  assert.match(html,/Thinking/);assert.doesNotMatch(html,/<script>/);
  c.syncChatProgress({status:'completed',title:'完成'});
  assert.match(c.renderProgressBubble(c.currentProgressBubble()),/aria-busy="false"/);
});
test('new turn gets its own bubble, previous turn remains unchanged',()=>{
  const c=fixture(); const first=c.currentProgressBubble(true);
  c.state.messages.push({agent:'user',text:'next'});
  assert.equal(c.currentProgressBubble(),null);
  assert.notEqual(c.currentProgressBubble(true),first);
});
test('reload recovers completed activity from the selected run snapshot',()=>{
  const c=fixture();c.state.runId='selected-run';c.state.running=false;
  c.syncChatProgress({status:'completed',title:'Completed',tools:[{name:'read_file',status:'completed'}]});
  assert.match(c.renderProgressBubble(c.currentProgressBubble()),/read_file/);
});
test('context deadline aborts stalled request, no endless startup', async()=>{
  const c=fixture();c.request=(url,{signal})=>new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(new Error('aborted'))));
  await assert.rejects(c.requestWithDeadline('/api/context/plan',{},5),/aborted/);
});

test('live bubble stays after streamed answers without reordering transcript state',()=>{
  const c=fixture(); const bubble=c.currentProgressBubble(true);
  bubble.progress.title='ACTIVE_STAGE';
  c.state.messages.push({kind:'message',agent:'agent',text:'ANSWER_TEXT',events:[],at:Date.now()});
  let html='';
  const container={scrollTop:0,scrollHeight:100,clientHeight:100,querySelectorAll:()=>[],
    insertAdjacentHTML:(_,value)=>{html=value;}};
  Object.assign(c,{$:id=>id==='messages'?container:{style:{}},messageRenderSignature:()=> 'changed',
    renderUserMessage:()=> 'USER', renderMarkdown:v=>v, isRoutineProcess:()=>false, configLabel:()=>''});
  c.state.messages[0].events=[];
  const start=source.indexOf('  function renderMessagesNow(');
  vm.runInContext(source.slice(start,source.indexOf('\n  }',start)+4),c);
  c.renderMessagesNow();
  assert.ok(html.indexOf('ACTIVE_STAGE')>html.indexOf('ANSWER_TEXT'));
  assert.equal(c.state.messages[1],bubble);
});
