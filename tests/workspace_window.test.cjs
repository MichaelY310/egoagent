const test = require('node:test');
const assert = require('node:assert/strict');
const { createWorkspaceWindowOpener } = require('../void_extension/egoagent-dag-chat/media/workspace-window');
const url = 'http://127.0.0.1:8880/api/remote/open/8689fe9b71105847';
function fixture() {
  const elements = [];
  const document = {activeElement: null};
  document.createElement = tag => {
    const element = {tag, style:{}, events:{}, children:[], setAttribute() {},
      append(...children) {this.children.push(...children);}, remove(){this.removed=true;},
      focus(){document.activeElement=this;}, addEventListener(name,handler){this.events[name]=handler;} };
    elements.push(element);return element;
  };
  document.body = document.createElement('body');
  const navigations = [];
  const host = {document,location:{assign:u=>navigations.push(u)}, open:()=>null};
  return {host, elements, navigations, open:createWorkspaceWindowOpener(host),
    click:label=>elements.find(e=>e.tag==='button'&&e.textContent===label).events.click()};
}
test('blocked popup keeps actionable dialog; current-tab fallback really navigates', async () => {
  const f=fixture();const result=f.open(url, '<b>WSL</b>');
  f.click('在新页面打开');
  assert.ok(f.elements.some(e=>e.textContent?.includes('浏览器阻止')));
  assert.equal(f.navigations.length,0);
  f.click('在当前页面打开');
  assert.deepEqual(f.navigations,[url]);
  assert.equal(await result,'navigating');
});
test('explicit new-tab click opens correct URL and detaches opener', async () => {
  const f=fixture();const target={opener:'original',location:{replace:u=>f.navigations.push(u)}};
  let calls=0;f.host.open=(destination)=>{calls++;f.navigations.push(destination);return target;};
  const result=f.open(url,'WSL');
  assert.equal(calls,0, 'must not lose user activation in an asynchronous extension callback');
  f.click('在新页面打开');
  assert.equal(await result,'opened');assert.equal(target.opener,null);
  assert.deepEqual(f.navigations,[url]);
});
test('cancel makes no navigation, desktop keeps native window handling', async () => {
  const f=fixture();const result=f.open(url,'WSL');f.click('暂不打开');
  assert.equal(await result,'cancelled');assert.equal(f.navigations.length,0);
  f.host.chrome={webview:{}};
  assert.equal(await f.open(url),'external');
});
test('reject external destinations, credentials, auth tokens and arbitrary paths', () => {
  const f=fixture();
  for(const target of ['https://evil.example/','javascript:alert(1)','http://127.0.0.1.evil.test/',
    'http://user@127.0.0.1/','http://127.0.0.1/path','http://127.0.0.1/?token=secret',
    url+'#secret',url.replace('8689fe9b71105847','wrong')]) {
    assert.throws(()=>f.open(target));
  }
});
