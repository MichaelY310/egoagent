const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path').posix;
const source = fs.readFileSync('void_extension/egoagent-dag-chat/extension-v21.js', 'utf8');

// Exercise the actual provider methods, not a second implementation of the parser.
function fixture(rootPath = '/home/me/project') {
  const uri = (scheme, authority, pathname) => ({scheme, authority, path: pathname,
    fsPath: pathname.replace(/^\/([A-Za-z]:\/)/, '$1'),
    toString() { return `${scheme}://${authority}${encodeURI(pathname)}`; }});
  const root = uri('vscode-remote', 'my-connection', rootPath);
  const reads = [];
  const replies = [];
  const vscode = {
    Uri: {
      from: value => uri(value.scheme, value.authority || '', value.path),
      parse(value) { const parsed = new URL(value); return uri(parsed.protocol.slice(0, -1), parsed.host, decodeURIComponent(parsed.pathname)); },
      file: value => uri('file', '', value.startsWith('/') ? value : '/' + value),
      joinPath: (base, ...parts) => uri(base.scheme, base.authority, path.join(base.path, ...parts)),
    },
    FileType: {File: 1, Directory: 2, SymbolicLink: 64},
    workspace: {
      workspaceFolders: [{uri: root, name: 'project'}],
      getWorkspaceFolder(value) { return value.scheme === root.scheme && value.authority === root.authority
        && (value.path === root.path || value.path.startsWith(root.path + '/')) ? {uri: root} : undefined; },
      fs: {
        async stat(value) { reads.push(value); return {type: value.path.endsWith('/docs') ? 2 : 1}; },
        async readDirectory() { return [['read me.md', 1]]; },
      },
      async openTextDocument(value) { return {getText: () => 'example\n', lineCount: 2, languageId: 'python'}; },
    },
  };
  const c = vm.createContext({vscode, console});
  for (const name of ['fsPathForBackend', 'normalizedFsPath', 'workspaceUriForPath', 'displayPath']) {
    const start = source.indexOf(`function ${name}(`);
    vm.runInContext(source.slice(start, source.indexOf('\n}', start) + 2), c);
  }
  const methods = ['droppedResourceStrings', 'contextForDroppedResource', 'resolveContextDrop'].map(name => {
    let start = source.indexOf(`  ${name}(`);
    if (start < 0) start = source.indexOf(`  async ${name}(`);
    return source.slice(start, source.indexOf('\n  }', start) + 4);
  }).join('\n');
  const provider = vm.runInContext(`new (class {${methods}})`, c);
  provider.view = {webview: {postMessage: message => replies.push(message)}};
  provider.contextForClipboardText = async () => null;
  return {provider, reads, replies};
}

test('CodeFiles and plain POSIX paths work for WSL/SSH, including spaces and Unicode', () => {
  const {provider} = fixture();
  assert.deepEqual(Array.from(provider.droppedResourceStrings({CodeFiles: JSON.stringify(['/home/me/project/中文 file.py', '/home/me/project/docs'])})),
    ['/home/me/project/中文 file.py', '/home/me/project/docs']);
  assert.deepEqual(Array.from(provider.droppedResourceStrings({'text/plain': '/home/me/project/file.py'})), ['/home/me/project/file.py']);
});
test('remote URI objects retain their authority; URI lists ignore comments', () => {
  const {provider} = fixture();
  const paths = provider.droppedResourceStrings({CodeEditors: JSON.stringify([{resource: {scheme: 'vscode-remote', authority: 'other-host', path: '/home/me/project/file.py'}}]),
    'text/uri-list': '# comment\nvscode-remote://my-connection/home/me/project/a.py\nfile:///home/me/project/b.py'});
  assert.deepEqual(Array.from(paths), ['vscode-remote://other-host/home/me/project/file.py', 'vscode-remote://my-connection/home/me/project/a.py', 'file:///home/me/project/b.py']);
});
test('Windows and UNC paths remain recognized without decoding path literals', () => {
  const {provider} = fixture();
  const values = ['C:\\repo\\file.py', '\\\\server\\share\\file.py', '/home/me/project/100%20done.py'];
  assert.deepEqual(Array.from(provider.droppedResourceStrings({CodeFiles: JSON.stringify(values)})), values);
});
test('Linux files and folders really resolve through the active remote workspace', async () => {
  const {provider, reads, replies} = fixture();
  await provider.resolveContextDrop({requestId: 'test', transfer: {CodeFiles: JSON.stringify(['/home/me/project/main.py', '/home/me/project/docs'])}});
  assert.equal(replies[0].error, '');
  assert.equal(replies[0].contexts.length, 2);
  assert.equal(replies[0].contexts[0].kind, 'file');
  assert.equal(replies[0].contexts[1].kind, 'folder');
  assert.match(replies[0].contexts[1].content, /docs\/read me.md/);
  assert.ok(reads.every(value => value.scheme === 'vscode-remote' && value.authority === 'my-connection'));
});
test('file URI is rebound to remote workspace; explicit foreign remote stays rejected', async () => {
  const {provider, reads} = fixture();
  assert.equal((await provider.contextForDroppedResource('file:///home/me/project/中文%20file.py')).kind, 'file');
  assert.equal(await provider.contextForDroppedResource('vscode-remote://other-host/home/me/project/main.py'), null);
  assert.equal(reads.length, 1);
});
test('out-of-workspace, traversal, remote sibling and unsafe URL do not read files', async () => {
  const {provider, reads} = fixture();
  for (const input of ['/etc/passwd', '/home/me/project-other/a.py', '/home/me/project/../../secret', 'https://example.com/x', 'command:delete']) {
    assert.equal(await provider.contextForDroppedResource(input), null, input);
  }
  assert.equal(reads.length, 0);
});
test('empty or unsupported drop returns an explicit error, not a stuck placeholder', async () => {
  const {provider, replies} = fixture();
  await provider.resolveContextDrop({requestId: 'empty', transfer: {}});
  assert.equal(replies[0].requestId, 'empty');
  assert.match(replies[0].error, /Workspace/);
  assert.equal(replies[0].contexts.length, 0);
});
