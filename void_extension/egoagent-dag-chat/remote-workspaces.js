const vscode = require('vscode');
const runtime = require('./connection-runtime');
const nativeFetch = globalThis.fetch.bind(globalThis);

function authenticatedFetch(input, options = {}) {
  if (!runtime.accessToken || new URL(typeof input === 'string' ? input : input.url).origin !== new URL(backendUrl()).origin) {
    return nativeFetch(input, options);
  }
  const headers = new Headers(options.headers || (input instanceof Request ? input.headers : undefined));
  headers.set('X-EgoAgent-Remote-Token', runtime.accessToken);
  return nativeFetch(input, { ...options, headers });
}

function backendUrl() {
  // A remote window must never inherit a local workspace's backend override.
  return (runtime.id ? runtime.backendUrl : vscode.workspace.getConfiguration('egoagent')
    .get('backendUrl', runtime.backendUrl || 'http://127.0.0.1:8765')).replace(/\/$/, '');
}

function webSocketUrl(apiUrl) {
  const url = new URL(apiUrl);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  url.port = String(Number(url.port || 8765) + 1);
  return url.toString().replace(/\/$/, '');
}

async function request(path, body) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 18000);
  try {
    const response = await authenticatedFetch(backendUrl() + '/api/remote/' + path, {
      signal: controller.signal,
      ...(body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}),
    });
    if (!(response.headers.get('content-type') || '').includes('json')) {
      throw new Error('当前后端还未更新远程功能，请重启 EgoAgent 服务并重新加载窗口');
    }
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || result.message || `HTTP ${response.status}`);
    return result;
  } finally { clearTimeout(timer); }
}

async function newConnection(kind) {
  const targets = await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: '检测 SSH/WSL 环境' },
    () => request('targets'));
  let target;
  if (kind === 'wsl') {
    if (!targets.wsl.length) throw new Error(targets.warning || '未发现 WSL 发行版。请先在 Windows 中安装 WSL/Ubuntu');
    target = await vscode.window.showQuickPick(targets.wsl, { title: '1/3 · 选择 WSL 发行版' });
  } else {
    const choice = await vscode.window.showQuickPick([
      ...targets.ssh.map(name => ({ label: name, target: name, description: '~/.ssh/config' })),
      { label: '输入 SSH Host / user@host…' },
    ], { title: '1/3 · 选择 SSH 主机', placeHolder: '使用已有 SSH 密钥和配置；首次连接请先在终端确认主机指纹' });
    if (!choice) return;
    target = choice.target || await vscode.window.showInputBox({ title: 'SSH Host', prompt: '如 ucsb、dev-server、alice@server；非默认端口请写入 SSH config', ignoreFocusOut: true });
  }
  if (!target) return;
  const workspace = await vscode.window.showInputBox({ title: '2/3 · 远程项目目录', value: '~/',
    prompt: '目标环境中的现有目录，如 /home/alice/myproject。编辑、终端、Agent 均在此环境工作。', ignoreFocusOut: true,
    validateInput: value => /^(\/|~\/)/.test(value) ? undefined : '请输入 Linux 路径，不是 C:\\…',
  });
  if (!workspace) return;
  const label = await vscode.window.showInputBox({ title: '3/3 · 连接名称',
    value: `${kind.toUpperCase()}: ${target} · ${workspace}`, ignoreFocusOut: true });
  if (!label) return;
  const profile = await request('connections', { kind, target, workspace, label });
  return connect(profile);
}

async function connect(profile) {
  const consent = await vscode.window.showWarningMessage(
    `连接 ${profile.label}`, { modal: true, detail:
      '首次将 EgoAgent 应用、Flow/Identity 和官方 Linux 编辑器安装到目标用户的 ~/.local/share/egoagent/connections/。约需 250 MB 磁盘，不使用 sudo，不上传项目或已有 Session。\n\nSSH 必须提前配置免交互认证并确认主机指纹。默认不复制 API Key；可以在远程 Workbench 设置中配置模型。' },
    '连接（不复制密钥）', '连接并复制模型配置');
  if (!consent) return;
  const includeModelConfig = consent === '连接并复制模型配置';
  if (includeModelConfig) {
    const confirm = await vscode.window.showWarningMessage('模型 API Key 将保存在目标机器上', {
      modal: true, detail: '仅在你信任该 SSH 主机及其管理员时继续。不会复制 SSH 密钥或其他环境变量。',
    }, '信任并复制');
    if (!confirm) return;
  }
  await request('connect', { id: profile.id, consent: true, includeModelConfig });
  await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: profile.label, cancellable: false },
    async progress => {
      const deadline = Date.now() + 12 * 60 * 1000;
      let lastMessage = '';
      while (Date.now() < deadline) {
        const { connections } = await request('connections');
        const current = connections.find(item => item.id === profile.id);
        if (!current) throw new Error('连接已被删除');
        if (current.message !== lastMessage) { progress.report({ message: current.message }); lastMessage = current.message; }
        if (current.state === 'error') throw new Error(current.message);
        if (current.state === 'connected') {
          await openWorkspaceWindow(current.url, profile.label);
          return;
        }
        await new Promise(resolve => setTimeout(resolve, 1200));
      }
      throw new Error('连接仍在准备，请重新打开 SSH/WSL 连接菜单查看状态');
    });
}

