try {
(() => {
  const vscode = acquireVsCodeApi();
  const apiBase = document.body.dataset.api.replace(/\/$/, '');
  const wsUrl = document.body.dataset.ws.replace(/\/$/, '');
  const saved = vscode.getState() || {};

  const state = {
    harnesses: [],
    identities: [],
    config: null,
    harness: saved.harness || '',
    harnessFilter: saved.harnessFilter || '',
    showWorkers: saved.showWorkers === true,
    identity: saved.identity || '',
    bindings: saved.bindings || {},
    mode: saved.mode || 'agent',
    running: false,
    waitingForInput: false,
    currentNode: null,
    stepCount: 0,
    messagesCount: 0,
    messages: [],
    trace: [],
    tools: [],
    entered: new Set(),
    ws: null,
    pollBusy: false,
    runId: '',
    changeTransactionId: '',
    outputMessages: new Map(),
    localProposals: [],
    backendChanges: [],
    metrics: {},
    reviewIssues: [],
    editorContext: null,
    attachedContext: null,
    pastedContexts: [],
    pendingContextPastes: new Map(),
    attachRequested: false,
    completionEnabled: true,
    aiStatus: { configured: false, fallback: 'deterministic-local' },
    workbenchStatus: { running: false, status: 'idle', pendingChanges: 0, evolutionProposals: 0 },
    contextPlan: null,
    executionWorkspace: '',
    foreignExecution: null,
    editorContextRequests: new Map(),
    renderMessageTimer: null,
    renderForceBottom: false,
    messageRenderSignature: '',
    runtimeRenderSignature: '',
    pendingApproval: null,
    terminationKey: '',
    warningKeys: new Set(),
    runStatus: 'idle',
    liveRuns: [],
    liveRunsSignature: '',
    awaitingNewSession: false,
    activityText: '就绪 · 发送消息开始',
    activityKind: 'idle',
    security: null,
    sandbox: null,
    configExpanded: saved.configExpanded === true,
    lastComposerMutation: null,
    editingAttachmentId: '',
    lastReviewTransactionId: null,
  };

  const $ = (id) => document.getElementById(id);
  const escapeHtml = (value) => String(value ?? '')
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;').replaceAll("'", '&#39;');
  const safeHref = (value) => /^https?:\/\//i.test(String(value || '').trim()) ? String(value).trim() : '';
  function renderInlineMarkdown(value) {
    const code = [];
    let html = escapeHtml(value).replace(/`([^`\n]+)`/g, (_match, content) => {
      const token = `@@EGO_INLINE_CODE_${code.length}@@`;
      code.push('<code>' + content + '</code>');
      return token;
    });
    html = html.replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/gi, (_match, label, href) => {
      const safe = safeHref(href);
      return safe ? '<a href="' + escapeHtml(safe) + '" target="_blank" rel="noreferrer">' + label + '</a>' : label;
    });
    html = html.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/__([^_\n]+)__/g, '<strong>$1</strong>');
    html = html.replace(/(^|[\s(])\*([^*\n]+)\*(?=$|[\s).,!?:;])/g, '$1<em>$2</em>');
    code.forEach((item, index) => { html = html.replace(`@@EGO_INLINE_CODE_${index}@@`, item); });
    return html;
  }

  function renderMarkdown(value) {
    const source = String(value || '').replaceAll('\r\n', '\n');
    const blocks = [];
    let cursor = 0;
    const fence = /```([^\n`]*)\n([\s\S]*?)```/g;
    let match;
    const renderTextBlock = (text) => {
      const lines = String(text || '').split('\n');
      const output = [];
      let paragraph = [];
      let listType = '';
      let listItems = [];
      const flushParagraph = () => {
        if (paragraph.length) output.push('<p>' + paragraph.map(renderInlineMarkdown).join('<br>') + '</p>');
        paragraph = [];
      };
      const flushList = () => {
        if (listItems.length) output.push(`<${listType}>` + listItems.map((item) => '<li>' + renderInlineMarkdown(item) + '</li>').join('') + `</${listType}>`);
        listType = '';
        listItems = [];
      };
      for (const line of lines) {
        const heading = /^(#{1,4})\s+(.+)$/.exec(line);
        const bullet = /^\s*[-*+]\s+(.+)$/.exec(line);
        const ordered = /^\s*\d+[.)]\s+(.+)$/.exec(line);
        const quote = /^>\s?(.*)$/.exec(line);
        if (!line.trim()) { flushParagraph(); flushList(); continue; }
        if (heading) { flushParagraph(); flushList(); const level = heading[1].length; output.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`); continue; }
        if (bullet || ordered) {
          flushParagraph();
          const nextType = bullet ? 'ul' : 'ol';
          if (listType && listType !== nextType) flushList();
          listType = nextType;
          listItems.push((bullet || ordered)[1]);
          continue;
        }
        if (quote) { flushParagraph(); flushList(); output.push('<blockquote>' + renderInlineMarkdown(quote[1]) + '</blockquote>'); continue; }
        flushList();
        paragraph.push(line);
      }
      flushParagraph();
      flushList();
      return output.join('');
    };
    while ((match = fence.exec(source))) {
      blocks.push(renderTextBlock(source.slice(cursor, match.index)));
      blocks.push('<pre><code class="language-' + escapeHtml(match[1].trim()) + '">' + escapeHtml(match[2].replace(/\n$/, '')) + '</code></pre>');
      cursor = match.index + match[0].length;
    }
    blocks.push(renderTextBlock(source.slice(cursor)));
    return '<div class="markdown-body">' + blocks.join('') + '</div>';
  }
  const pretty = (value) => {
    if (typeof value === 'string') {
      try { return JSON.stringify(JSON.parse(value), null, 2); } catch { return value; }
    }
    try { return JSON.stringify(value, null, 2); } catch { return String(value); }
  };
  const countOf = (value) => Array.isArray(value) ? value.length : value && typeof value === 'object' ? Object.keys(value).length : 0;
  const casualPrompts = new Set([
    '你好', '您好', '嗨', 'hi', 'hello', 'hey', '在吗', '你在吗',
    '说话啊', '回复我', '回话', '你是谁', '谢谢', '谢谢你', '再见',
  ]);
  const isCasualPrompt = (value) => casualPrompts.has(String(value || '').trim().toLocaleLowerCase());
  function casualTurnText(text, pastedContexts = []) {
    const contexts = Array.isArray(pastedContexts) ? pastedContexts : [];
    let authoredText = String(text || '');
    for (const item of contexts) {
      if (item?.reference) authoredText = authoredText.replaceAll(item.reference, ' ');
    }
    authoredText = authoredText.replace(/\s+/g, ' ').trim();
    if (isCasualPrompt(authoredText) && contexts.length === 0) return authoredText;

    // Ctrl+V intentionally creates a visible attachment reference.  A single
    // plain-text clipboard containing only “你好” must still be semantically
    // identical to typing “你好”; otherwise the marker itself sends the
    // flagship Harness into capability discovery and repository inspection.
    if (!authoredText && contexts.length === 1 && contexts[0]?.kind === 'clipboard') {
      const clipboardText = String(contexts[0]?.content || '').trim();
      if (isCasualPrompt(clipboardText)) return clipboardText;
    }
    return '';
  }
  const persist = () => vscode.setState({
    harness: state.harness,
    harnessFilter: state.harnessFilter,
    showWorkers: state.showWorkers,
    identity: state.identity,
    bindings: state.bindings,
    mode: state.mode,
    configExpanded: state.configExpanded,
  });

  function canonicalWorkspace(value) {
    let normalized = String(value || '').trim().replaceAll('\\', '/');
    normalized = normalized.replace(/^\/([A-Za-z]:\/)/, '$1').replace(/\/+$/, '');
    return /^[A-Za-z]:\//.test(normalized) ? normalized.toLowerCase() : normalized;
  }

  function currentWorkspace() {
    return canonicalWorkspace(state.editorContext?.workspacePath);
  }

  function sortedRecord(value) {
    return Object.fromEntries(Object.entries(value || {}).sort(([left], [right]) => left.localeCompare(right)));
  }

  function executionMatchesSelection(execution) {
    if (state.runId && String(execution?.run_id || '') !== String(state.runId)) return false;
    const workspace = currentWorkspace();
    if (!workspace || canonicalWorkspace(execution?.workspace) !== workspace) return false;
    if (String(execution?.harness || '') !== String(state.harness || '')) return false;
    if (String(execution?.mode || 'agent') !== String(state.mode || 'agent')) return false;
    if (state.config && JSON.stringify(sortedRecord(execution?.agents)) !== JSON.stringify(sortedRecord(buildAgents()))) return false;
    return true;
  }

  function shouldAdoptExecutionSnapshot(currentRunId, execution) {
    return Boolean(
      String(currentRunId || '').trim()
      || execution?.running
      || execution?.waiting_for_input
    );
  }

  function resetConversationForWorkspace() {
    state.running = false;
    state.currentNode = null;
    state.stepCount = 0;
    state.messagesCount = 0;
    state.messages = [];
    state.trace = [];
    state.tools = [];
    state.entered = new Set();
    state.runId = '';
    state.changeTransactionId = '';
    state.outputMessages.clear();
    state.contextPlan = null;
    state.pastedContexts = [];
    state.pendingContextPastes.clear();
    state.executionWorkspace = '';
    state.foreignExecution = null;
    state.pendingApproval = null;
    state.terminationKey = '';
    state.runStatus = 'idle';
    state.awaitingNewSession = false;
    state.activityText = '就绪 · 发送消息开始';
    state.activityKind = 'idle';
    postBackendReviewSnapshot();
    renderMessages({ forceBottom: true });
    renderContextPlan();
    renderRuntime();
  }

  function detachFromExecutionSelection() {
    // A mode/Harness/Identity change defines a different Agent instance. Keep
    // the visible conversation, but detach runtime state so a late cancelled
    // snapshot from the previous run cannot become the new run's first error.
    state.running = false;
    state.waitingForInput = false;
    state.currentNode = null;
    state.stepCount = 0;
    state.messagesCount = state.messages.length;
    state.trace = [];
    state.tools = [];
    state.entered = new Set();
    state.runId = '';
    state.changeTransactionId = '';
    state.outputMessages.clear();
    state.executionWorkspace = '';
    state.foreignExecution = null;
    state.pendingApproval = null;
    state.terminationKey = '';
    state.runStatus = 'idle';
    state.awaitingNewSession = true;
    state.activityText = '配置已切换 · 下一条消息会启动新的 Agent 运行';
    state.activityKind = 'idle';
    postBackendReviewSnapshot();
    renderRuntime();
  }

  function requestFreshEditorContext(timeoutMs = 2000) {
    const requestId = `context-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        state.editorContextRequests.delete(requestId);
        resolve(state.editorContext);
      }, timeoutMs);
      state.editorContextRequests.set(requestId, { resolve, timer });
      vscode.postMessage({ type: 'requestEditorContext', requestId });
    });
  }

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(apiBase + path, {
      ...options,
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    });
  } catch (error) {
    const detail = error instanceof Error && error.message && error.message !== 'Failed to fetch'
      ? ` (${error.message})`
      : '';
    throw new Error(`无法连接 EgoAgent 后端 ${apiBase}。请确认 Studio 服务已启动；如果刚更新过代码，请重启服务后重试。${detail}`);
  }
    const text = await response.text();
    let data;
    try { data = text ? JSON.parse(text) : {}; } catch { data = text; }
    if (!response.ok) {
      const error = new Error((data && data.error) || text || response.statusText);
      error.status = response.status;
      throw error;
    }
    return data;
  }

  function toast(message, isError = false) {
    const el = $('toast');
    el.textContent = message;
    el.className = 'toast show' + (isError ? ' error' : '');
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => { el.className = 'toast'; }, 2600);
    if (isError) vscode.postMessage({ type: 'notifyError', message });
  }

  function setConnection(online, label) {
    const el = $('connection');
    el.className = 'connection ' + (online ? 'online' : 'offline');
    el.innerHTML = '<span></span>' + escapeHtml(label || (online ? '已连接' : '离线'));
  }

  function renderAIStatus() {
    const badge = document.querySelector('.local-badge');
    if (!badge) return;
    if (state.aiStatus?.configured) {
      const health = state.aiStatus.health;
      const capabilities = state.aiStatus.capabilities || {};
      const available = Object.entries(capabilities).filter(([, enabled]) => enabled).map(([role]) => role);
      badge.textContent = `${String(state.aiStatus.provider || 'AI').toUpperCase()}${health === false ? ' DEGRADED' : ''} · ${state.aiStatus.model || 'MODEL'}`;
      badge.title = health === false
        ? `模型探针失败；AI 请求已在发送前禁用，本地能力仍可用。${state.aiStatus.last_probe?.error || ''}`
        : `模型功能已连接：${state.aiStatus.base_url || ''}${available.length ? `\n能力：${available.join(', ')}` : '\n尚未运行能力探针'}`;
    } else {
      badge.textContent = 'LOCAL FALLBACK';
      badge.title = '模型未配置或后端不可用，编辑功能将使用本地降级能力';
    }
  }

  function renderWorkbenchStatus() {
    const el = $('workbenchStatus');
    if (!el) return;
    const status = state.workbenchStatus || {};
    const pending = Number(status.pendingChanges || 0);
    const proposals = Number(status.evolutionProposals || 0);
    const visible = Boolean(status.running || pending || proposals);
    el.hidden = !visible;
    el.classList.toggle('running', Boolean(status.running));
    el.classList.toggle('paused', Boolean(status.paused));
    const scopeLabel = status.scope === 'evaluate' ? '评测' : status.scope === 'evolution' ? '进化' : 'Agent';
    const label = status.running
      ? `${scopeLabel}${status.waitingForInput ? '等待输入' : status.paused ? '已暂停' : '运行中'}`
      : pending ? `${pending} 个代码块待审` : `${proposals} 个进化提案`;
    el.querySelector('strong').textContent = label;
    el.querySelector('small').textContent = status.currentNode || status.harness || (pending ? '点击打开改动审阅' : '点击打开进化实验室');
  }

  function normalizeNames(values) {
    if (!Array.isArray(values)) return [];
    return values.map((value) => typeof value === 'string' ? value : value && value.name).filter(Boolean);
  }

  async function loadCatalog() {
    try {
      const [harnesses, identities] = await Promise.all([
        request('/api/harnesses'),
        request('/api/identities'),
      ]);
      state.harnesses = normalizeNames(harnesses);
      state.identities = normalizeNames(identities);
      if (!state.harness || !state.harnesses.includes(state.harness)) {
        state.harness = state.harnesses.includes('react_single') ? 'react_single' : (state.harnesses[0] || '');
      }
      if (!state.identity || !state.identities.includes(state.identity)) {
        state.identity = state.identities.includes('dante') ? 'dante' : (state.identities[0] || '');
      }
      renderSelectors();
      if (state.harness) await loadHarness(state.harness);
      setConnection(true, '已连接');
      persist();
    } catch (error) {
      setConnection(false, '后端不可用');
      toast('无法连接 EgoAgent：' + error.message, true);
    }
  }

  function renderSelectors() {
    const query = state.harnessFilter.trim().toLowerCase();
    const matches = (name) => !query || name.toLowerCase().includes(query);
    const groups = [
      ['开源复刻（可直接运行）', state.harnesses.filter((name) => name.endsWith('_replica') && matches(name))],
      ['基础 Harness', state.harnesses.filter((name) => !name.endsWith('_replica') && !name.endsWith('_worker') && matches(name))],
      ['内部 Worker', state.showWorkers ? state.harnesses.filter((name) => name.endsWith('_worker') && matches(name)) : []],
    ];
    const visible = new Set(groups.flatMap(([, names]) => names));
    if (state.harness && !visible.has(state.harness)) groups.unshift(['当前选择', [state.harness]]);
    $('harnessSelect').innerHTML = groups
      .filter(([, names]) => names.length)
      .map(([label, names]) => '<optgroup label="' + escapeHtml(label) + '">' + names
        .map((name) => '<option value="' + escapeHtml(name) + '">' + escapeHtml(name) + '</option>').join('') + '</optgroup>')
      .join('');
    $('identitySelect').innerHTML = state.identities.map((name) => '<option value="' + escapeHtml(name) + '">' + escapeHtml(name) + '</option>').join('');
    $('harnessSelect').value = state.harness;
    $('identitySelect').value = state.identity;
    $('harnessFilter').value = state.harnessFilter;
    $('showWorkers').checked = state.showWorkers;
    const visibleCount = groups.reduce((count, [, names]) => count + names.length, 0);
    $('harnessCount').textContent = query || state.showWorkers
      ? `${Math.min(visibleCount, state.harnesses.length)} / ${state.harnesses.length}`
      : `${state.harnesses.filter((name) => !name.endsWith('_worker')).length} 个可运行`;
    const modeLabel = ({ chat: 'Chat', plan: 'Plan', agent: 'Agent', debug: 'Debug', evolve: 'Evolve', evaluate: 'Evaluate' })[state.mode] || state.mode;
    $('agentConfigSummary').textContent = `${modeLabel} · ${state.harness || '未选 Harness'} · ${state.identity || '未选 Identity'}`;
  }

  async function loadHarness(name) {
    state.harness = name;
    state.config = await request('/api/harness/' + encodeURIComponent(name));
    const description = state.config.description || '无描述';
    const nodeCount = Object.keys(state.config.pipeline?.nodes || {}).length;
    $('harnessMeta').textContent = description + ' · ' + nodeCount + ' 个节点';
    renderBindings();
    renderDag();
    renderSelectors();
    persist();
  }

  function renderBindings() {
    const slots = state.config?.slots || {};
    const entries = Object.entries(slots);
    if (!entries.length) {
      $('slotBindings').innerHTML = '<div class="muted">此 Harness 没有命名 slot，将使用默认 Identity。</div>';
      return;
    }
    $('slotBindings').innerHTML = entries.map(([slot, def]) => {
      const selected = state.bindings[slot] || def.identity || state.identity;
      const options = state.identities.map((name) => '<option value="' + escapeHtml(name) + '"' + (name === selected ? ' selected' : '') + '>' + escapeHtml(name) + '</option>').join('');
      return '<label class="slot-row"><span title="' + escapeHtml(def.description || slot) + '">' + escapeHtml(slot) + (def.required ? ' *' : '') + '</span><select data-slot="' + escapeHtml(slot) + '">' + options + '</select></label>';
    }).join('');
    document.querySelectorAll('[data-slot]').forEach((select) => {
      select.addEventListener('change', () => {
        detachFromExecutionSelection();
        state.bindings[select.dataset.slot] = select.value;
        persist();
      });
    });
  }

  function renderDag() {
    const nodes = state.config?.pipeline?.nodes || {};
    $('dagNodes').innerHTML = Object.entries(nodes).map(([id, node]) => {
      const classes = ['dag-node'];
      if (state.entered.has(id)) classes.push('entered');
      if (state.currentNode === id) classes.push('current');
      return '<span class="' + classes.join(' ') + '" title="' + escapeHtml(node.op || '') + '">' + escapeHtml(id) + '</span>';
    }).join('');
  }

  function buildAgents() {
    const slots = state.config?.slots || {};
    const agents = {};
    for (const [slot, def] of Object.entries(slots)) {
      const identity = state.bindings[slot] || def.identity || state.identity;
      if (def.required && !identity) throw new Error('必须为 slot “' + slot + '” 绑定 Identity');
      agents[slot] = 'identity/' + (identity || slot);
    }
    return agents;
  }

  function runQuery(runId = state.runId) {
    return runId ? '?run_id=' + encodeURIComponent(runId) : '';
  }

  function renderSessionTabs() {
    const container = $('sessionTabs');
    if (!container) return;
    const runs = Array.isArray(state.liveRuns) ? state.liveRuns : [];
    if (!runs.length) {
      container.innerHTML = '<span class="session-empty">新 Session</span>';
      return;
    }
    container.innerHTML = runs.map((run) => {
      const active = String(run.run_id || '') === String(state.runId || '');
      const status = run.pending_approval || run.waiting_for_input ? 'waiting'
        : run.running ? 'running' : run.status === 'error' ? 'error' : 'done';
      const label = run.session_name || run.harness || String(run.run_id || '').slice(-8);
      const title = `${label}\n${run.status || (run.running ? 'running' : 'completed')} · ${run.mode || 'agent'}\n${run.run_id || ''}`;
      return '<button class="session-pill ' + status + (active ? ' active' : '') + '" data-session-run="' + escapeHtml(run.run_id || '') + '" title="' + escapeHtml(title) + '"><i></i><span>' + escapeHtml(label) + '</span></button>';
    }).join('');
    container.querySelectorAll('[data-session-run]').forEach((button) => {
      button.addEventListener('click', () => activateExecutionSession(button.dataset.sessionRun));
    });
  }

  async function refreshExecutionSessions() {
    const workspace = state.editorContext?.workspacePath || '';
    if (!workspace) return;
    try {
      const payload = await request('/api/execution/runs?workspace=' + encodeURIComponent(workspace));
      const runs = Array.isArray(payload?.runs) ? payload.runs : [];
      const signature = runs.map((run) => [run.run_id, run.status, run.running ? 1 : 0, run.waiting_for_input ? 1 : 0, run.step_count, run.session_name].join(':')).join('|');
      if (signature === state.liveRunsSignature) return;
      state.liveRunsSignature = signature;
      state.liveRuns = runs;
      renderSessionTabs();
    } catch {
      // The normal connection indicator already reports backend failures.
    }
  }

  async function activateExecutionSession(runId) {
    if (!runId || String(runId) === String(state.runId || '')) return;
    try {
      const execution = await request('/api/execution/state?run_id=' + encodeURIComponent(runId));
      state.messages = [];
      state.outputMessages.clear();
      state.trace = [];
      state.tools = [];
      state.entered = new Set();
      state.runId = String(runId);
      state.awaitingNewSession = false;
      state.mode = execution.mode || 'agent';
      const identities = Object.fromEntries(Object.entries(execution.agents || {}).map(([slot, value]) => [
        slot,
        String(value || '').replaceAll('\\', '/').split('/').filter(Boolean).pop() || '',
      ]));
      state.bindings = identities;
      state.identity = Object.values(identities)[0] || state.identity;
      await loadHarness(execution.harness || state.harness);
      $('modeSelect').value = state.mode;
      applyExecutionState(execution);
      persist();
      renderMessages({ forceBottom: true });
      renderSessionTabs();
      toast('已切换 Session；其他 Session 会继续在后台运行');
    } catch (error) {
      toast('切换 Session 失败：' + error.message, true);
    }
  }

  function startFreshSession() {
    resetConversationForWorkspace();
    state.awaitingNewSession = true;
    state.liveRunsSignature = '';
    renderSessionTabs();
    $('prompt').focus();
    toast('已打开新 Session；发送消息后才会启动 Agent');
  }

  function activeReviewTransactionId() {
    const explicit = String(state.changeTransactionId || '').trim();
    if (explicit) return explicit;
    if (!state.running && !state.waitingForInput) return '';
    const pending = state.backendChanges.filter((change) => (
      change?.transaction_id
      && (change.hunks || []).some((hunk) => hunk.status === 'pending')
    )).sort((left, right) => (
      Number(right.updated_at || right.timestamp || right.index || 0)
      - Number(left.updated_at || left.timestamp || left.index || 0)
    ));
    return String(pending[0]?.transaction_id || '');
  }

  function postBackendReviewSnapshot(force = false) {
    const activeTransactionId = activeReviewTransactionId();
    if (!force && state.lastReviewTransactionId === activeTransactionId) return;
    state.lastReviewTransactionId = activeTransactionId;
    vscode.postMessage({
      type: 'backendChangesSnapshot',
      changes: state.backendChanges,
      activeTransactionId,
    });
  }

  function workspaceQuery() {
    const workspace = state.editorContext?.workspacePath || '';
    return workspace ? '?workspace=' + encodeURIComponent(workspace) : '';
  }

  function runBody(payload = {}) {
    return JSON.stringify(state.runId ? { ...payload, run_id: state.runId } : payload);
  }

  async function startExecution(silent = false) {
    if (!state.harness) throw new Error('请先选择 Harness');
    const workspace = state.editorContext?.workspacePath || '';
    if (!canonicalWorkspace(workspace)) throw new Error('Void 尚未提供当前工作区，请打开项目文件后重试');
    const identityTargets = [...new Set(Object.values(buildAgents()).map((value) => String(value).replaceAll('\\', '/').split('/').filter(Boolean).pop()).filter(Boolean))];
    let existing = null;
    if (state.runId) {
      try {
        existing = await request('/api/execution/state' + runQuery());
      } catch (error) {
        // A restarted backend legitimately forgets its in-memory live-run
        // handle.  The persisted Session remains available in Portfolio.
        if (Number(error?.status) !== 404) throw error;
      }
    }
    if (existing && executionMatchesSelection(existing) && existing.running) {
      applyExecutionState(existing);
      return existing;
    }
    // A different Session in this workspace may still be running.  Starting a
    // new one must not cancel it; the session strip is the explicit switcher.
    const result = await request('/api/execution/start', {
      method: 'POST',
      body: JSON.stringify({
        harness: state.harness,
        agents: buildAgents(),
        workspace,
        mode: state.mode,
        mutation_targets: state.mode === 'evolve' ? [state.harness, ...identityTargets] : [],
      }),
    });
    state.runId = String(result.run_id || result.state?.run_id || '');
    state.awaitingNewSession = false;
    state.changeTransactionId = String(result.change_transaction_id || result.state?.change_transaction_id || '');
    postBackendReviewSnapshot();
    state.running = true;
    state.waitingForInput = false;
    state.executionWorkspace = canonicalWorkspace(workspace);
    state.foreignExecution = null;
    state.currentNode = null;
    state.stepCount = 0;
    state.messagesCount = 0;
    state.trace = [];
    state.tools = [];
    state.entered = new Set();
    state.liveRunsSignature = '';
    void refreshExecutionSessions();
    renderRuntime();
    if (!silent) toast('DAG 已启动');
    return result;
  }

  async function stopExecution() {
    await request('/api/execution/stop', { method: 'POST', body: runBody() });
    state.running = false;
    state.waitingForInput = false;
    renderRuntime();
    toast('已请求停止 DAG');
  }

  function isWaiting() {
    const op = state.currentNode && state.config?.pipeline?.nodes?.[state.currentNode]?.op;
    return state.waitingForInput || op === '等待输入' || op === '输入';
  }

  async function waitUntilReadyForInput(timeoutMs = 15000) {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      const execution = await request('/api/execution/state' + runQuery());
      applyExecutionState(execution);
      if (isWaiting()) return;
      if (!state.running) {
        const failure = execution.termination?.failure || {};
        const message = failure.message || execution.termination?.message;
        const action = failure.action || execution.termination?.action;
        throw new Error([
          message ? `Agent 启动失败：${message}` : 'DAG 在进入等待输入节点前结束',
          action,
        ].filter(Boolean).join('\n'));
      }
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    throw new Error('DAG 尚未到达等待输入节点，请在“运行”页检查执行轨迹');
  }

  async function buildContextPlan(query, pastedContexts = state.pastedContexts) {
    const context = state.attachedContext;
    const workspaceContext = context?.workspacePath ? context : state.editorContext;
    if (!workspaceContext?.workspacePath) return null;
    const explicit = (pastedContexts || []).map((item, index) => ({
      kind: item.kind === 'terminal' ? 'terminal' : item.kind === 'selection' ? 'selection' : item.kind === 'file' ? 'file' : item.kind === 'workspace' ? 'workspace' : 'clipboard',
      title: item.title,
      path: item.path || '',
      start_line: item.startLine || undefined,
      end_line: item.endLine || undefined,
      content: item.content,
      metadata: {
        language: item.language || 'text', source: item.kind === 'file' ? 'drag-drop' : 'clipboard', terminal: item.terminalName || undefined,
        reference: item.reference || '', attachment_order: index + 1,
      },
    }));
    if (context?.available && context.fileExcerpt) {
      explicit.push({
        kind: 'file', title: `Current file ${context.path}`, path: context.path,
        start_line: context.excerptStartLine, end_line: context.excerptEndLine,
        content: context.fileExcerpt, revision: String(context.documentVersion || ''),
      });
    }
    if (context?.selectionText) {
      explicit.unshift({
        kind: 'selection', title: `Selected code in ${context.path}`, path: context.path,
        start_line: context.line, content: context.selectionText,
      });
    }
    const pendingChanges = (state.backendChanges || []).filter((change) => ['pending', 'partial', 'conflict'].includes(change.status)).slice(0, 12);
    const recentTools = (state.tools || []).slice(-8);
    return request('/api/context/plan', {
      method: 'POST',
      body: JSON.stringify({
        workspace: workspaceContext.workspacePath,
        query,
        token_budget: 12000,
        explicit,
        diagnostics: context?.diagnostics || [],
        definitions: context?.definitions || [],
        references: context?.references || [],
        diff: pendingChanges.length ? { title: 'Pending agent changes', content: JSON.stringify(pendingChanges) } : null,
        terminal: recentTools.length ? { title: 'Recent tool and terminal results', content: JSON.stringify(recentTools) } : null,
        include_repo_map: true,
        retrieval_mode: 'auto',
      }),
    });
  }

  async function sendPrompt() {
    const input = $('prompt');
    const text = composerText().trim();
    if (!text) return;
    if (state.pendingContextPastes.size) {
      toast('附件仍在识别，请等正文中的“附件识别中”变成文件名后再发送', true);
      return;
    }
    if (state.pendingApproval) {
      toast('请先在审批卡中选择“允许一次”或“拒绝”', true);
      return;
    }
    const pastedContexts = state.pastedContexts.slice();
    const casualText = casualTurnText(text, pastedContexts);
    const requestText = casualText || text;
    clearComposer();
    addMessage('user', text, pastedContexts);
    const commandMatch = /^\/(mock|review|edit|run|map|preview|commit)(?:\s+([\s\S]*))?$/i.exec(text);
    if (commandMatch) {
      const command = commandMatch[1].toLowerCase();
      const argument = (commandMatch[2] || '').trim();
      if (command === 'mock') vscode.postMessage({ type: 'mockEdit', mode: argument || 'maintainability' });
      if (command === 'review') vscode.postMessage({ type: 'localReview' });
      if (command === 'edit') vscode.postMessage({ type: 'inlineEdit', instruction: argument });
      if (command === 'run') vscode.postMessage({ type: 'terminalCommand', command: argument });
      if (command === 'map') vscode.postMessage({ type: 'codeMap' });
      if (command === 'preview') vscode.postMessage({ type: 'preview' });
      if (command === 'commit') vscode.postMessage({ type: 'commitMessage' });
      $('composerHint').textContent = '已交给 Void 本地能力处理';
      input.focus();
      return;
    }
    $('send').disabled = true;
    setAgentActivity(state.running ? '正在把消息交给当前 DAG…' : '正在读取编辑器状态并启动 DAG…', 'running');
    try {
      await requestFreshEditorContext();
      await startExecution(true);
      if (!isWaiting()) await waitUntilReadyForInput();
      const context = state.attachedContext;
      let contextBlock = '';
      try {
        // A greeting should remain a two-message chat turn. Retrieving a repo
        // map for "你好" biases small models into reopening the previous task
        // and needlessly enters the capability/tool loop.
        state.contextPlan = casualText ? null : await buildContextPlan(text, pastedContexts);
        renderContextPlan();
        if (state.contextPlan?.prompt) {
          const attachmentGuide = pastedContexts.length
            ? 'The user message contains inline attachment references. Match each reference attribute below to the exact position where it appears in the message.\n'
            : '';
          contextBlock = '\n\n[EgoAgent planned context]\n' + attachmentGuide + state.contextPlan.prompt;
        }
      } catch {
        const pastedBlock = pastedContexts.map((item) => (
          `\n\n[EgoAgent pasted context ${item.reference || ''}: ${item.title}]\n` +
          `\`\`\`${item.language || 'text'}\n${item.content}\n\`\`\``
        )).join('');
        contextBlock = (context?.available
          ? '\n\n[EgoAgent editor context]\n@file ' + context.path + ':' + context.line
            + (context.selectionText ? '\n@selection\n' + context.selectionText : '')
            + (context.symbols?.length ? '\n@symbols ' + context.symbols.slice(0, 15).map((item) => item.name).join(', ') : '')
          : '') + pastedBlock;
      }
      await request('/api/execution/input', { method: 'POST', body: runBody({ text: requestText + contextBlock }) });
      state.pastedContexts = [];
      renderEditorContext();
      setAgentActivity('任务已收到 · 正在进入第一个 DAG 节点…', 'running');
    } catch (error) {
      addEvent('system', 'error', '发送失败', error.message);
      setAgentActivity('发送失败 · 请查看错误详情', 'error');
      toast(error.message, true);
    } finally {
      $('send').disabled = false;
      input.focus();
    }
  }

  function addMessage(agent, text, contexts = []) {
    const last = state.messages[state.messages.length - 1];
    if (agent !== 'user' && last && last.kind === 'message' && last.agent === agent && !last.sealed) {
      last.text += text || '';
    } else {
      state.messages.push({ kind: 'message', agent, text: text || '', contexts: contexts || [], at: Date.now(), sealed: agent === 'user', events: [] });
    }
    renderMessages({ forceBottom: agent === 'user' });
  }

  function addEvent(agent, type, title, result, detail = null) {
    let message = state.messages[state.messages.length - 1];
    if (!message || message.kind !== 'message' || message.agent !== agent || message.sealed) {
      message = { kind: 'message', agent, text: '', at: Date.now(), sealed: false, events: [] };
      state.messages.push(message);
    }
    message.events.push({ type, title, result, detail });
    message.sealed = true;
    if (type === 'tool') {
      state.tools.unshift({ title, result, at: Date.now() });
      state.tools = state.tools.slice(0, 30);
    }
    renderMessages();
    renderRuntime();
  }

  function messageRenderSignature() {
    return state.messages.map((message) => [
      message.backendKey || '',
      message.agent || '',
      String(message.text || '').length,
      String(message.text || '').slice(-24),
      message.events?.length || 0,
      message.contexts?.map((item) => `${item.id || item.title}:${String(item.content || '').length}`).join(',') || '',
      message.sealed ? 1 : 0,
    ].join(':')).join('|');
  }

  function processSummary(message) {
    const tools = (message.events || []).filter((event) => event.type === 'tool');
    const subflows = (message.events || []).filter((event) => event.type === 'sub');
    if (tools.length) {
      const names = tools.map((event) => String(event.title || '').replace(/^↳\s*/, '').replace(/^🔧\s*/, '')).join('、');
      return `已完成 ${tools.length} 个工具调用${names ? ` · ${names}` : ''}`;
    }
    if (subflows.length) return `子 Agent 过程 · ${subflows.length} 条事件`;
    if (message.agent && message.agent !== 'agent') return `${message.agent} · 内部过程`;
    return 'Agent 中间过程';
  }

  function isRoutineProcess(message) {
    const events = message.events || [];
    const publicAgents = new Set(Object.keys(state.config?.slots || {}));
    const isInternalWorker = publicAgents.size > 0
      && !publicAgents.has(message.agent)
      && !['user', 'system', 'terminal'].includes(message.agent);
    const hasOnlyRoutineEvents = events.length > 0
      && events.every((event) => event.type === 'tool' || event.type === 'sub');
    return message.agent !== 'user' && message.sealed && (isInternalWorker || hasOnlyRoutineEvents);
  }

  function renderMessages({ forceBottom = false } = {}) {
    state.renderForceBottom ||= forceBottom;
    if (state.renderMessageTimer !== null) return;
    // Streaming models can emit many tiny token events. Rebuilding every chat
    // bubble for each token causes visible typing and scroll jank. Batch DOM
    // work to at most ~12 updates/second while retaining a live stream.
    state.renderMessageTimer = setTimeout(() => {
      state.renderMessageTimer = null;
      const nextForceBottom = state.renderForceBottom;
      state.renderForceBottom = false;
      requestAnimationFrame(() => renderMessagesNow({ forceBottom: nextForceBottom }));
    }, 80);
  }

  function renderUserMessage(message) {
    let remaining = String(message.text || '');
    const contexts = Array.isArray(message.contexts) ? message.contexts : [];
    const parts = [];
    while (remaining) {
      let matchContext = null;
      let matchIndex = remaining.length;
      for (const context of contexts) {
        if (!context?.reference) continue;
        const index = remaining.indexOf(context.reference);
        if (index >= 0 && index < matchIndex) { matchIndex = index; matchContext = context; }
      }
      if (!matchContext) { parts.push(escapeHtml(remaining)); break; }
      if (matchIndex) parts.push(escapeHtml(remaining.slice(0, matchIndex)));
      const canOpen = Boolean(matchContext.absolutePath);
      const preview = String(matchContext.content || '').replace(/\s+/g, ' ').trim().slice(0, 180);
      parts.push('<button class="message-attachment" data-open-context="' + escapeHtml(matchContext.id || '') + '" title="' + escapeHtml(canOpen ? '打开来源位置' : preview || matchContext.title || '查看附件') + '"><span aria-hidden="true">' + (matchContext.kind === 'terminal' ? '⌘' : matchContext.kind === 'selection' || matchContext.kind === 'file' ? '⌁' : '▤') + '</span>' + escapeHtml(matchContext.title || '附件') + '</button>');
      remaining = remaining.slice(matchIndex + matchContext.reference.length);
    }
    return '<div class="user-authored-text">' + parts.join('') + '</div>';
  }

  function renderMessagesNow({ forceBottom = false } = {}) {
    $('emptyState').style.display = state.messages.length ? 'none' : 'flex';
    const container = $('messages');
    const signature = messageRenderSignature();
    if (signature === state.messageRenderSignature) {
      if (forceBottom) container.scrollTop = container.scrollHeight;
      return;
    }
    state.messageRenderSignature = signature;
    const previousScrollTop = container.scrollTop;
    const distanceFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
    const shouldFollow = forceBottom || distanceFromBottom <= 48;
    const html = state.messages.map((message) => {
      const isUser = message.agent === 'user';
      const time = new Date(message.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      const events = message.events.map((event) => {
        const blocked = event.type === 'blocked' || event.type === 'error';
        if (event.type === 'approval_required') {
          const detail = event.detail || {};
          const risk = detail.risk || {};
          const findings = (risk.findings || []).map((item) => '<li>' + escapeHtml(item.summary || item.code) + '</li>').join('');
          return '<section class="approval-card"><div class="approval-title"><strong>需要你的允许</strong><span class="risk-' + escapeHtml(risk.level || 'high') + '">' + escapeHtml(String(risk.level || 'high').toUpperCase()) + '</span></div><p>' + escapeHtml(event.result || detail.prompt || '') + '</p><code>' + escapeHtml(detail.tool || detail.name || 'operation') + '</code><pre>' + escapeHtml(pretty(detail.arguments ?? detail.data ?? {})) + '</pre>' + (findings ? '<ul>' + findings + '</ul>' : '') + '<small>' + escapeHtml(detail.reason || '此操作超出自动执行边界。') + '</small><div class="approval-actions"><button data-approval="approved" data-approval-id="' + escapeHtml(detail.approval_id || '') + '" class="allow">允许一次</button><button data-approval="rejected" data-approval-id="' + escapeHtml(detail.approval_id || '') + '" class="reject">拒绝</button></div></section>';
        }
        const expanded = blocked || event.type === 'warning';
        return '<details class="event-card' + (blocked ? ' blocked' : '') + '"' + (expanded ? ' open' : '') + '><summary>' + escapeHtml(event.title) + '</summary><pre class="event-result">' + escapeHtml(pretty(event.result)) + '</pre></details>';
      }).join('');
      const content = (isUser ? renderUserMessage(message) : renderMarkdown(message.text)) + events;
      const bubble = isRoutineProcess(message)
        ? '<div class="bubble process-bubble"><details class="process-card"><summary><span class="process-icon">⌁</span>' + escapeHtml(processSummary(message)) + '<small>展开查看</small></summary><div class="process-detail">' + content + '</div></details></div>'
        : '<div class="bubble">' + content + '</div>';
      return '<article class="message' + (isUser ? ' user' : '') + '"><div class="message-head"><strong>' + escapeHtml(isUser ? '你' : message.agent || 'agent') + '</strong><span>' + time + '</span></div>' + bubble + '</article>';
    }).join('');
    Array.from(container.querySelectorAll('.message')).forEach((node) => node.remove());
    container.insertAdjacentHTML('beforeend', html);
    container.scrollTop = shouldFollow
      ? container.scrollHeight
      : Math.min(previousScrollTop, Math.max(0, container.scrollHeight - container.clientHeight));
    $('messageCount').textContent = String(state.messages.length);
  }

  function handleEvent(message) {
    if (typeof message?.running === 'boolean') {
      applyExecutionState(message);
      return;
    }
    if (message?.scope && !executionMatchesSelection(message.scope)) return;
    const type = message?.type;
    const data = message?.data || {};
    if (type === 'run_started') {
      state.changeTransactionId = String(
        data.change_transaction_id
        || (data.run_id ? `run-${data.run_id}` : '')
        || ''
      );
      postBackendReviewSnapshot(true);
    } else if (type === 'node_enter') {
      state.currentNode = data.node_id || null;
      const op = data.op || (state.currentNode && state.config?.pipeline?.nodes?.[state.currentNode]?.op);
      state.waitingForInput = op === '等待输入' || op === '输入';
      state.stepCount += 1;
      if (state.currentNode) {
        state.entered.add(state.currentNode);
        state.trace.push({ node: state.currentNode, at: Date.now() });
      }
      const labels = {
        '输入': '正在等待你的输入', '等待输入': '正在等待你的输入',
        'Agent': '正在让 Agent 分析任务', '推理': '正在让模型分析任务', '模型': '正在调用模型',
        '工具': '正在执行工具', '执行工具': '正在执行工具', '子流程': '正在运行子 Agent / SubDAG',
        '条件': '正在选择下一条 DAG 路径', '上下文': '正在整理上下文', '数据': '正在更新运行状态',
      };
      setAgentActivity(labels[op] || `正在执行节点 ${state.currentNode}`, state.waitingForInput ? 'waiting' : 'running');
    } else if (type === 'model_request') {
      setAgentActivity(`正在向 ${data.agent || '模型'} 发送整理后的上下文…`, 'running');
    } else if (type === 'token') {
      setAgentActivity(`${data.agent || 'Agent'} 正在生成回答…`, 'running');
      addMessage(data.agent || 'agent', data.text || '');
    } else if (type === 'model_response') {
      const calls = Array.isArray(data.tool_calls) ? data.tool_calls.length : 0;
      if (!calls) {
        const last = state.messages[state.messages.length - 1];
        if (last?.kind === 'message' && last.agent === (data.agent || 'agent')) last.sealed = true;
      }
      setAgentActivity(calls ? `模型选择了 ${calls} 个工具 · 准备执行…` : '模型回答完成 · 正在收尾…', 'running');
    } else if (type === 'tool') {
      setAgentActivity(`已完成 ${data.name || '工具'} · 正在结合结果继续分析…`, 'running');
      addEvent(data.agent || 'system', 'tool', '🔧 ' + (data.name || 'tool'), data.result || '');
    } else if (type === 'blocked') {
      addEvent(data.agent || 'system', 'blocked', '🚫 已拦截 ' + (data.tool || 'tool'), data.reason || '');
    } else if (type === 'error') {
      setAgentActivity('执行失败 · 请查看上方错误', 'error');
      const failure = data.failure || {};
      addEvent('system', 'error', failure.title || '执行错误', [data.message || message.message || '未知错误', failure.action || ''].filter(Boolean).join('\n\n'));
    } else if (type === 'model_output_truncated') {
      const failure = data.failure || {};
      addEvent(data.agent || 'agent', 'warning', '⚠️ ' + (failure.title || '输出达到长度上限'), [data.message || '回复未完成。', failure.action || '请发送“继续”。'].filter(Boolean).join('\n\n'));
    } else if (type === 'run_limit_exceeded') {
      const failure = data.failure || {};
      addEvent('system', 'warning', '⏹ ' + (failure.title || '运行达到上限'), [data.message || '', failure.action || ''].filter(Boolean).join('\n\n'));
    } else if (type === 'approval_required') {
      setAgentActivity('已暂停 · 等待你审批高风险操作', 'waiting');
      state.pendingApproval = data;
      state.waitingForInput = true;
      addEvent('system', 'approval_required', '需要审批', data.prompt || '', data);
    } else if (type === 'approval') {
      state.pendingApproval = null;
      state.waitingForInput = false;
      addEvent('system', data.decision === 'approved' ? 'approval' : 'blocked', data.decision === 'approved' ? '✓ 已允许一次' : '🚫 已拒绝', data.tool || data.name || 'operation');
    } else if (type === 'cancelled') {
      setAgentActivity('运行已停止', 'idle');
      addEvent('system', 'warning', '运行已停止', data.message || '本次运行已取消。');
    } else if (type === 'input_required') {
      state.waitingForInput = true;
      state.currentNode = data.node_id || state.currentNode;
      state.messages.forEach((item) => { item.sealed = true; });
      setAgentActivity('本轮完成 · 等待你的下一条消息', 'waiting');
    } else if (type === 'sub_harness_start') {
      setAgentActivity(`正在运行子 Agent · ${data.harness_name || 'SubDAG'}`, 'running');
      addEvent(data.parent_agent || 'system', 'sub', '↳ 子 Harness：' + (data.harness_name || ''), data.slots || {});
    } else if (type === 'sub_token') {
      setAgentActivity(`${data.agent || '子 Agent'} 正在生成结果…`, 'running');
      addMessage((data.harness_name ? data.harness_name + ' · ' : '') + (data.agent || 'sub-agent'), data.text || '');
    } else if (type === 'sub_tool') {
      addEvent(data.agent || 'sub-agent', 'tool', '↳ 🔧 ' + (data.name || 'tool'), data.result || '');
    } else if (type === 'sub_harness_end') {
      setAgentActivity(`子 Agent 已完成 · 正在返回主 DAG`, 'running');
      addEvent('system', 'sub', '✓ 子 Harness 完成', data.harness_name || data.harness_id || '');
    }
    renderRuntime();
  }

  function syncExecutionOutputs(execution) {
    const outputs = Array.isArray(execution.outputs) ? execution.outputs : [];
    if (!outputs.length) return;
    const runId = String(execution.run_id || state.runId || '');
    state.runId = runId;

    outputs.forEach((output, index) => {
      const key = `${runId}:${output.id ?? index}`;
      const agent = output.agent || 'agent';
      const snapshotText = output.text || '';
      const errorText = agent === 'system' && snapshotText.startsWith('❌ ')
        ? snapshotText.slice(2).trim()
        : '';
      let message = state.outputMessages.get(key);

      if (!message) {
        if (errorText) {
          message = [...state.messages].reverse().find((item) => (
            item.kind === 'message'
            && !item.backendKey
            && item.events?.some((event) => event.type === 'error' && String(event.result || '').trim() === errorText)
          ));
        }
        // A live WebSocket token may have created the bubble just before the
        // polling snapshot arrives. Claim it in chronological order so two
        // identical short replies keep their real turn order. A model_response
        // or input_required event can seal a fast reply before polling sees it;
        // an exact sealed match is therefore also safe to claim.
        message ||= state.messages.find((item) => (
          item.kind === 'message'
          && item.agent === agent
          && !item.backendKey
          && (
            (!item.sealed && (snapshotText.startsWith(item.text || '') || (item.text || '').startsWith(snapshotText)))
            || (item.sealed && item.text === snapshotText)
          )
        ));
        if (!message) {
          message = {
            kind: 'message', agent, text: '', at: Date.now(), sealed: false,
            events: errorText ? [{ type: 'error', title: '执行错误', result: errorText }] : [],
          };
          state.messages.push(message);
        }
        message.backendKey = key;
        state.outputMessages.set(key, message);
      }

      message.agent = agent;
      message.text = errorText ? '' : snapshotText;
      message.events = errorText ? message.events : [
        ...(output.tools || []).map((tool) => ({
          type: 'tool',
          title: '🔧 ' + (tool.name || 'tool'),
          result: tool.result || '',
        })),
        ...(output.blocked || []).map((blocked) => ({
          type: 'blocked',
          title: '🚫 已拦截 ' + (blocked.name || 'tool'),
          result: blocked.reason || '',
        })),
        ...(output.sub_harness ? [{
          type: 'sub',
          title: '↳ 子 Harness：' + (output.sub_harness.harness_name || ''),
          result: output.sub_harness,
        }] : []),
      ];
      message.sealed = Boolean(errorText) || Boolean(output.sealed) || index < outputs.length - 1
        || !execution.running
        || execution.waiting_for_input
        || execution.current_node === 'wait_input'
        || ['输入', '等待输入'].includes(state.config?.pipeline?.nodes?.[execution.current_node]?.op);
    });

    renderMessages();
  }

  function applyExecutionState(execution) {
    if (state.awaitingNewSession && !state.runId) return;
    if (state.runId && execution?.run_id && String(execution.run_id) !== String(state.runId)) {
      // WebSocket broadcasts carry updates for every live Session. Keep the
      // active conversation stable and refresh only the background status dot.
      state.liveRunsSignature = '';
      void refreshExecutionSessions();
      return;
    }
    if (!executionMatchesSelection(execution)) {
      state.foreignExecution = execution.running ? {
        workspace: execution.workspace || '',
        harness: execution.harness || '',
        runId: execution.run_id || 0,
      } : null;
      state.running = false;
      state.currentNode = null;
      state.stepCount = 0;
      renderRuntime();
      return;
    }
    state.foreignExecution = null;
    state.executionWorkspace = canonicalWorkspace(execution.workspace);
    state.running = Boolean(execution.running);
    state.runStatus = String(execution.status || (state.running ? 'running' : 'idle'));
    state.waitingForInput = Boolean(execution.waiting_for_input);
    state.pendingApproval = execution.pending_approval || null;
    state.security = execution.security || state.security;
    state.sandbox = execution.sandbox || state.sandbox;
    state.currentNode = execution.current_node || null;
    state.stepCount = Number(execution.step_count || 0);
    state.messagesCount = Number(execution.messages_count || state.messages.length);
    if (execution.run_id != null) {
      state.runId = String(execution.run_id);
      const reportedTransaction = String(
        execution.change_transaction_id
        || (execution.pipeline_run_id ? `run-${execution.pipeline_run_id}` : '')
        || ''
      );
      if (reportedTransaction) state.changeTransactionId = reportedTransaction;
      postBackendReviewSnapshot();
    }
    syncExecutionOutputs(execution);
    const termination = execution.termination;
    if (termination) {
      const failure = termination.failure || {};
      const message = failure.message || termination.message || termination.kind || '';
      const key = `${execution.run_id || state.runId}:${termination.at || ''}:${termination.kind || ''}:${message}`;
      if (key !== state.terminationKey) {
        state.terminationKey = key;
        const alreadyShown = state.messages.some((item) => item.events?.some((event) => (
          ['error', 'warning'].includes(event.type) && String(event.result || '').includes(String(message))
        )));
        if (!alreadyShown) addEvent(
          'system',
          termination.kind === 'error' ? 'error' : 'warning',
          failure.title || termination.title || (termination.kind === 'limit_exceeded' ? '运行达到上限' : termination.kind === 'cancelled' ? '运行已停止' : '运行结束'),
          [message, failure.action || termination.action || ''].filter(Boolean).join('\n\n'),
        );
      }
    }
    if (state.currentNode) state.entered.add(state.currentNode);
    if (!state.running) state.messages.forEach((message) => { message.sealed = true; });
    renderRuntime();
  }

  function renderRuntime() {
    const runtimeSignature = [
      state.running ? 1 : 0,
      state.waitingForInput ? 1 : 0,
      state.currentNode || '',
      state.stepCount,
      state.messagesCount,
      state.trace.length,
      state.tools.length,
      state.entered.size,
      state.harness || '',
      state.foreignExecution?.runId || 0,
      state.runStatus || '',
      state.pendingApproval?.approval_id || '',
    ].join(':');
    if (runtimeSignature === state.runtimeRenderSignature) return;
    state.runtimeRenderSignature = runtimeSignature;
    const statusLabels = { idle: '空闲', running: '运行中', waiting_approval: '等待审批', completed: '已完成', budget_exceeded: '达到上限', limit_exceeded: '达到上限', error: '失败', cancelled: '已停止' };
    $('runStatus').textContent = state.pendingApproval ? '等待审批' : (state.running ? (isWaiting() ? '等待输入' : '运行中') : (statusLabels[state.runStatus] || '空闲'));
    $('stepCount').textContent = String(state.stepCount);
    $('currentNode').textContent = state.currentNode || '—';
    $('messageCount').textContent = String(Math.max(state.messagesCount, state.messages.length));
    if ($('sandboxStatus')) $('sandboxStatus').textContent = state.sandbox?.label || 'Workspace guard';
    $('start').disabled = state.running;
    $('stop').disabled = !state.running;
    const inferenceNodes = Object.values(state.config?.pipeline?.nodes || {}).filter((node) => node.op === '推理').length;
    if (state.pendingApproval) {
      state.activityText = '已暂停 · 等待你审批高风险操作';
      state.activityKind = 'waiting';
    } else if (state.running && isWaiting()) {
      state.activityText = '本轮完成 · 等待你的下一条消息';
      state.activityKind = 'waiting';
    } else if (!state.running) {
      state.activityText = state.runStatus === 'error'
        ? '执行失败 · 请查看上方错误'
        : state.runStatus === 'cancelled' ? '运行已停止' : '就绪 · 发送消息开始';
      state.activityKind = state.runStatus === 'error' ? 'error' : 'idle';
    } else if (!state.activityText || ['idle', 'waiting'].includes(state.activityKind)) {
      state.activityText = inferenceNodes > 1
        ? `Agent 正在工作 · 当前节点 ${state.currentNode || '准备中'}`
        : 'Agent 正在工作';
      state.activityKind = 'running';
    }
    renderAgentActivity();
    $('trace').innerHTML = state.trace.length ? state.trace.map((item, index) => '<div class="trace-item"><span class="trace-index">' + (index + 1) + '</span><span>' + escapeHtml(item.node) + '</span></div>').join('') : '<div class="muted">尚未执行</div>';
    $('toolHistory').innerHTML = state.tools.length ? state.tools.map((tool) => '<div class="tool-item"><strong>' + escapeHtml(tool.title) + '</strong><pre>' + escapeHtml(pretty(tool.result)) + '</pre></div>').join('') : '<div class="muted">尚无工具调用</div>';
    renderDag();
  }

  function renderAgentActivity() {
    const el = $('agentActivity');
    if (!el) return;
    el.className = `agent-activity ${state.activityKind || 'idle'}`;
    el.setAttribute('aria-busy', state.activityKind === 'running' ? 'true' : 'false');
    $('composerHint').textContent = state.activityText || '就绪';
  }

  function setAgentActivity(text, kind = 'running') {
    state.activityText = text;
    state.activityKind = kind;
    renderAgentActivity();
  }

  function connectWebSocket() {
    try {
      state.ws?.close();
      const ws = new WebSocket(wsUrl);
      state.ws = ws;
      ws.addEventListener('open', () => setConnection(true, '实时连接'));
      ws.addEventListener('message', (event) => {
        try { handleEvent(JSON.parse(event.data)); } catch {}
      });
      ws.addEventListener('close', () => {
        setConnection(false, '重连中');
        setTimeout(connectWebSocket, 1800);
      });
      ws.addEventListener('error', () => setConnection(false, '实时连接失败'));
    } catch {
      setTimeout(connectWebSocket, 2200);
    }
  }

  async function pollExecution() {
    if (state.pollBusy) return;
    state.pollBusy = true;
    try {
      const execution = await request('/api/execution/state' + (state.runId ? runQuery() : workspaceQuery()));
      // A workspace lookup can return its most recent completed run. Treat it
      // as history, not as the active Chat after a reload; otherwise an old
      // transaction silently re-enables stale editor decorations forever.
      if (shouldAdoptExecutionSnapshot(state.runId, execution)) {
        applyExecutionState(execution);
      }
      setConnection(true, state.ws?.readyState === WebSocket.OPEN ? '实时连接' : '已连接');
    } catch {
      setConnection(false, '后端不可用');
    } finally {
      state.pollBusy = false;
    }
  }

  function itemList(value, emptyLabel) {
    const values = Array.isArray(value) ? value : value && typeof value === 'object' ? Object.entries(value).map(([key, entry]) => ({ key, entry })) : [];
    if (!values.length) return '<div class="muted">' + escapeHtml(emptyLabel) + '</div>';
    return values.slice(0, 30).map((item, index) => {
      const title = item?.name || item?.title || item?.id || item?.key || ('#' + (index + 1));
      const body = item?.entry ?? item;
      return '<div class="context-item"><strong>' + escapeHtml(title) + '</strong><pre>' + escapeHtml(pretty(body)) + '</pre></div>';
    }).join('');
  }

  function renderContextPlan() {
    const container = $('contextPlan');
    if (!container) return;
    const plan = state.contextPlan;
    if (!plan) {
      container.innerHTML = '<div class="muted">发送消息后显示自动选择、排除原因与 token 预算。</div>';
      return;
    }
    const selected = (plan.selected || []).map((item) => {
      const location = item.path ? item.path + (item.start_line ? ':' + item.start_line : '') : item.title;
      return '<div class="context-item"><strong>' + escapeHtml(item.kind + ' · ' + location) + '</strong>'
        + '<span class="muted">' + escapeHtml(item.provenance) + ' · ' + Number(item.token_count || 0) + ' tokens · score ' + Number(item.score || 0).toFixed(2) + '</span>'
        + '<pre>' + escapeHtml(String(item.content || '').slice(0, 900)) + (String(item.content || '').length > 900 ? '\n…' : '') + '</pre>'
        + '<div class="context-actions"><button data-context-feedback="accepted" data-context-id="' + escapeHtml(item.id) + '">有用</button>'
        + '<button data-context-feedback="rejected" data-context-id="' + escapeHtml(item.id) + '">无用</button></div></div>';
    }).join('');
    const excluded = (plan.excluded || []).slice(0, 20).map((item) =>
      '<div class="muted">排除 ' + escapeHtml(item.id) + '：' + escapeHtml(item.reason) + ' (' + Number(item.token_count || 0) + ' tokens)</div>'
    ).join('');
    container.innerHTML = '<div class="context-summary"><div class="summary-chip"><strong>' + Number(plan.tokens_used || 0) + '</strong>已用 tokens</div>'
      + '<div class="summary-chip"><strong>' + Number(plan.tokens_remaining || 0) + '</strong>剩余</div>'
      + '<div class="summary-chip"><strong>' + (plan.selected || []).length + '</strong>已选择</div></div>'
      + (selected || '<div class="muted">没有选择上下文</div>')
      + (excluded ? '<details><summary>未选内容及原因</summary>' + excluded + '</details>' : '');
    container.querySelectorAll('[data-context-feedback]').forEach((button) => button.addEventListener('click', async () => {
      try {
        await request('/api/context/feedback', {
          method: 'POST',
          body: JSON.stringify({
            workspace: state.attachedContext?.workspacePath,
            item_ids: [button.dataset.contextId],
            decision: button.dataset.contextFeedback,
          }),
        });
        button.disabled = true;
        toast('上下文反馈已保存在当前工作区');
      } catch (error) {
        toast('上下文反馈失败：' + error.message, true);
      }
    }));
  }

  async function loadContext() {
    $('contextSummary').innerHTML = '<div class="muted">加载中…</div>';
    const paths = ['/api/memory', '/api/rules', '/api/checkpoints', '/api/sessions/history' + workspaceQuery()];
    const results = await Promise.allSettled(paths.map((path) => request(path)));
    const data = results.map((result) => result.status === 'fulfilled' ? result.value : []);
    const [memory, rules, checkpoints, sessions] = data;
    $('contextSummary').innerHTML = [
      ['记忆', countOf(memory)], ['规则', countOf(rules)], ['检查点', countOf(checkpoints)], ['Sessions', countOf(sessions)],
    ].map(([label, count]) => '<div class="summary-chip"><strong>' + count + '</strong>' + label + '</div>').join('');
    $('memoryList').innerHTML = itemList(memory, '暂无记忆');
    $('rulesList').innerHTML = itemList(rules, '暂无项目规则');
    $('checkpointsList').innerHTML = itemList(checkpoints, '暂无检查点');
    $('sessionsList').innerHTML = itemList(sessions, '暂无历史 Session');
  }

  function cleanDiffLine(line) {
    return String(line ?? '').replace(/\r?\n$/, '');
  }

  function statusText(status) {
    return ({ pending: '待审查', partial: '部分完成', accepted: '已接受', rejected: '已拒绝', conflict: '文件冲突' })[status] || status;
  }

  function pendingReviewHunks(item) {
    if (item?.file_exists === false && !item?.is_deleted_file) return [];
    return (Array.isArray(item?.hunks) ? item.hunks : []).filter((hunk) => hunk.status === 'pending');
  }

  function needsReview(item) {
    return pendingReviewHunks(item).length > 0 || item?.status === 'conflict';
  }

  function renderDiffLines(oldLines, newLines) {
    const removed = (oldLines || []).map((line) => '<div class="diff-line removed"><span>−</span><code>' + escapeHtml(cleanDiffLine(line)) + '</code></div>').join('');
    const added = (newLines || []).map((line) => '<div class="diff-line added"><span>＋</span><code>' + escapeHtml(cleanDiffLine(line)) + '</code></div>').join('');
    if (!removed && !added) return '<div class="muted">无文本差异</div>';
    return '<div class="mini-diff">' + removed + added + '</div>';
  }

  function localProposalHtml(proposal) {
    const reviewHunks = pendingReviewHunks(proposal);
    const pending = reviewHunks.length;
    const firstLine = Number(reviewHunks[0]?.oldStart || 1);
    const hunks = reviewHunks.map((hunk) => {
      const actions = '<div class="hunk-actions"><button data-change-source="local" data-change-action="accept" data-proposal="' + escapeHtml(proposal.id) + '" data-hunk="' + hunk.id + '" class="accept">✓ 接受</button><button data-change-source="local" data-change-action="reject" data-proposal="' + escapeHtml(proposal.id) + '" data-hunk="' + hunk.id + '" class="reject">✕ 拒绝</button></div>';
      return '<article class="hunk ' + escapeHtml(hunk.status) + '"><div class="hunk-head"><span>第 ' + hunk.oldStart + ' 行 · ' + escapeHtml(hunk.label) + '</span>' + actions + '</div>' + renderDiffLines(hunk.oldLines, hunk.newLines) + '</article>';
    }).join('');
    const bulk = '<div class="file-actions"><button data-change-source="local" data-change-action="diff" data-proposal="' + escapeHtml(proposal.id) + '">↔ 原生 Diff</button>' + (pending ? '<button data-change-source="local" data-change-action="acceptAll" data-proposal="' + escapeHtml(proposal.id) + '">全部接受</button><button data-change-source="local" data-change-action="rejectAll" data-proposal="' + escapeHtml(proposal.id) + '">全部拒绝</button>' : '') + '</div>';
    return '<section class="change-card"><div class="change-head"><div><button type="button" class="change-file-link" data-open-change-file="' + escapeHtml(proposal.path) + '" data-open-change-line="' + firstLine + '" title="在编辑器中打开"><strong>' + escapeHtml(proposal.path) + '</strong></button><span>' + escapeHtml(proposal.title) + ' · 已默认应用到编辑器</span></div><span class="status-pill">' + pending + ' 待审</span></div>' + bulk + hunks + '</section>';
  }

  function backendChangeHtml(change) {
    const hunks = pendingReviewHunks(change);
    const pending = hunks.length;
    const selector = escapeHtml(change.id || String(change.index));
    const firstLine = Number(hunks[0]?.old_start || 0) + 1;
    const hunkHtml = hunks.length ? hunks.map((hunk) => {
      const actions = '<div class="hunk-actions"><button data-change-source="backend" data-change-action="accept" data-id="' + selector + '" data-hunk="' + escapeHtml(String(hunk.id)) + '" class="accept">✓ 接受</button><button data-change-source="backend" data-change-action="reject" data-id="' + selector + '" data-hunk="' + escapeHtml(String(hunk.id)) + '" class="reject">✕ 拒绝</button></div>';
      return '<article class="hunk ' + escapeHtml(hunk.status) + '"><div class="hunk-head"><span>原第 ' + (Number(hunk.old_start || 0) + 1) + ' 行 · ' + escapeHtml(hunk.tag || 'edit') + '</span>' + actions + '</div>' + renderDiffLines(hunk.old_lines, hunk.new_lines) + '</article>';
    }).join('') : '<pre class="unified-diff">' + escapeHtml((change.diff || []).join('')) + '</pre>';
    const diffAction = change.change_type === 'text'
      ? '<button data-open-backend-diff="' + selector + '" data-hunk="' + escapeHtml(String(hunks[0]?.id || '')) + '">↔ Review Diff</button>'
      : '';
    const actions = '<div class="file-actions">' + diffAction + ((change.status === 'pending' || change.status === 'partial')
      ? '<button data-change-source="backend" data-change-action="acceptAll" data-id="' + selector + '">全部接受</button><button data-change-source="backend" data-change-action="rejectAll" data-id="' + selector + '">全部拒绝</button>'
      : '') + '</div>';
    const conflict = change.conflict ? '<div class="muted">⚠ ' + escapeHtml(change.conflict.message || '文件已被外部修改，请先保存或手动合并后刷新') + '</div>' : '';
    return '<section class="change-card backend"><div class="change-head"><div><button type="button" class="change-file-link" data-open-change-file="' + escapeHtml(change.file_path) + '" data-open-change-line="' + firstLine + '" data-review-transaction="' + escapeHtml(change.transaction_id || '') + '" title="在编辑器中打开并审阅本次运行"><strong>' + escapeHtml(change.file_path) + '</strong></button><span>' + escapeHtml(change.tool_name || 'DAG Agent') + ' · 真实 Agent 改动' + (change.is_new_file ? ' · 新文件（全文绿色）' : '') + (change.is_deleted_file ? ' · 删除文件' : '') + '</span></div><span class="status-pill">' + escapeHtml(statusText(change.status)) + (pending ? ' · ' + pending : '') + '</span></div>' + conflict + actions + hunkHtml + '</section>';
  }

  function renderReviewIssues() {
    const labels = ['错误', '警告', '信息', '提示'];
    $('reviewIssues').innerHTML = state.reviewIssues.length
      ? '<details open><summary>AI / Local Quick Review · ' + state.reviewIssues.length + ' 项</summary>' + state.reviewIssues.map((issue) => '<div class="review-issue severity-' + issue.severity + '"><strong>L' + issue.line + ' · ' + labels[issue.severity] + '</strong><span>' + escapeHtml(issue.message) + (issue.suggestion ? '<small>' + escapeHtml(issue.suggestion) + '</small>' : '') + '</span><code>' + escapeHtml(issue.code) + '</code></div>').join('') + '</details>'
      : '';
  }

  function renderChanges() {
    const localPending = state.localProposals.reduce((total, proposal) => total + pendingReviewHunks(proposal).length, 0);
    const backendPending = state.backendChanges.reduce((total, change) => total + pendingReviewHunks(change).length, 0);
    const pending = localPending + backendPending;
    $('pendingBadge').textContent = String(pending);
    $('pendingBadge').classList.toggle('active', pending > 0);
    const metrics = state.metrics || {};
    $('changeSummary').innerHTML = [
      ['待审改动', pending],
      ['Tab 建议', metrics.completionsOffered || 0],
      ['Tab 接受', metrics.completionsAccepted || 0],
      ['已审 hunk', (metrics.hunksAccepted || 0) + (metrics.hunksRejected || 0)],
    ].map(([label, count]) => '<div class="summary-chip"><strong>' + count + '</strong>' + label + '</div>').join('');
    const html = [
      ...state.localProposals.filter(needsReview).map(localProposalHtml),
      ...state.backendChanges.filter(needsReview).map(backendChangeHtml),
    ].join('');
    $('changeList').innerHTML = html || '<div class="changes-empty"><strong>当前没有待审查改动</strong><span>点击“AI 多段改动”生成提案；模型不可用时仍可体验逐段 Accept / Reject 和原生红绿 Diff。</span></div>';
    renderReviewIssues();
  }

  async function loadTrackedChanges() {
    try {
      const workspace = state.editorContext?.workspacePath;
      const query = workspace ? '?workspace=' + encodeURIComponent(workspace) : '';
      state.backendChanges = await request('/api/session/changes' + query);
    } catch {
      state.backendChanges = [];
    }
    postBackendReviewSnapshot(true);
    renderChanges();
  }

  async function handleChangeAction(button) {
    const source = button.dataset.changeSource;
    const action = button.dataset.changeAction;
    if (!source || !action) return;
    button.disabled = true;
    try {
      if (source === 'local') {
        vscode.postMessage({ type: 'changeAction', action, proposalId: button.dataset.proposal, hunkId: Number(button.dataset.hunk) });
        return;
      }
      const id = button.dataset.id;
      const hunkId = button.dataset.hunk === undefined ? undefined : button.dataset.hunk;
      vscode.postMessage({ type: 'backendChangeAction', action, id, hunkId });
    } catch (error) {
      toast('改动操作失败：' + error.message, true);
    } finally {
      button.disabled = false;
    }
  }

  function attachmentReference(context) {
    const title = String(context?.title || 'Clipboard context').replace(/\s+/g, ' ').trim().slice(0, 240);
    const kind = context?.kind === 'terminal' ? '终端附件' : context?.kind === 'selection' ? '代码附件' : context?.kind === 'file' ? '文件附件' : context?.kind === 'workspace' ? '项目上下文' : '文本附件';
    return `[${kind}: ${title}]`;
  }

  function composerText() {
    const walk = (node) => {
      if (node.nodeType === Node.TEXT_NODE) return node.nodeValue || '';
      if (node.nodeType !== Node.ELEMENT_NODE) return '';
      if (node.classList.contains('inline-attachment')) {
        const context = state.pastedContexts.find((item) => item.id === node.dataset.contextId);
        return context?.reference || '';
      }
      if (node.tagName === 'BR') return '\n';
      const text = Array.from(node.childNodes).map(walk).join('');
      return node !== $('prompt') && ['DIV', 'P'].includes(node.tagName) ? text + '\n' : text;
    };
    return walk($('prompt')).replace(/\u00a0/g, ' ');
  }

  function clearComposer() {
    $('prompt').replaceChildren();
    state.lastComposerMutation = null;
  }

  function placeCaretAfter(node) {
    const range = document.createRange();
    range.setStartAfter(node);
    range.collapse(true);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  }

  function insertNodeAtComposerCaret(node) {
    const input = $('prompt');
    input.focus();
    const selection = window.getSelection();
    let range = selection.rangeCount ? selection.getRangeAt(0) : null;
    if (!range || !input.contains(range.commonAncestorContainer)) {
      range = document.createRange();
      range.selectNodeContents(input);
      range.collapse(false);
    }
    range.deleteContents();
    range.insertNode(node);
    const spacer = document.createTextNode('\u00a0');
    node.after(spacer);
    placeCaretAfter(spacer);
  }

  function insertPlainTextAtCaret(text) {
    const node = document.createTextNode(String(text || ''));
    insertNodeAtComposerCaret(node);
  }

  function attachmentIcon(kind) {
    return kind === 'terminal' ? '⌘' : kind === 'selection' || kind === 'file' ? '⌁' : '▤';
  }

  function attachmentPreview(context, limit = 180) {
    const content = String(context?.content || '').replace(/\r\n/g, '\n').trim();
    if (!content) return context?.title || '空附件';
    const compact = content.replace(/\s+/g, ' ');
    return compact.length > limit ? compact.slice(0, limit - 1) + '…' : compact;
  }

  function updateAttachmentNode(node, context) {
    if (!node || !context) return;
    node.dataset.contextId = context.id;
    const preview = attachmentPreview(context);
    node.title = context.absolutePath
      ? `${preview}\n点击打开来源；Backspace 或 Ctrl+Z 删除`
      : `${preview}\n点击查看并编辑；Backspace 或 Ctrl+Z 删除`;
    node.setAttribute('aria-label', `${context.title || '附件'}。${preview}`);
    node.querySelector('.attachment-icon').textContent = attachmentIcon(context.kind);
    node.querySelector('.attachment-label').textContent = context.title || '附件';
  }

  function makeAttachmentNode({ requestId = '', context = null, pending = false }) {
    const node = document.createElement('span');
    node.className = 'inline-attachment' + (pending ? ' pending' : '');
    node.contentEditable = 'false';
    if (requestId) node.dataset.pendingId = requestId;
    node.innerHTML = '<span class="attachment-icon" aria-hidden="true">' + attachmentIcon(context?.kind) + '</span><span class="attachment-label">' + escapeHtml(pending ? '识别中…' : context?.title || '附件') + '</span>';
    if (context?.id) updateAttachmentNode(node, context);
    else node.title = '正在识别附件…';
    return node;
  }

  function openAttachmentEditor(context, editable) {
    if (!context) return;
    state.editingAttachmentId = editable ? context.id : '';
    $('attachmentEditorTitle').textContent = context.title || '文本附件';
    $('attachmentEditorMeta').textContent = `${context.language || 'text'} · ${String(context.content || '').length.toLocaleString()} 字符`;
    $('attachmentEditorContent').value = String(context.content || '');
    $('attachmentEditorContent').readOnly = !editable;
    $('attachmentEditorNotice').textContent = editable ? '修改只会更新本次尚未发送的上下文。' : '这是已发送消息中的附件快照，只读展示。';
    $('attachmentEditorSave').hidden = !editable;
    $('attachmentEditorCancel').textContent = editable ? '取消' : '关闭';
    $('attachmentEditor').showModal();
    if (editable) {
      $('attachmentEditorContent').focus();
      $('attachmentEditorContent').setSelectionRange(0, 0);
    }
  }

  function saveAttachmentEditor() {
    const context = state.pastedContexts.find((item) => item.id === state.editingAttachmentId);
    if (!context) return;
    const raw = $('attachmentEditorContent').value;
    context.content = raw.slice(0, 50000);
    context.truncated = raw.length > 50000;
    if (context.kind === 'clipboard') {
      const lines = context.content.replaceAll('\r\n', '\n').split('\n').length;
      context.title = `Clipboard · ${lines} ${lines === 1 ? 'line' : 'lines'}`;
    }
    context.reference = attachmentReference(context);
    Array.from($('prompt').querySelectorAll('.inline-attachment[data-context-id]'))
      .filter((node) => node.dataset.contextId === context.id)
      .forEach((node) => updateAttachmentNode(node, context));
    state.lastComposerMutation = null;
    $('composerHint').textContent = '文本附件已更新';
    renderEditorContext();
  }

  function insertComposerAttachmentPlaceholder(requestId) {
    const node = makeAttachmentNode({ requestId, pending: true });
    state.pendingContextPastes.set(requestId, { node });
    insertNodeAtComposerCaret(node);
  }

  function resolveComposerAttachmentPlaceholder(requestId, context = null) {
    const pending = state.pendingContextPastes.get(requestId);
    state.pendingContextPastes.delete(requestId);
    if (!pending?.node?.isConnected) return false;
    if (!context) {
      pending.node.nextSibling?.nodeType === Node.TEXT_NODE && pending.node.nextSibling.nodeValue === '\u00a0'
        ? pending.node.nextSibling.remove()
        : null;
      pending.node.remove();
      return true;
    }
    const node = makeAttachmentNode({ context });
    pending.node.replaceWith(node);
    state.lastComposerMutation = { kind: 'attachment', id: context.id };
    placeCaretAfter(node.nextSibling || node);
    $('prompt').focus();
    return true;
  }

  function removePastedContext(id, { removeNode = true } = {}) {
    state.pastedContexts = state.pastedContexts.filter((item) => item.id !== id);
    if (removeNode) {
      Array.from($('prompt').querySelectorAll('.inline-attachment')).forEach((node) => {
        if (node.dataset.contextId === id) {
          const next = node.nextSibling;
          node.remove();
          if (next?.nodeType === Node.TEXT_NODE && /^\s*$/.test(next.nodeValue || '')) next.remove();
        }
      });
    }
    if (state.lastComposerMutation?.id === id) state.lastComposerMutation = null;
    renderEditorContext();
  }

  function addPastedContext(context, id) {
    if (!context || (!context.content && context.kind !== 'workspace')) return null;
    const item = {
      ...context,
      id: id || `paste-${Date.now()}-${Math.random().toString(36).slice(2)}`,
      reference: attachmentReference(context),
    };
    state.pastedContexts.push(item);
    if (state.pastedContexts.length > 8) removePastedContext(state.pastedContexts[0].id);
    $('composerHint').textContent = `${item.title} 已在消息正文标注并作为上下文附加`;
    return item;
  }

  function renderEditorContext() {
    const context = state.editorContext;
    const contextEl = $('editorContext');
    if (contextEl) {
      contextEl.innerHTML = context?.available
        ? '<div class="context-file"><strong>@file ' + escapeHtml(context.path) + ':' + context.line + '</strong><span>' + escapeHtml(context.language) + ' · ' + (context.symbols?.length || 0) + ' symbols' + (context.selectionLines ? ' · 选中 ' + context.selectionLines + ' 行' : '') + '</span></div>'
        : '<div class="muted">打开代码文件后，这里会显示当前文件、选区和符号上下文。</div>';
    }
    const chips = [];
    if (state.attachedContext?.available) {
      chips.push('<span class="context-chip">@file ' + escapeHtml(state.attachedContext.path) + '<button id="removeContext" title="移除">×</button></span>');
      if (state.attachedContext.selectionText) chips.push('<span class="context-chip">@selection ' + state.attachedContext.selectionLines + ' 行</span>');
    }
    // Every pasted/dropped context now lives only at its exact position inside
    // the message composer. Do not duplicate Clipboard previews above it.
    $('contextChips').innerHTML = chips.join('');
    $('removeContext')?.addEventListener('click', () => { state.attachedContext = null; renderEditorContext(); });
  }

  async function createCheckpoint() {
    try {
      await request('/api/checkpoints/create', {
        method: 'POST',
        body: JSON.stringify({
          label: 'Void DAG Chat · ' + new Date().toLocaleString(),
          workspace: state.editorContext?.workspacePath || '',
          files: state.editorContext?.absolutePath ? [state.editorContext.absolutePath] : [],
          metadata: { source: 'void', harness: state.harness, identity: state.identity },
        }),
      });
      toast('检查点已创建');
      await loadContext();
    } catch (error) {
      toast('创建检查点失败：' + error.message, true);
    }
  }

  function switchTab(name) {
    document.querySelectorAll('.tab').forEach((tab) => tab.classList.toggle('active', tab.dataset.tab === name));
    document.querySelectorAll('.tab-panel').forEach((panel) => panel.classList.remove('active'));
    $(name + 'Tab').classList.add('active');
    if (name === 'context') loadContext();
    if (name === 'changes') loadTrackedChanges();
  }

  $('harnessSelect').addEventListener('change', async (event) => {
    detachFromExecutionSelection();
    try { await loadHarness(event.target.value); } catch (error) { toast(error.message, true); }
  });
  $('harnessFilter').addEventListener('input', (event) => {
    state.harnessFilter = event.target.value;
    renderSelectors();
    persist();
  });
  $('showWorkers').addEventListener('change', (event) => {
    state.showWorkers = event.target.checked;
    renderSelectors();
    persist();
  });
  $('identitySelect').addEventListener('change', (event) => {
    detachFromExecutionSelection();
    state.identity = event.target.value;
    renderBindings();
    persist();
  });
  $('modeSelect').value = state.mode;
  $('modeSelect').addEventListener('change', (event) => {
    detachFromExecutionSelection();
    state.mode = event.target.value;
    renderSelectors();
    persist();
    const descriptions = {
      chat: '只读问答：禁止写文件和运行进程',
      plan: '只读规划：输出方案，不执行修改',
      agent: '完整 Agent：按权限策略执行并记录改动',
      debug: '调试：复现、修复并验证',
      evolve: '进化：仅允许修改当前 Harness 和已绑定 Identity',
      evaluate: '隔离评测：默认禁网且禁止全局进化',
    };
    toast(descriptions[state.mode] || state.mode);
  });
  $('agentConfigDetails').open = state.configExpanded;
  $('agentConfigDetails').addEventListener('toggle', () => {
    state.configExpanded = $('agentConfigDetails').open;
    persist();
  });
  let plainPasteArmed = false;
  function attachmentBeforeCaret() {
    const selection = window.getSelection();
    if (!selection.rangeCount || !selection.isCollapsed) return null;
    const range = selection.getRangeAt(0);
    let node = range.startContainer;
    if (!$('prompt').contains(node)) return null;
    if (node.nodeType === Node.TEXT_NODE) {
      if ((node.nodeValue || '').slice(0, range.startOffset).trim()) return null;
      node = node.previousSibling;
    } else if (node.nodeType === Node.ELEMENT_NODE) {
      node = node.childNodes[Math.max(0, range.startOffset - 1)] || null;
    }
    while (node?.nodeType === Node.TEXT_NODE && !(node.nodeValue || '').trim()) node = node.previousSibling;
    return node?.nodeType === Node.ELEMENT_NODE && node.classList.contains('inline-attachment') ? node : null;
  }

  function syncComposerContexts() {
    const ids = new Set(Array.from($('prompt').querySelectorAll('.inline-attachment[data-context-id]')).map((node) => node.dataset.contextId));
    const retained = state.pastedContexts.filter((item) => ids.has(item.id));
    if (retained.length === state.pastedContexts.length) return false;
    state.pastedContexts = retained;
    if (state.lastComposerMutation?.id && !ids.has(state.lastComposerMutation.id)) state.lastComposerMutation = null;
    renderEditorContext();
    $('composerHint').textContent = '附件图标已删除，对应上下文也已移除';
    return true;
  }

  $('prompt').addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'v' && event.shiftKey) {
      plainPasteArmed = true;
      setTimeout(() => { plainPasteArmed = false; }, 1000);
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z' && state.lastComposerMutation?.kind === 'attachment') {
      const node = Array.from($('prompt').querySelectorAll('.inline-attachment')).find((item) => item.dataset.contextId === state.lastComposerMutation.id);
      if (node) {
        event.preventDefault();
        removePastedContext(state.lastComposerMutation.id);
        $('composerHint').textContent = '已撤销附件插入';
        return;
      }
      state.lastComposerMutation = null;
    }
    if (event.key === 'Backspace') {
      const node = attachmentBeforeCaret();
      if (node) {
        event.preventDefault();
        const id = node.dataset.contextId;
        if (id) removePastedContext(id);
        else {
          const requestId = node.dataset.pendingId;
          if (requestId) state.pendingContextPastes.delete(requestId);
          node.remove();
        }
        $('composerHint').textContent = '附件已删除';
        return;
      }
    }
    if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); sendPrompt(); }
  });
  $('prompt').addEventListener('input', (event) => {
    if (event.inputType !== 'insertFromPaste') state.lastComposerMutation = null;
    syncComposerContexts();
  });
  new MutationObserver(() => syncComposerContexts()).observe($('prompt'), { childList: true, subtree: true });
  $('prompt').addEventListener('paste', (event) => {
    const text = event.clipboardData?.getData('text/plain') || '';
    if (plainPasteArmed) {
      plainPasteArmed = false;
      event.preventDefault();
      insertPlainTextAtCaret(text);
      $('composerHint').textContent = '已按纯文本粘贴';
      return;
    }
    if (!text) return;
    event.preventDefault();
    const requestId = `paste-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    insertComposerAttachmentPlaceholder(requestId);
    $('composerHint').textContent = '正在识别代码来源…';
    vscode.postMessage({ type: 'resolveContextPaste', requestId, text });
  });
  let contextDragDepth = 0;
  const transferSnapshot = (dataTransfer) => {
    const transfer = {};
    for (const type of Array.from(dataTransfer?.types || [])) {
      try { transfer[type] = dataTransfer.getData(type); } catch {}
    }
    const files = Array.from(dataTransfer?.files || []).map((file) => ({
      name: file.name || '',
      path: file.path || '',
      type: file.type || '',
    }));
    if (files.length) transfer.__files = files;
    return transfer;
  };
  const attachDroppedTransfer = (transfer) => {
    const requestId = `drop-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    insertComposerAttachmentPlaceholder(requestId);
    $('composerHint').textContent = '正在读取拖入的文件或选区…';
    vscode.postMessage({ type: 'resolveContextDrop', requestId, transfer });
  };
  const handleContextDrop = (event) => {
    event.preventDefault();
    event.stopPropagation();
    contextDragDepth = 0;
    $('prompt').classList.remove('drop-target');
    const caret = document.caretRangeFromPoint?.(event.clientX, event.clientY);
    if (caret && $('prompt').contains(caret.commonAncestorContainer)) {
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(caret);
    }
    attachDroppedTransfer(transferSnapshot(event.dataTransfer));
  };
  // Void's Explorer and editor tabs drag custom ResourceURLs / CodeEditors
  // across a nested webview iframe.  Capturing on the whole webview is more
  // reliable than requiring the browser to resolve the final target to the
  // contenteditable itself.  The attachment is still inserted at the caret
  // when the pointer lands inside the composer.
  document.addEventListener('dragenter', (event) => {
    event.preventDefault();
    contextDragDepth += 1;
    $('prompt').classList.add('drop-target');
  }, true);
  document.addEventListener('dragover', (event) => {
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy';
    $('prompt').classList.add('drop-target');
  }, true);
  document.addEventListener('dragleave', () => {
    contextDragDepth = Math.max(0, contextDragDepth - 1);
    if (!contextDragDepth) $('prompt').classList.remove('drop-target');
  }, true);
  document.addEventListener('drop', handleContextDrop, true);
  // A VS Code webview is nested behind an isolated iframe. Some Chromium
  // builds finish Explorer drags in the workbench document and never dispatch
  // `drop` inside this frame. Register a MessageChannel with the small
  // workbench bridge installed by start-all.py so the original ResourceURLs /
  // CodeEditors payload can cross that boundary without turning into plain
  // text or requiring a context-menu fallback.
  if (window.top !== window && typeof MessageChannel === 'function') {
    const workbenchDropChannel = new MessageChannel();
    workbenchDropChannel.port1.onmessage = (event) => {
      if (event.data?.type !== 'egoagent-workbench-resource-drop' || !event.data.transfer) return;
      $('prompt').classList.remove('drop-target');
      attachDroppedTransfer(event.data.transfer);
    };
    workbenchDropChannel.port1.start();
    window.top.postMessage({
      type: 'egoagent-drop-target-register',
      width: window.innerWidth,
      height: window.innerHeight,
    }, '*', [workbenchDropChannel.port2]);
  }
  $('prompt').addEventListener('click', (event) => {
    const node = event.target.closest('.inline-attachment[data-context-id]');
    if (!node) return;
    const context = state.pastedContexts.find((item) => item.id === node.dataset.contextId);
    if (context?.absolutePath) vscode.postMessage({ type: 'openContextLocation', context });
    else openAttachmentEditor(context, true);
  });
  $('attachmentEditor').addEventListener('close', () => { state.editingAttachmentId = ''; });
  $('attachmentEditorSave').addEventListener('click', (event) => {
    event.preventDefault();
    saveAttachmentEditor();
    $('attachmentEditor').close('saved');
  });
  $('send').addEventListener('click', sendPrompt);
  $('messages').addEventListener('click', async (event) => {
    const contextButton = event.target.closest('[data-open-context]');
    if (contextButton) {
      const context = state.messages.flatMap((message) => message.contexts || []).find((item) => item.id === contextButton.dataset.openContext);
      if (context?.absolutePath) vscode.postMessage({ type: 'openContextLocation', context });
      else if (context) openAttachmentEditor(context, false);
      return;
    }
    const button = event.target.closest('[data-approval]');
    if (!button) return;
    button.disabled = true;
    try {
      await request('/api/execution/approval', {
        method: 'POST',
        body: runBody({ approval_id: button.dataset.approvalId, decision: button.dataset.approval }),
      });
      button.closest('.approval-actions')?.querySelectorAll('button').forEach((item) => { item.disabled = true; });
      toast(button.dataset.approval === 'approved' ? '已允许本次操作' : '已拒绝本次操作');
    } catch (error) {
      button.disabled = false;
      toast('审批失败：' + error.message, true);
    }
  });
  $('start').addEventListener('click', () => startExecution().catch((error) => toast(error.message, true)));
  $('stop').addEventListener('click', () => stopExecution().catch((error) => toast(error.message, true)));
  $('clear').addEventListener('click', () => { state.messages = []; state.trace = []; state.tools = []; state.entered = new Set(); renderMessages(); renderRuntime(); });
  $('refreshContext').addEventListener('click', loadContext);
  $('attachContext').addEventListener('click', (event) => {
    event.stopPropagation();
    $('contextPicker').hidden = !$('contextPicker').hidden;
  });
  $('contextPicker').addEventListener('click', (event) => {
    const button = event.target.closest('[data-attach-kind]');
    if (!button) return;
    state.attachRequested = button.dataset.attachKind;
    $('contextPicker').hidden = true;
    vscode.postMessage({ type: 'requestEditorContext' });
  });
  document.addEventListener('click', () => { $('contextPicker').hidden = true; });
  $('createCheckpoint').addEventListener('click', createCheckpoint);
  const openWorkbench = (tab) => vscode.postMessage({ type: 'openWorkbench', tab });
  $('workbenchQuick')?.addEventListener('click', () => openWorkbench('home'));
  $('openSessionPortfolio')?.addEventListener('click', () => openWorkbench('sessions'));
  $('newSession')?.addEventListener('click', startFreshSession);
  $('openWorkbench')?.addEventListener('click', () => openWorkbench('home'));
  $('openHarnessBuilder')?.addEventListener('click', () => openWorkbench('harness'));
  $('openEvaluation')?.addEventListener('click', () => openWorkbench('tasks'));
  $('openEvolution')?.addEventListener('click', () => openWorkbench('evolution'));
  $('openSecurity')?.addEventListener('click', () => openWorkbench('settings'));
  $('workbenchStatus')?.addEventListener('click', () => {
    const status = state.workbenchStatus || {};
    const route = status.pendingChanges ? 'changes' : status.scope === 'evaluate' ? 'tasks' : status.scope === 'evolution' || status.evolutionProposals ? 'evolution' : 'harness';
    openWorkbench(route);
  });
  $('codeMap').addEventListener('click', () => vscode.postMessage({ type: 'codeMap' }));
  $('previewApp').addEventListener('click', () => vscode.postMessage({ type: 'preview' }));
  $('commitMessage').addEventListener('click', () => vscode.postMessage({ type: 'commitMessage' }));
  $('mockChanges').addEventListener('click', () => vscode.postMessage({ type: 'mockEdit', mode: 'maintainability' }));
  $('inlineEdit').addEventListener('click', () => vscode.postMessage({ type: 'inlineEdit' }));
  $('localReview').addEventListener('click', () => vscode.postMessage({ type: 'localReview' }));
  $('refreshChanges').addEventListener('click', loadTrackedChanges);
  $('changeList').addEventListener('click', (event) => {
    const file = event.target.closest('[data-open-change-file]');
    if (file) {
      vscode.postMessage({
        type: 'openChangeFile',
        path: file.dataset.openChangeFile,
        line: Number(file.dataset.openChangeLine || 1),
        transactionId: file.dataset.reviewTransaction || '',
      });
      return;
    }
    const diff = event.target.closest('[data-open-backend-diff]');
    if (diff) {
      vscode.postMessage({ type: 'openBackendDiff', id: diff.dataset.openBackendDiff, hunkId: diff.dataset.hunk || '' });
      return;
    }
    const button = event.target.closest('[data-change-action]');
    if (button) handleChangeAction(button);
  });
  document.querySelectorAll('.tab').forEach((tab) => tab.addEventListener('click', () => switchTab(tab.dataset.tab)));
  window.addEventListener('message', (event) => {
    const message = event.data || {};
    if (message.type === 'refresh') { loadCatalog(); loadTrackedChanges(); }
    if (message.type === 'refreshTrackedChanges') loadTrackedChanges();
    if (message.type === 'trackedChanges') {
      state.backendChanges = Array.isArray(message.changes) ? message.changes : [];
      postBackendReviewSnapshot(true);
      renderChanges();
    }
    if (message.type === 'localState') {
      state.localProposals = message.proposals || [];
      state.metrics = message.metrics || {};
      state.reviewIssues = message.reviewIssues || [];
      state.completionEnabled = message.completionEnabled !== false;
      state.aiStatus = message.aiStatus || state.aiStatus;
      state.workbenchStatus = message.workbenchStatus || state.workbenchStatus;
      renderAIStatus();
      renderWorkbenchStatus();
      renderChanges();
    }
    if (message.type === 'workbenchStatus') {
      state.workbenchStatus = message.status || state.workbenchStatus;
      renderWorkbenchStatus();
    }
    if (message.type === 'contextPasteResolved') {
      if (message.context) {
        const item = addPastedContext(message.context, message.requestId);
        resolveComposerAttachmentPlaceholder(message.requestId, item);
        renderEditorContext();
        const pasteLabel = message.context.kind === 'terminal'
          ? '终端输出'
          : message.context.kind === 'selection' ? '代码选区' : '剪贴板内容';
        toast(pasteLabel + '已作为结构化上下文附加');
      } else {
        resolveComposerAttachmentPlaceholder(message.requestId, null);
        $('composerHint').textContent = '剪贴板中没有可附加的内容';
      }
    }
    if (message.type === 'contextDropResolved') {
      const contexts = Array.isArray(message.contexts) ? message.contexts : [];
      if (!contexts.length) {
        resolveComposerAttachmentPlaceholder(message.requestId, null);
        $('composerHint').textContent = message.error || '没有识别到可拖入的文件或选区';
      } else {
        const first = addPastedContext(contexts[0], `${message.requestId}-0`);
        resolveComposerAttachmentPlaceholder(message.requestId, first);
        for (let index = 1; index < contexts.length; index += 1) {
          const item = addPastedContext(contexts[index], `${message.requestId}-${index}`);
          if (item) insertNodeAtComposerCaret(makeAttachmentNode({ context: item }));
        }
        state.lastComposerMutation = { kind: 'attachment', id: state.pastedContexts.at(-1)?.id };
        toast(`已附加 ${contexts.length} 个文件/选区`);
      }
      renderEditorContext();
    }
    if (message.type === 'externalContextsAttached') {
      const contexts = Array.isArray(message.contexts) ? message.contexts : [];
      for (const context of contexts) {
        const item = addPastedContext(context, `external-${Date.now()}-${Math.random().toString(36).slice(2)}`);
        if (item) insertNodeAtComposerCaret(makeAttachmentNode({ context: item }));
      }
      const latest = state.pastedContexts.at(-1);
      if (latest) state.lastComposerMutation = { kind: 'attachment', id: latest.id };
      renderEditorContext();
      $('prompt').focus();
      toast(contexts.length ? `已把 ${contexts.length} 个文件/选区插入 Chat` : '没有可附加的文件或选区', !contexts.length);
    }
    if (message.type === 'editorContext') {
      const previousWorkspace = canonicalWorkspace(state.editorContext?.workspacePath);
      const nextWorkspace = canonicalWorkspace(message.context?.workspacePath);
      state.editorContext = message.context;
      if (previousWorkspace && nextWorkspace && nextWorkspace !== previousWorkspace) {
        state.attachedContext = null;
        resetConversationForWorkspace();
      }
      if (state.attachRequested) {
        const requestedKind = state.attachRequested;
        state.attachRequested = false;
        const source = message.context || {};
        let attachment = null;
        if (requestedKind === 'selection' && source.selectionText) {
          attachment = {
            kind: 'selection', title: `${source.path}:${source.selectionStartLine}-${source.selectionEndLine}`,
            path: source.path, absolutePath: source.absolutePath, startLine: source.selectionStartLine,
            endLine: source.selectionEndLine, language: source.language, content: source.selectionText,
            truncated: source.selectionTruncated,
          };
        } else if (requestedKind === 'file' && source.available) {
          attachment = {
            kind: 'file', title: source.path, path: source.path, absolutePath: source.absolutePath,
            startLine: source.excerptStartLine || 1, endLine: source.excerptEndLine || 1,
            language: source.language, content: source.fileExcerpt || '',
          };
        } else if (requestedKind === 'workspace' && source.workspacePath) {
          attachment = {
            kind: 'workspace', title: `Workspace · ${source.workspacePath.replaceAll('\\', '/').split('/').filter(Boolean).at(-1) || 'project'}`,
            path: '', workspacePath: source.workspacePath, language: 'workspace',
            content: 'Use the current Workspace repository map and retrieval index at this position in the user message.',
          };
        }
        if (attachment) {
          const item = addPastedContext(attachment, `attach-${Date.now()}-${Math.random().toString(36).slice(2)}`);
          if (item) {
            insertNodeAtComposerCaret(makeAttachmentNode({ context: item }));
            state.lastComposerMutation = { kind: 'attachment', id: item.id };
            toast(`${requestedKind === 'selection' ? '@selection' : requestedKind === 'workspace' ? '@workspace' : '@file'} 已插入消息`);
          }
        } else {
          toast(requestedKind === 'selection' ? '请先在编辑器中选中代码' : '当前没有可附加的编辑器或 Workspace', true);
        }
      }
      renderEditorContext();
      const pending = state.editorContextRequests.get(message.requestId);
      if (pending) {
        clearTimeout(pending.timer);
        state.editorContextRequests.delete(message.requestId);
        pending.resolve(message.context);
      }
      if (nextWorkspace !== previousWorkspace) {
        state.liveRuns = [];
        state.liveRunsSignature = '';
        renderSessionTabs();
        loadTrackedChanges();
        refreshExecutionSessions();
      }
    }
    if (message.type === 'showTab') switchTab(message.tab);
    if (message.type === 'commandResult') {
      addEvent('terminal', message.ok ? 'tool' : 'blocked', (message.ok ? '▶ ' : '🚫 ') + message.command, message.message);
    }
  });

  loadCatalog();
  connectWebSocket();
  pollExecution();
  refreshExecutionSessions();
  loadTrackedChanges();
  vscode.postMessage({ type: 'webviewReady' });
  setInterval(() => {
    if (document.hidden) return;
    // The socket already delivers state and incremental events. Polling the
    // full trace snapshot at the same time only duplicates JSON parsing and
    // DOM work; keep HTTP strictly as a disconnected recovery path.
    if (state.ws?.readyState === WebSocket.OPEN) return;
    pollExecution();
  }, 2500);
  setInterval(() => {
    if (!document.hidden) refreshExecutionSessions();
  }, 4000);
})();
} catch (error) {
  const connection = document.getElementById('connection');
  if (connection) {
    connection.className = 'connection offline';
    connection.textContent = 'UI 错误：' + (error?.message || String(error));
  }
  document.body.dataset.scriptError = error?.stack || error?.message || String(error);
}