async function openWorkspaceWindow(url, label) {
  let result;
  try {
    result = await vscode.commands.executeCommand('egoagent.openWorkspaceWindow', url, label);
  } catch (error) {
    // Older remote installations might not have the renderer command yet.
    // Do not promise success: make the actual URL available for recovery.
    const action = await vscode.window.showWarningMessage(
      '工作区已就绪，但当前窗口需要重新加载后才能使用可靠的打开方式。', '尝试打开', '复制地址');
    if (action === '复制地址') { await vscode.env.clipboard.writeText(url); return; }
    if (action !== '尝试打开') return;
    result = 'external';
  }
  if (result === 'external') {
    const opened = await vscode.env.openExternal(vscode.Uri.parse(url));
    if (!opened) {
      const action = await vscode.window.showWarningMessage('窗口未能打开。可以复制地址手动打开。', '复制地址');
      if (action) await vscode.env.clipboard.writeText(url);
    }
  }
}

async function openRemoteWorkspaces() {
  try {
    if (runtime.id) {
      const action = await vscode.window.showInformationMessage(`当前运行位置：${runtime.label}`, { modal: true,
        detail: '文件、终端、Agent、Flow 和 Session 保存在此目标环境。返回本机不停止运行；断开连接请在本机 SSH/WSL 菜单选择此连接。' }, '返回本机');
      if (action) await openWorkspaceWindow(runtime.managerUrl || 'http://127.0.0.1:8880/', '本机 EgoAgent');
      return;
    }
    const { connections } = await request('connections');
    const choice = await vscode.window.showQuickPick([
      { label: '$(terminal-linux) 新建 WSL 项目连接', kind: 'wsl' },
      { label: '$(remote) 新建 SSH 项目连接', kind: 'ssh' },
      ...connections.map(profile => ({ label: profile.label, description: profile.state,
        detail: String(profile.message || '').replace(/\s+/g, ' ').slice(0, 180), profile })),
    ], { title: 'EgoAgent · SSH / WSL 工作区', matchOnDetail: true, placeHolder: '完整的远程 IDE + Agent，不只是打开远程终端' });
    if (!choice) return;
    if (choice.kind) return await newConnection(choice.kind);
    const profile = choice.profile;
    const action = await vscode.window.showQuickPick([
      profile.state === 'connected' ? '打开远程项目' : '连接 / 重试',
      ...(profile.state === 'connected' ? ['断开连接'] : []), '修改连接名称', '移除连接记录',
    ], { title: profile.label, placeHolder: profile.workspace });
    if (action === '打开远程项目') await openWorkspaceWindow(profile.url, profile.label);
    if (action === '连接 / 重试') await connect(profile);
    if (action === '断开连接') {
      if (await vscode.window.showWarningMessage('断开会停止该连接中的 Agent 与终端进程，请先保存文件。', { modal: true }, '断开')) {
        await request('disconnect', { id: profile.id });
        vscode.window.showInformationMessage('已断开；远程文件和 Session 保留，可再次连接');
      }
    }
    if (action === '修改连接名称') {
      const label = await vscode.window.showInputBox({ title: '连接名称', value: profile.label });
      if (label) await request('rename', { id: profile.id, label });
    }
    if (action === '移除连接记录') {
      if (await vscode.window.showWarningMessage('移除这条连接？远程项目、安装目录和 Session 不会删除。连接若还在运行则会断开。', { modal: true }, '移除')) {
        await request('remove', { id: profile.id });
      }
    }
  } catch (error) { vscode.window.showErrorMessage(`SSH/WSL：${error.message || error}`); }
}

function registerRemoteWorkspaces(context) {
  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 1000);
  status.text = runtime.id ? `$(remote) ${runtime.label}` : '$(remote) SSH / WSL';
  status.tooltip = runtime.id ? '文件、终端和 Agent 均在此目标环境执行；点击返回本机' : '连接远程项目：WSL 或 SSH';
  status.command = 'egoagent.openRemoteWorkspace';
  status.show();
  context.subscriptions.push(status, vscode.commands.registerCommand('egoagent.openRemoteWorkspace', openRemoteWorkspaces));
}

module.exports = { backendUrl, webSocketUrl, registerRemoteWorkspaces, openRemoteWorkspaces,
  fetch: authenticatedFetch, accessToken: runtime.accessToken || '', runtimeLabel: runtime.id ? runtime.label : '' };
