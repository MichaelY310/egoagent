// Versioned entry filename prevents Void's Web Extension Host from combining
// a cached main module with current media files after local upgrades.
const vscode = require('vscode');
const remoteWorkspaces = require('./remote-workspaces');
const fetch = remoteWorkspaces.fetch;

const DOCUMENT_SELECTOR = [
  { scheme: 'file' },
  { scheme: 'vscode-remote' },
  { scheme: 'untitled' },
];

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('"', '&quot;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;');
}


function splitLines(text) {
  return String(text).replaceAll('\r\n', '\n').split('\n');
}

function reconstructTrackedOriginal(currentText, change, locateHunk) {
  const currentLines = splitLines(currentText);
  const output = [];
  let cursor = 0;
  const hunks = [...(change?.hunks || [])].sort((left, right) => (
    Number(left.old_start || 0) - Number(right.old_start || 0)
  ));
  for (const hunk of hunks) {
    const start = Math.max(cursor, Number(locateHunk(hunk)) || 0);
    output.push(...currentLines.slice(cursor, start));
    const visibleLines = hunk.status === 'rejected' ? hunk.old_lines : hunk.new_lines;
    const visibleCount = Math.max(0, (visibleLines || []).length - ((visibleLines || []).at(-1) === '' ? 1 : 0));
    if (hunk.status === 'pending') {
      output.push(...(hunk.old_lines || []).map((line) => String(line).replace(/\r?\n$/, '')));
    } else {
      // Accepted hunks already belong to the baseline; rejected hunks have
      // already been restored. Only pending hunks remain red/green in review.
      output.push(...currentLines.slice(start, start + visibleCount));
    }
    cursor = start + visibleCount;
  }
  output.push(...currentLines.slice(cursor));
  const eol = String(currentText).includes('\r\n') ? '\r\n' : '\n';
  return output.join(eol);
}

function changesForReviewTransaction(changes, transactionId) {
  const selected = String(transactionId || '');
  if (!selected) return [];
  return (Array.isArray(changes) ? changes : []).filter((change) => (
    String(change?.transaction_id || '') === selected
  ));
}

function reviewChangeRecency(change) {
  const timestamp = Date.parse(String(change?.updated_at || change?.created_at || ''));
  if (Number.isFinite(timestamp)) return timestamp;
  const numeric = Number(change?.timestamp ?? change?.index ?? 0);
  return Number.isFinite(numeric) ? numeric : 0;
}

function isMaterializedReviewChange(change) {
  return change?.file_exists !== false || Boolean(change?.is_deleted_file);
}

function latestPendingReviewTransaction(changes) {
  const pending = (Array.isArray(changes) ? changes : []).filter((change) => (
    isMaterializedReviewChange(change)
    &&
    change?.transaction_id
    && (change.hunks || []).some((hunk) => hunk.status === 'pending')
  ));
  pending.sort((left, right) => reviewChangeRecency(right) - reviewChangeRecency(left));
  return String(pending[0]?.transaction_id || '');
}

function fullDocumentRange(document) {
  return new vscode.Range(document.positionAt(0), document.positionAt(document.getText().length));
}

function displayPath(uri) {
  const normalize = (value) => decodeURIComponent(String(value || '')).replaceAll('\\', '/').replace(/^\/(\w:\/)/, '$1');
  const target = normalize(uri.path || uri.fsPath);
  for (const folder of vscode.workspace.workspaceFolders || []) {
    const root = normalize(folder.uri.path || folder.uri.fsPath).replace(/\/$/, '');
    if (target.toLowerCase().startsWith(root.toLowerCase() + '/')) return target.slice(root.length + 1);
    if (target.toLowerCase() === root.toLowerCase()) return folder.name;
  }
  try {
    const relative = vscode.workspace.asRelativePath(uri, false).replaceAll('\\', '/');
    if (!relative.startsWith('../')) return relative;
  } catch {}
  return target || uri.toString();
}

function selectionLineRange(selection) {
  if (!selection || selection.isEmpty) return { startLine: 0, endLine: 0, lineCount: 0 };
  const startLine = Number(selection.start.line || 0) + 1;
  // VS Code ranges are end-exclusive. A whole-line selection commonly ends at
  // column zero of the next line, which must not be advertised as selected.
  const endLine = Math.max(
    startLine,
    Number(selection.end.line || 0) + (Number(selection.end.character || 0) > 0 ? 1 : 0),
  );
  return { startLine, endLine, lineCount: endLine - startLine + 1 };
}

function normalizedClipboardText(value) {
  return String(value || '').replaceAll('\r\n', '\n').replace(/\n$/, '');
}

function clipboardLineCount(value) {
  const normalized = String(value || '').replaceAll('\r\n', '\n').replace(/\n+$/, '');
  return normalized ? normalized.split('\n').length : 0;
}

async function readClipboardAfterCopy(previousText = '', timeoutMs = 600) {
  // On Windows the terminal copy command can resolve a little before the OS
  // clipboard becomes visible to the extension host.  Reading immediately
  // occasionally returned the previous editor/clipboard value, so the Chat
  // later classified it as a generic Clipboard attachment.  Wait briefly for
  // a changed value, while still accepting an intentionally repeated copy.
  const startedAt = Date.now();
  let latest = '';
  do {
    await new Promise((resolve) => setTimeout(resolve, 30));
    try { latest = await vscode.env.clipboard.readText(); } catch { latest = ''; }
    if (latest && normalizedClipboardText(latest) !== normalizedClipboardText(previousText)) return latest;
    if (latest && Date.now() - startedAt >= 150) return latest;
  } while (Date.now() - startedAt < timeoutMs);
  return latest;
}

function extractLocalSymbols(document) {
  const results = [];
  const language = document.languageId;
  const patterns = language === 'python'
    ? [{ regex: /^\s*class\s+([A-Za-z_]\w*)/, kind: 'Class' }, { regex: /^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)/, kind: 'Function' }]
    : [{ regex: /^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)/, kind: 'Class' }, { regex: /^\s*(?:(?:export|async)\s+)*function\s+([A-Za-z_$][\w$]*)/, kind: 'Function' }, { regex: /^\s*(?:export\s+)?(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(/, kind: 'Function' }];
  for (let line = 0; line < document.lineCount && results.length < 80; line += 1) {
    const text = document.lineAt(line).text;
    for (const pattern of patterns) {
      const match = pattern.regex.exec(text);
      if (match) {
        results.push({ name: match[1], kind: pattern.kind, line: line + 1, detail: text.trim().slice(0, 160) });
        break;
      }
    }
  }
  return results;
}

class LocalMetrics {
  constructor(context) {
    this.context = context;
    this.values = context.globalState.get('egoagent.localMetrics', {
      completionsOffered: 0,
      completionsAccepted: 0,
      proposalsCreated: 0,
      hunksAccepted: 0,
      hunksRejected: 0,
      reviewsRun: 0,
    });
  }

  bump(name, amount = 1) {
    this.values[name] = Number(this.values[name] || 0) + amount;
    this.context.globalState.update('egoagent.localMetrics', this.values);
  }

  snapshot() { return { ...this.values }; }
}

class AIClient {
  constructor() {
    this.statusCache = new Map();
    this.statusPending = new Map();
  }

  get enabled() {
    return vscode.workspace.getConfiguration('egoagent').get('ai.enabled', true);
  }

  get backendUrl() {
    return remoteWorkspaces.backendUrl();
  }

  operationRole(operation) {
    return ({
      completion: 'autocomplete',
      'next-edit': 'edit',
      'inline-edit': 'edit',
      edit: 'edit',
      review: 'chat',
      'commit-message': 'chat',
    })[operation];
  }

  async supports(role) {
    if (!this.enabled) return false;
    const status = await this.status(false, role);
    if (!status?.configured || status?.health === false) return false;
    const capabilities = status.capabilities || {};
    if (Object.prototype.hasOwnProperty.call(capabilities, role)) return capabilities[role] === true;
    // An unprobed provider remains backward compatible. Once a probe exists,
    // unsupported roles are rejected before the operation request starts.
    return true;
  }

  async request(operation, payload, timeoutMs, cancellationToken) {
    if (cancellationToken?.isCancellationRequested) throw new Error('AI request cancelled');
    if (!this.enabled) throw new Error('AI assistance is disabled in EgoAgent settings');
    const role = this.operationRole(operation);
    if (role && !(await this.supports(role))) {
      throw new Error(`Configured model is unavailable or does not support the '${role}' role`);
    }
    if (cancellationToken?.isCancellationRequested) throw new Error('AI request cancelled');
    const controller = new AbortController();
    const timeout = Number(timeoutMs || vscode.workspace.getConfiguration('egoagent').get('ai.requestTimeoutMs', 60000));
    const timer = setTimeout(() => controller.abort(), timeout);
    const cancellation = cancellationToken?.onCancellationRequested?.(() => controller.abort());
    if (cancellationToken?.isCancellationRequested) controller.abort();
    try {
      const response = await fetch(`${this.backendUrl}/api/ai/${encodeURIComponent(operation)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload || {}),
        signal: controller.signal,
      });
      const text = await response.text();
      let data = {};
      try { data = text ? JSON.parse(text) : {}; } catch { data = { error: text }; }
      if (!response.ok) throw new Error(data.error || `AI request failed (${response.status})`);
      return data;
    } catch (error) {
      if (error?.name === 'AbortError') {
        if (cancellationToken?.isCancellationRequested) throw new Error('AI request cancelled');
        throw new Error(`AI request timed out after ${timeout} ms`);
      }
      throw error;
    } finally {
      clearTimeout(timer);
      cancellation?.dispose?.();
    }
  }

  async status(force = false, role = 'chat') {
    const key = `${this.backendUrl}|${role}`;
    const cached = this.statusCache.get(key);
    if (!force && cached && Date.now() - cached.at < 15000) return cached.value;
    if (this.statusPending.has(key)) return this.statusPending.get(key);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 2000);
    const pending = (async () => {
      let value;
      try {
        const response = await fetch(`${this.backendUrl}/api/ai/status?role=${encodeURIComponent(role)}`, { signal: controller.signal });
        value = response.ok ? await response.json() : { configured: false };
      } catch { value = { configured: false }; }
      finally { clearTimeout(timer); this.statusPending.delete(key); }
      this.statusCache.set(key, { value, at: Date.now() });
      return value;
    })();
    this.statusPending.set(key, pending);
    return pending;
  }
}

function fsPathForBackend(value) {
  // Remote Void documents use vscode-remote URIs. `fsPath` for a non-file URI
  // may include a UNC authority, while `path` is the stable `/C:/...` value
  // that maps to the backend's Windows path, or a Linux absolute path.
  let text = String(value?.path || value?.fsPath || value || '').replaceAll('\\', '/');
  try { text = decodeURIComponent(text); } catch {}
  text = text.replace(/^\/+([A-Za-z]:\/)/, '$1');
  return text === '/' ? text : text.replace(/\/+$/, '');
}

function normalizedFsPath(value) {
  const path = fsPathForBackend(value);
  // Linux foo.py and Foo.py are different files. Only Windows/UNC paths
  // should use the case-insensitive comparison of the original local IDE.
  return /^[A-Za-z]:\//.test(path) || path.startsWith('//') ? path.toLowerCase() : path;
}

function sameDocumentPath(uri, filePath) {
  return normalizedFsPath(uri) === normalizedFsPath(filePath);
}

function workspaceUriForPath(filePath) {
  const target = normalizedFsPath(filePath);
  for (const folder of vscode.workspace.workspaceFolders || []) {
    const root = normalizedFsPath(folder.uri);
    if (target === root || target.startsWith(`${root}/`)) {
      const relative = String(filePath).replaceAll('\\', '/').slice(root.length).replace(/^\/+/, '');
      return vscode.Uri.joinPath(folder.uri, ...relative.split('/').filter(Boolean));
    }
  }
  return vscode.Uri.file(filePath);
}

function applyLineHunks(originalText, rawHunks, eol = '\n') {
  const originalLines = splitLines(originalText);
  const hunks = (Array.isArray(rawHunks) ? rawHunks : [])
    .map((hunk, index) => ({
      start: Math.max(0, Math.min(originalLines.length, Number(hunk.start) || 0)),
      end: Math.max(0, Math.min(originalLines.length, Number(hunk.end) || 0)),
      newLines: Array.isArray(hunk.newLines) ? hunk.newLines.map(String) : splitLines(hunk.newText || ''),
      label: hunk.label || `改动 ${index + 1}`,
    }))
    .filter((hunk) => hunk.end >= hunk.start)
    .sort((a, b) => a.start - b.start || a.end - b.end);
  const output = [];
  let cursor = 0;
  for (const hunk of hunks) {
    if (hunk.start < cursor) throw new Error('编辑结果包含重叠代码块');
    output.push(...originalLines.slice(cursor, hunk.start), ...hunk.newLines);
    cursor = hunk.end;
  }
  output.push(...originalLines.slice(cursor));
  return output.join(eol);
}

class ChangeReviewManager {
  constructor(context, metrics, onStateChanged, aiClient) {
    this.context = context;
    this.metrics = metrics;
    this.onStateChanged = onStateChanged;
    this.aiClient = aiClient;
    const stored = context.workspaceState?.get('egoagent.changeReviewProposals.v2', []);
    this.proposals = (Array.isArray(stored) ? stored : []).filter((proposal) => (
      proposal && typeof proposal.id === 'string' && typeof proposal.uri === 'string'
      && typeof proposal.originalText === 'string' && typeof proposal.lastAppliedText === 'string'
      && Array.isArray(proposal.hunks)
    )).slice(0, 30);
    this.backendChanges = [];
    this.activeBackendTransactionId = '';
    this.backendSignature = '';
    this.previewDrafts = new Map();
    this.autoOpenedReviewKeys = new Set();
    this.codeLensEmitter = new vscode.EventEmitter();
    this.onDidChangeCodeLenses = this.codeLensEmitter.event;
    this.inlayHintEmitter = new vscode.EventEmitter();
    this.onDidChangeInlayHints = this.inlayHintEmitter.event;
    this.contentEmitter = new vscode.EventEmitter();
    this.pendingInsertedDecoration = vscode.window.createTextEditorDecorationType({
      isWholeLine: true,
      backgroundColor: new vscode.ThemeColor('diffEditor.insertedLineBackground'),
      overviewRulerColor: '#3fb950',
      overviewRulerLane: vscode.OverviewRulerLane.Right,
    });
    this.pendingRemovedDecoration = vscode.window.createTextEditorDecorationType({
      gutterIconPath: vscode.Uri.joinPath(context.extensionUri, 'media', 'deleted-change.svg'),
      gutterIconSize: 'contain',
      overviewRulerColor: '#f85149',
      overviewRulerLane: vscode.OverviewRulerLane.Right,
    });

    const originalProvider = {
      onDidChange: this.contentEmitter.event,
      provideTextDocumentContent: (uri) => this.virtualContent(uri, false),
    };
    const proposedProvider = {
      onDidChange: this.contentEmitter.event,
      provideTextDocumentContent: (uri) => this.virtualContent(uri, true),
    };
    const previewProvider = {
      onDidChange: this.contentEmitter.event,
      provideTextDocumentContent: (uri) => this.previewDrafts.get(uri.toString()) || 'Preview expired.',
    };
    const reviewProviders = [
      this.codeLensEmitter,
      this.inlayHintEmitter,
      this.contentEmitter,
      this.pendingInsertedDecoration,
      this.pendingRemovedDecoration,
      vscode.workspace.registerTextDocumentContentProvider('egoagent-original', originalProvider),
      vscode.workspace.registerTextDocumentContentProvider('egoagent-proposed', proposedProvider),
      vscode.workspace.registerTextDocumentContentProvider('egoagent-preview', previewProvider),
      vscode.languages.registerCodeLensProvider(DOCUMENT_SELECTOR, this),
      vscode.window.onDidChangeActiveTextEditor((editor) => {
        this.decorate(editor);
        void this.openPendingReviewForEditor(editor);
      }),
      vscode.workspace.onDidChangeConfiguration((event) => {
        if (
          event.affectsConfiguration('egoagent.review.inlineActions')
          || event.affectsConfiguration('editor.codeLens')
          || event.affectsConfiguration('diffEditor.codeLens')
        ) {
          this.codeLensEmitter.fire();
          this.inlayHintEmitter.fire();
        }
      }),
    ];
    // CodeLens is primary. Inlay Hint is a mutually-exclusive fallback for
    // profiles that disable CodeLens, so the same controls never overlap.
    if (typeof vscode.languages.registerInlayHintsProvider === 'function') {
      reviewProviders.push(vscode.languages.registerInlayHintsProvider(DOCUMENT_SELECTOR, this));
    }
    context.subscriptions.push(...reviewProviders);
  }

  async propose(document, title, rawHunks) {
    const originalText = document.getText();
    const originalLines = splitLines(originalText);
    const hunks = rawHunks
      .map((hunk, index) => ({
        id: index,
        start: Math.max(0, Math.min(originalLines.length, Number(hunk.start))),
        end: Math.max(0, Math.min(originalLines.length, Number(hunk.end))),
        oldLines: [],
        newLines: Array.isArray(hunk.newLines) ? hunk.newLines : splitLines(hunk.newText || ''),
        label: hunk.label || `改动 ${index + 1}`,
        status: 'pending',
        decisionHistory: [],
        decidedAt: 0,
      }))
      .filter((hunk) => hunk.end >= hunk.start)
      .sort((a, b) => a.start - b.start || a.end - b.end);

    let previousEnd = -1;
    for (const hunk of hunks) {
      if (hunk.start < previousEnd) throw new Error('本地编辑提案包含重叠改动');
      hunk.oldLines = originalLines.slice(hunk.start, hunk.end);
      previousEnd = hunk.end;
    }
    if (!hunks.length) throw new Error('当前文件没有可生成的本地改动');

    const proposal = {
      id: `local-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      title,
      uri: document.uri.toString(),
      path: displayPath(document.uri),
      language: document.languageId,
      originalText,
      lastAppliedText: originalText,
      eol: document.eol === vscode.EndOfLine.CRLF ? '\r\n' : '\n',
      createdAt: Date.now(),
      hunks,
    };
    const proposedText = this.buildText(proposal);
    const edit = new vscode.WorkspaceEdit();
    edit.replace(document.uri, fullDocumentRange(document), proposedText);
    if (!await vscode.workspace.applyEdit(edit)) throw new Error('无法将 Agent 改动应用到编辑器');
    proposal.lastAppliedText = proposedText;
    this.proposals.unshift(proposal);
    this.proposals = this.proposals.slice(0, 30);
    this.metrics.bump('proposalsCreated');
    this.emit();
    return proposal;
  }

  getProposal(id) { return this.proposals.find((proposal) => proposal.id === id); }

  buildText(proposal) {
    const original = splitLines(proposal.originalText);
    const output = [];
    let cursor = 0;
    for (const hunk of proposal.hunks) {
      output.push(...original.slice(cursor, hunk.start));
      if (hunk.status === 'rejected') {
        output.push(...hunk.oldLines);
      } else {
        output.push(...hunk.newLines);
      }
      cursor = hunk.end;
    }
    output.push(...original.slice(cursor));
    return output.join(proposal.eol);
  }

  async updateHunk(proposalId, hunkId, status) {
    const proposal = this.getProposal(proposalId);
    const hunk = proposal?.hunks.find((item) => item.id === Number(hunkId));
    if (!proposal || !hunk || hunk.status !== 'pending') return false;
    const document = await vscode.workspace.openTextDocument(vscode.Uri.parse(proposal.uri));
    if (document.getText() !== proposal.lastAppliedText) {
      vscode.window.showWarningMessage('文件在审查期间被手动修改。为避免覆盖你的代码，本次操作已取消。');
      return false;
    }
    const previous = hunk.status;
    const previousDecidedAt = Number(hunk.decidedAt || 0);
    hunk.decisionHistory.push(previous);
    hunk.status = status;
    hunk.decidedAt = Date.now();
    const nextText = this.buildText(proposal);
    if (nextText !== proposal.lastAppliedText) {
      const edit = new vscode.WorkspaceEdit();
      edit.replace(document.uri, fullDocumentRange(document), nextText);
      if (!await vscode.workspace.applyEdit(edit)) {
        hunk.status = previous;
        hunk.decidedAt = previousDecidedAt;
        hunk.decisionHistory.pop();
        return false;
      }
      proposal.lastAppliedText = nextText;
    }
    this.metrics.bump(status === 'accepted' ? 'hunksAccepted' : 'hunksRejected');
    this.emit();
    return true;
  }

  async updateAll(proposalId, status) {
    const proposal = this.getProposal(proposalId);
    if (!proposal) return false;
    const document = await vscode.workspace.openTextDocument(vscode.Uri.parse(proposal.uri));
    if (document.getText() !== proposal.lastAppliedText) {
      vscode.window.showWarningMessage('文件在审查期间被手动修改。为避免覆盖你的代码，本次操作已取消。');
      return false;
    }
    let changed = 0;
    const changedHunks = [];
    for (const hunk of proposal.hunks) {
      if (hunk.status === 'pending') {
        hunk.decisionHistory.push(hunk.status);
        hunk.status = status;
        hunk.decidedAt = Date.now();
        changedHunks.push(hunk);
        changed += 1;
      }
    }
    if (!changed) return false;
    const nextText = this.buildText(proposal);
    if (nextText !== proposal.lastAppliedText) {
      const edit = new vscode.WorkspaceEdit();
      edit.replace(document.uri, fullDocumentRange(document), nextText);
      if (!await vscode.workspace.applyEdit(edit)) {
        for (const hunk of changedHunks) {
          hunk.status = hunk.decisionHistory.pop() || 'pending';
          hunk.decidedAt = 0;
        }
        return false;
      }
      proposal.lastAppliedText = nextText;
    }
    this.metrics.bump(status === 'accepted' ? 'hunksAccepted' : 'hunksRejected', changed);
    this.emit();
    return true;
  }

  async undoHunk(proposalId, hunkId) {
    const proposal = this.getProposal(proposalId);
    const hunk = proposal?.hunks.find((item) => item.id === Number(hunkId));
    if (!proposal || !hunk || !hunk.decisionHistory.length) return false;
    const document = await vscode.workspace.openTextDocument(vscode.Uri.parse(proposal.uri));
    if (document.getText() !== proposal.lastAppliedText) {
      vscode.window.showWarningMessage('文件在审查期间被手动修改。为避免覆盖你的代码，本次撤销决定已取消。');
      return false;
    }
    const decidedStatus = hunk.status;
    const decidedAt = Number(hunk.decidedAt || 0);
    const previous = hunk.decisionHistory.pop();
    hunk.status = previous;
    hunk.decidedAt = previous === 'pending' ? 0 : Date.now();
    const nextText = this.buildText(proposal);
    if (nextText !== proposal.lastAppliedText) {
      const edit = new vscode.WorkspaceEdit();
      edit.replace(document.uri, fullDocumentRange(document), nextText);
      if (!await vscode.workspace.applyEdit(edit)) {
        hunk.status = decidedStatus;
        hunk.decidedAt = decidedAt;
        hunk.decisionHistory.push(previous);
        return false;
      }
      proposal.lastAppliedText = nextText;
    }
    this.emit();
    return true;
  }

  async openDiff(proposalId) {
    const proposal = this.getProposal(proposalId);
    if (!proposal) return;
    const suffix = proposal.path.replaceAll('\\', '/').split('/').pop() || 'change';
    const query = `id=${encodeURIComponent(proposal.id)}`;
    const before = vscode.Uri.from({ scheme: 'egoagent-original', path: `/${suffix}`, query });
    const after = vscode.Uri.from({ scheme: 'egoagent-proposed', path: `/${suffix}`, query });
    await vscode.commands.executeCommand('vscode.diff', before, after, `EgoAgent Review · ${proposal.path}`, { preview: false });
    await this.preferInlineDiff();
  }

  backendOriginalText(change, currentText) {
    return reconstructTrackedOriginal(currentText, change, (hunk) => this.backendHunkLine(change, hunk));
  }

  async preferInlineDiff() {
    if (!vscode.workspace.getConfiguration('egoagent').get('review.preferInlineDiff', true)) return;
    if (!vscode.workspace.getConfiguration('diffEditor').get('renderSideBySide', true)) return;
    try { await vscode.commands.executeCommand('toggle.diff.renderSideBySide'); } catch {}
  }

  async openBackendDiff(changeSelector, hunkId, options = {}) {
    const change = this.getBackendChange(changeSelector);
    if (!change) return vscode.window.showWarningMessage('找不到对应的 Agent 改动，请刷新后重试');
    this.selectBackendTransaction(change.transaction_id);
    if (change.change_type !== 'text') {
      return vscode.window.showInformationMessage('二进制文件或移动操作没有逐行文本 Diff');
    }
    const fileUri = workspaceUriForPath(change.file_path);
    let document;
    try { document = await vscode.workspace.openTextDocument(fileUri); } catch {}
    let exact;
    try {
      const response = await fetch(`${this.aiClient.backendUrl}/api/session/changes/content?id=${encodeURIComponent(String(change.id || change.index))}`);
      if (response.ok) exact = await response.json();
    } catch {}
    const suffix = displayPath(fileUri).replaceAll('\\', '/').split('/').pop() || 'change';
    const before = vscode.Uri.from({
      scheme: 'egoagent-preview',
      path: `/${encodeURIComponent(suffix)}.before`,
      query: `backend=${encodeURIComponent(String(change.id || change.index))}&at=${Date.now()}`,
    });
    const currentText = document?.getText() || '';
    const hasExactOld = exact && Object.prototype.hasOwnProperty.call(exact, 'old_content');
    const hasExactNew = exact && Object.prototype.hasOwnProperty.call(exact, 'new_content');
    const useLiveEditor = Boolean(document && change.file_exists !== false && (
      !change.proposed_revision || change.materialized_revision === change.proposed_revision
    ));
    const after = useLiveEditor ? fileUri : vscode.Uri.from({
      scheme: 'egoagent-preview',
      path: `/${encodeURIComponent(suffix)}.after`,
      query: `backend=${encodeURIComponent(String(change.id || change.index))}&at=${Date.now()}`,
    });
    const beforeText = useLiveEditor
      ? this.backendOriginalText(change, currentText)
      : hasExactOld ? String(exact.old_content || '') : this.backendOriginalText(change, currentText);
    const afterText = useLiveEditor ? currentText : hasExactNew ? String(exact.new_content || '') : currentText;
    this.previewDrafts.set(before.toString(), beforeText);
    if (!useLiveEditor) this.previewDrafts.set(after.toString(), afterText);
    this.contentEmitter.fire(before);
    if (!useLiveEditor) this.contentEmitter.fire(after);
    const hunk = (change.hunks || []).find((item) => String(item.id) === String(hunkId));
    const line = Math.min(
      Math.max(0, hunk ? this.backendHunkLine(change, hunk) : 0),
      Math.max(0, splitLines(afterText).length - 1),
    );
    const selection = new vscode.Range(line, 0, line, splitLines(afterText)[line]?.length || 0);
    await vscode.commands.executeCommand(
      'vscode.diff',
      before,
      after,
      `${displayPath(fileUri)} · Agent Changes`,
      { preview: false, selection },
    );
    await this.preferInlineDiff();
    this.codeLensEmitter.fire();
    this.inlayHintEmitter.fire();
    if (options.automatic) this.decorate(vscode.window.activeTextEditor);
    return true;
  }

  async reconcileBackendReview(changeSelector, options = {}) {
    const change = this.getBackendChange(changeSelector);
    if (!change) return false;
    const activeReview = this.activeReviewDiffMatches(change);
    if (!activeReview && !options.reopenPending) return false;
    const pending = (change.hunks || []).find((hunk) => (
      hunk.status === 'pending' && String(hunk.id) === String(options.hunkId || '')
    )) || (change.hunks || []).find((hunk) => hunk.status === 'pending');
    if (activeReview) await vscode.commands.executeCommand('workbench.action.closeActiveEditor');
    if (pending) {
      await this.openBackendDiff(change.id || change.index, pending.id, { automatic: true });
    } else if (activeReview && change.file_exists !== false) {
      const document = await vscode.workspace.openTextDocument(workspaceUriForPath(change.file_path));
      await vscode.window.showTextDocument(document, { preview: false });
    }
    return true;
  }

  async showDraftPreview(document, proposedText, title, existingUri) {
    const uri = existingUri || vscode.Uri.from({
      scheme: 'egoagent-preview',
      path: `/${encodeURIComponent(displayPath(document.uri).split('/').pop() || 'edit')}`,
      query: `id=${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    });
    this.previewDrafts.set(uri.toString(), proposedText);
    this.contentEmitter.fire(uri);
    if (!existingUri) {
      await vscode.commands.executeCommand(
        'vscode.diff', document.uri, uri, title || `EgoAgent Inline Edit · ${displayPath(document.uri)}`,
        { preview: true },
      );
    }
    return uri;
  }

  async closeDraftPreview(uri) {
    if (!uri) return;
    if (vscode.window.activeTextEditor?.document?.uri?.toString() === uri.toString()) {
      await vscode.commands.executeCommand('workbench.action.closeActiveEditor');
    }
    this.previewDrafts.delete(uri.toString());
    this.contentEmitter.fire(uri);
  }

  virtualContent(uri, proposed) {
    const match = /(?:^|&)id=([^&]+)/.exec(uri.query || '');
    const proposal = match ? this.getProposal(decodeURIComponent(match[1])) : undefined;
    if (!proposal) return 'This EgoAgent change proposal is no longer available.';
    return proposed ? this.buildText(proposal) : proposal.originalText;
  }

  serialize() {
    return this.proposals.map((proposal) => ({
      id: proposal.id,
      title: proposal.title,
      path: proposal.path,
      language: proposal.language,
      createdAt: proposal.createdAt,
      hunks: proposal.hunks.map((hunk) => ({
        id: hunk.id,
        label: hunk.label,
        status: hunk.status,
        canUndo: hunk.decisionHistory.length > 0,
        oldStart: hunk.start + 1,
        newStart: hunk.start + 1,
        oldLines: hunk.oldLines.slice(0, 80),
        newLines: hunk.newLines.slice(0, 80),
      })),
    }));
  }

  emit() {
    void this.context.workspaceState?.update('egoagent.changeReviewProposals.v2', this.proposals);
    this.codeLensEmitter.fire();
    this.inlayHintEmitter.fire();
    this.contentEmitter.fire(vscode.Uri.parse('egoagent-original:/change'));
    this.contentEmitter.fire(vscode.Uri.parse('egoagent-proposed:/change'));
    this.decorate(vscode.window.activeTextEditor);
    this.onStateChanged?.(this.serialize());
  }

  syncBackendChanges(changes, activeTransactionId) {
    const normalized = (Array.isArray(changes) ? changes : []).filter(isMaterializedReviewChange);
    if (activeTransactionId !== undefined) {
      this.activeBackendTransactionId = String(activeTransactionId || '');
    }
    const signature = JSON.stringify([this.activeBackendTransactionId, normalized]);
    if (signature === this.backendSignature) return;
    this.backendSignature = signature;
    this.backendChanges = normalized;
    this.codeLensEmitter.fire();
    this.inlayHintEmitter.fire();
    this.decorate(vscode.window.activeTextEditor);
    this.onStateChanged?.(this.serialize());
    void this.openPendingReviewForEditor(vscode.window.activeTextEditor);
  }

  selectBackendTransaction(transactionId) {
    const next = String(transactionId || '');
    if (next === this.activeBackendTransactionId) return;
    this.activeBackendTransactionId = next;
    this.backendSignature = '';
    this.codeLensEmitter.fire();
    this.inlayHintEmitter.fire();
    this.decorate(vscode.window.activeTextEditor);
  }

  activeBackendChanges() {
    return changesForReviewTransaction(this.backendChanges, this.activeBackendTransactionId);
  }

  pendingReviewKey(change) {
    const hunks = (change?.hunks || [])
      .filter((hunk) => hunk.status === 'pending')
      .map((hunk) => hunk.id)
      .join(',');
    return `${change?.id || change?.index || ''}:${hunks}`;
  }

  activeReviewDiffMatches(change) {
    const input = vscode.window.tabGroups?.activeTabGroup?.activeTab?.input;
    if (!input?.original || !input?.modified || input.original.scheme !== 'egoagent-preview') return false;
    try { return sameDocumentPath(input.modified, change.file_path); } catch { return false; }
  }

  async openPendingReviewForEditor(editor) {
    if (!editor || editor.document.uri.scheme === 'egoagent-preview') return false;
    const change = this.pendingBackendChangesForDocument(editor.document)[0];
    const hunk = (change?.hunks || []).find((item) => item.status === 'pending');
    if (!change || !hunk || change.change_type !== 'text') return false;
    if (this.activeReviewDiffMatches(change)) return true;
    const key = this.pendingReviewKey(change);
    if (!key || this.autoOpenedReviewKeys.has(key)) return false;
    this.autoOpenedReviewKeys.add(key);
    try {
      await this.openBackendDiff(change.id || change.index, hunk.id, { automatic: true });
      return true;
    } catch (error) {
      this.autoOpenedReviewKeys.delete(key);
      console.error('Failed to open EgoAgent inline review', error);
      return false;
    }
  }

  pendingBackendChangesForDocument(document) {
    const scopedChanges = this.activeBackendTransactionId ? this.activeBackendChanges() : [];
    const matching = scopedChanges.filter((change) => {
      if (!(change.hunks || []).some((hunk) => hunk.status === 'pending')) return false;
      try { return sameDocumentPath(document.uri, change.file_path); } catch { return false; }
    }).sort((left, right) => reviewChangeRecency(right) - reviewChangeRecency(left));
    if (!matching.length) return [];
    const latestTransaction = String(matching[0].transaction_id || '');
    return latestTransaction
      ? matching.filter((change) => String(change.transaction_id || '') === latestTransaction)
      : matching.slice(0, 1);
  }

  getBackendChange(selector) {
    return this.backendChanges.find((change) => (
      String(change.id || '') === String(selector) || String(change.index) === String(selector)
    ));
  }

  decorate(editor) {
    if (!editor) {
      void vscode.commands.executeCommand('setContext', 'egoagent.reviewDecisionAvailable', false);
      return;
    }
    const activeTabInput = vscode.window.tabGroups?.activeTabGroup?.activeTab?.input;
    const nativeReviewDiff = activeTabInput?.original?.scheme === 'egoagent-preview'
      && activeTabInput?.modified?.toString() === editor.document.uri.toString();
    if (nativeReviewDiff) {
      // The native inline diff already renders every removed row red and every
      // inserted row green. Do not overlay the compact single-editor fallback.
      editor.setDecorations(this.pendingInsertedDecoration, []);
      editor.setDecorations(this.pendingRemovedDecoration, []);
      void vscode.commands.executeCommand(
        'setContext',
        'egoagent.reviewDecisionAvailable',
        Boolean(this.latestUndoTarget(editor.document)),
      );
      return;
    }
    const uri = editor.document.uri.toString();
    const proposals = this.proposals.filter((item) => item.uri === uri);
    const backendChanges = this.pendingBackendChangesForDocument(editor.document);
    const inserted = [];
    const removed = [];
    const lineCount = (lines) => Math.max(0, (lines || []).length - ((lines || []).at(-1) === '' ? 1 : 0));
    const rangeFor = (startLine, count) => {
      const start = Math.min(Math.max(0, Number(startLine) || 0), Math.max(0, editor.document.lineCount - 1));
      const end = Math.min(Math.max(start, start + Math.max(Number(count) || 1, 1) - 1), Math.max(0, editor.document.lineCount - 1));
      return new vscode.Range(start, 0, end, editor.document.lineAt(end).text.length);
    };
    const removedOption = (line, oldLines, label, oldStart) => {
      const currentLine = Math.min(Math.max(0, Number(line) || 0), Math.max(0, editor.document.lineCount - 1));
      const visibleOldLines = (oldLines || [])
        .map((value) => String(value).replace(/\r?\n$/, ''))
        .slice(0, 80);
      const firstOldLine = Math.max(1, Number(oldStart) || currentLine + 1);
      const hover = new vscode.MarkdownString();
      hover.appendMarkdown(`**${label || 'Agent 删除内容'}** · 原第 ${firstOldLine}–${firstOldLine + Math.max(0, visibleOldLines.length - 1)} 行\n\n`);
      hover.appendCodeblock(visibleOldLines.join('\n'));
      hover.appendMarkdown('\n使用上方 **Review Diff** 查看原生红绿对比。');
      const deletedCount = Math.max(1, visibleOldLines.length);
      const lineText = editor.document.lineAt(currentLine).text;
      return {
        // A deleted range has no surviving text to decorate. Anchor one small
        // red badge after the nearest real line instead of fabricating virtual
        // source rows (which corrupts wrapping and line-number layout).
        range: new vscode.Range(currentLine, lineText.length, currentLine, lineText.length),
        hoverMessage: hover,
        renderOptions: {
          after: {
            contentText: `  −${deletedCount} 行已删除`,
            margin: '0 0 0 1.25em',
            color: new vscode.ThemeColor('gitDecoration.deletedResourceForeground'),
            backgroundColor: new vscode.ThemeColor('diffEditor.removedTextBackground'),
            border: '1px solid',
            borderColor: new vscode.ThemeColor('gitDecoration.deletedResourceForeground'),
          },
        },
      };
    };

    for (const proposal of proposals) {
      let sourceCursor = 0;
      let currentLine = 0;
      for (const hunk of proposal.hunks) {
        currentLine += hunk.start - sourceCursor;
        const visibleLines = hunk.status === 'rejected' ? hunk.oldLines : hunk.newLines;
        const visibleCount = lineCount(visibleLines);
        if (hunk.status === 'pending') {
          if (visibleCount) inserted.push({ range: rangeFor(currentLine, visibleCount), hoverMessage: 'EgoAgent 新增内容 · 等待接受或拒绝' });
          if (lineCount(hunk.oldLines)) removed.push(removedOption(currentLine, hunk.oldLines, hunk.label, hunk.start + 1));
        }
        currentLine += visibleCount;
        sourceCursor = hunk.end;
      }
    }

    for (const change of backendChanges) {
      for (const hunk of change.hunks || []) {
        const oldLines = hunk.old_lines || [];
        const newLines = hunk.new_lines || [];
        const line = this.backendHunkLine(change, hunk);
        if (hunk.status === 'pending') {
          const count = lineCount(newLines);
          if (count) inserted.push({ range: rangeFor(line, count), hoverMessage: `${change.tool_name || 'DAG Agent'} 新增内容 · 等待接受或拒绝` });
          if (lineCount(oldLines)) removed.push(removedOption(line, oldLines, hunk.tag, Number(hunk.old_start || 0) + 1));
        }
      }
    }

    editor.setDecorations(this.pendingInsertedDecoration, inserted);
    editor.setDecorations(this.pendingRemovedDecoration, removed);
    void vscode.commands.executeCommand(
      'setContext',
      'egoagent.reviewDecisionAvailable',
      Boolean(this.latestUndoTarget(editor.document)),
    );
  }

  localHunkLine(proposal, targetHunk) {
    let sourceCursor = 0;
    let currentLine = 0;
    for (const hunk of proposal.hunks || []) {
      currentLine += Math.max(0, Number(hunk.start || 0) - sourceCursor);
      if (hunk === targetHunk || String(hunk.id) === String(targetHunk?.id)) return currentLine;
      const visibleLines = hunk.status === 'rejected' ? hunk.oldLines : hunk.newLines;
      currentLine += Math.max(0, (visibleLines || []).length - ((visibleLines || []).at(-1) === '' ? 1 : 0));
      sourceCursor = Number(hunk.end || 0);
    }
    return Math.max(0, Number(targetHunk?.start || 0));
  }

  backendHunkLine(change, targetHunk) {
    let sourceCursor = 0;
    let currentLine = 0;
    const hunks = [...(change?.hunks || [])].sort((left, right) => (
      Number(left.old_start || 0) - Number(right.old_start || 0)
    ));
    for (const hunk of hunks) {
      const start = Math.max(sourceCursor, Number(hunk.old_start || 0));
      currentLine += Math.max(0, start - sourceCursor);
      if (hunk === targetHunk || String(hunk.id) === String(targetHunk?.id)) return currentLine;
      const visibleLines = hunk.status === 'rejected' ? hunk.old_lines : hunk.new_lines;
      currentLine += Math.max(0, (visibleLines || []).length - ((visibleLines || []).at(-1) === '' ? 1 : 0));
      sourceCursor = Math.max(start, Number(hunk.old_start || 0) + Number(hunk.old_count ?? (hunk.old_lines || []).length));
    }
    return Math.max(0, Number(targetHunk?.new_start ?? targetHunk?.old_start ?? 0));
  }

  latestUndoTarget(document) {
    if (!document) return null;
    const targets = [];
    const uri = document.uri.toString();
    for (const proposal of this.proposals.filter((item) => item.uri === uri)) {
      for (const hunk of proposal.hunks || []) {
        if (!hunk.decisionHistory?.length) continue;
        targets.push({ source: 'local', proposalId: proposal.id, hunkId: hunk.id, at: Number(hunk.decidedAt || proposal.createdAt || 0) });
      }
    }
    for (const change of this.activeBackendChanges()) {
      try { if (!sameDocumentPath(document.uri, change.file_path)) continue; } catch { continue; }
      for (const hunk of change.hunks || []) {
        if (!hunk.can_undo) continue;
        targets.push({ source: 'backend', changeId: change.id || change.index, hunkId: hunk.id, at: Date.parse(change.updated_at || change.created_at || '') || Number(change.index || 0) });
      }
    }
    return targets.sort((left, right) => right.at - left.at)[0] || null;
  }

  reviewEntries(document) {
    const uri = document.uri.toString();
    const maxLine = Math.max(0, document.lineCount - 1);
    const entries = [];
    for (const proposal of this.proposals.filter((item) => item.uri === uri)) {
      for (const hunk of proposal.hunks) {
        entries.push({
          line: Math.min(Math.max(0, this.localHunkLine(proposal, hunk)), maxLine),
          label: hunk.label || '本地 Agent 改动',
          summary: `−${hunk.oldLines?.length || 0} +${hunk.newLines?.length || 0}`,
          status: hunk.status,
          canUndo: Boolean(hunk.decisionHistory?.length),
          accept: { command: 'egoagent.acceptHunk', arguments: [proposal.id, hunk.id] },
          reject: { command: 'egoagent.rejectHunk', arguments: [proposal.id, hunk.id] },
          undo: { command: 'egoagent.undoHunkDecision', arguments: [proposal.id, hunk.id] },
          diff: { command: 'egoagent.openProposalDiff', arguments: [proposal.id] },
        });
      }
    }
    for (const change of this.pendingBackendChangesForDocument(document)) {
      for (const hunk of change.hunks || []) {
        const baseLine = this.backendHunkLine(change, hunk);
        entries.push({
          line: Math.min(Math.max(0, baseLine), maxLine),
          label: hunk.tag || `${change.tool_name || 'DAG Agent'} 改动`,
          summary: `−${Number(hunk.old_count ?? hunk.old_lines?.length ?? 0)} +${Number(hunk.new_count ?? hunk.new_lines?.length ?? 0)}`,
          status: hunk.status,
          canUndo: Boolean(hunk.can_undo),
          accept: { command: 'egoagent.acceptBackendHunk', arguments: [change.id || change.index, hunk.id] },
          reject: { command: 'egoagent.rejectBackendHunk', arguments: [change.id || change.index, hunk.id] },
          diff: { command: 'egoagent.openBackendDiff', arguments: [change.id || change.index, hunk.id] },
        });
      }
    }
    return entries;
  }

  provideCodeLenses(document) {
    if (!vscode.workspace.getConfiguration('egoagent').get('review.inlineActions', true)) return [];
    if (!vscode.workspace.getConfiguration('editor', document.uri).get('codeLens', true)) return [];
    const activeInput = vscode.window.tabGroups?.activeTabGroup?.activeTab?.input;
    const inAgentDiff = activeInput?.original?.scheme === 'egoagent-preview'
      && activeInput?.modified?.toString() === document.uri.toString();
    if (inAgentDiff && !vscode.workspace.getConfiguration('diffEditor', document.uri).get('codeLens', true)) return [];
    const lenses = [];
    for (const entry of this.reviewEntries(document)) {
      const range = new vscode.Range(entry.line, 0, entry.line, 0);
      if (entry.status === 'pending') {
        lenses.push(
          new vscode.CodeLens(range, { title: `$(diff) Review Diff · ${entry.summary}`, command: entry.diff.command, arguments: entry.diff.arguments }),
          new vscode.CodeLens(range, { title: '✓ Accept', command: entry.accept.command, arguments: entry.accept.arguments }),
          new vscode.CodeLens(range, { title: '↶ Refuse', command: entry.reject.command, arguments: entry.reject.arguments }),
        );
      }
    }
    return lenses;
  }

  provideInlayHints(document) {
    if (!vscode.workspace.getConfiguration('egoagent').get('review.inlineActions', true)) return [];
    const activeInput = vscode.window.tabGroups?.activeTabGroup?.activeTab?.input;
    const inAgentDiff = activeInput?.original?.scheme === 'egoagent-preview'
      && activeInput?.modified?.toString() === document.uri.toString();
    const editorCodeLens = vscode.workspace.getConfiguration('editor', document.uri).get('codeLens', true);
    const diffCodeLens = vscode.workspace.getConfiguration('diffEditor', document.uri).get('codeLens', true);
    if (editorCodeLens && (!inAgentDiff || diffCodeLens)) return [];
    return this.reviewEntries(document)
      .filter((entry) => entry.status === 'pending')
      .map((entry) => {
        const line = Math.min(Math.max(0, entry.line), Math.max(0, document.lineCount - 1));
        const labels = [
          ['Review Diff', entry.diff],
          ['✓ Accept', entry.accept],
          ['↶ Refuse', entry.reject],
        ].map(([title, action]) => {
          const part = new vscode.InlayHintLabelPart(title);
          part.command = { title, command: action.command, arguments: action.arguments };
          return part;
        });
        const hint = new vscode.InlayHint(new vscode.Position(line, 0), labels, vscode.InlayHintKind.Type);
        hint.paddingLeft = true;
        hint.paddingRight = true;
        return hint;
      });
  }

  pendingLocations() {
    const locations = [];
    for (const proposal of this.proposals) {
      for (const hunk of proposal.hunks || []) {
        if (hunk.status === 'pending') locations.push({ uri: proposal.uri, line: this.localHunkLine(proposal, hunk) });
      }
    }
    const latestByPath = new Map();
    for (const change of [...this.activeBackendChanges()].sort((left, right) => reviewChangeRecency(right) - reviewChangeRecency(left))) {
      if (!(change.hunks || []).some((hunk) => hunk.status === 'pending')) continue;
      const path = normalizedFsPath(change.file_path);
      if (path && !latestByPath.has(path)) latestByPath.set(path, change);
    }
    for (const change of latestByPath.values()) {
      for (const hunk of change.hunks || []) {
        if (hunk.status !== 'pending') continue;
        locations.push({ uri: workspaceUriForPath(change.file_path).toString(), line: this.backendHunkLine(change, hunk) });
      }
    }
    return locations.sort((a, b) => a.uri.localeCompare(b.uri) || a.line - b.line);
  }

  async navigatePending(direction = 1) {
    const locations = this.pendingLocations();
    if (!locations.length) return vscode.window.showInformationMessage('当前没有待审查的 Agent 改动');
    const editor = vscode.window.activeTextEditor;
    const uri = editor?.document.uri.toString() || '';
    const line = editor?.selection.active.line ?? -1;
    let index;
    if (direction >= 0) {
      index = locations.findIndex((item) => item.uri > uri || (item.uri === uri && item.line > line));
      if (index < 0) index = 0;
    } else {
      index = locations.length - 1;
      for (let cursor = locations.length - 1; cursor >= 0; cursor -= 1) {
        const item = locations[cursor];
        if (item.uri < uri || (item.uri === uri && item.line < line)) { index = cursor; break; }
      }
    }
    const target = locations[index];
    const document = await vscode.workspace.openTextDocument(vscode.Uri.parse(target.uri));
    const targetEditor = await vscode.window.showTextDocument(document, { preview: false });
    const safeLine = Math.min(Math.max(0, target.line), Math.max(0, document.lineCount - 1));
    const position = new vscode.Position(safeLine, 0);
    targetEditor.selection = new vscode.Selection(position, position);
    targetEditor.revealRange(new vscode.Range(position, position), vscode.TextEditorRevealType.InCenterIfOutsideViewport);
    this.decorate(targetEditor);
    return target;
  }
}

const LocalCompletionProvider = require('./completion').createCompletionProvider(vscode, displayPath);

class NextEditPredictor {
  constructor(context, aiClient, reviewManager, metrics) {
    this.context = context;
    this.aiClient = aiClient;
    this.reviewManager = reviewManager;
    this.metrics = metrics;
    this.serial = 0;
    this.timer = undefined;
    this.prediction = undefined;
    this.applying = false;
    this.decoration = vscode.window.createTextEditorDecorationType({
      isWholeLine: true,
      backgroundColor: new vscode.ThemeColor('editor.wordHighlightBackground'),
      border: '1px dashed',
      borderColor: new vscode.ThemeColor('editorInfo.foreground'),
      after: { color: new vscode.ThemeColor('editorInfo.foreground'), fontStyle: 'italic' },
      overviewRulerColor: new vscode.ThemeColor('editorInfo.foreground'),
      overviewRulerLane: vscode.OverviewRulerLane.Right,
    });
    this.status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 91);
    this.status.command = 'egoagent.previewNextEdit';
    this.status.tooltip = '预览 EgoAgent 预测的下一处编辑';
    context.subscriptions.push(
      this.decoration,
      this.status,
      vscode.workspace.onDidChangeTextDocument((event) => this.schedule(event)),
      vscode.window.onDidChangeActiveTextEditor(() => this.render()),
    );
  }

  schedule(event) {
    if (this.applying) return;
    const config = vscode.workspace.getConfiguration('egoagent');
    if (!config.get('nextEdit.enabled', true) || !config.get('nextEdit.autoPredict', true)) return;
    const editor = vscode.window.activeTextEditor;
    if (!editor || editor.document.uri.toString() !== event.document.uri.toString()) return;
    const changed = (event.contentChanges || []).reduce((total, item) => total + Number(item.rangeLength || 0) + String(item.text || '').length, 0);
    if (changed < 2 || event.document.languageId === 'plaintext') return;
    clearTimeout(this.timer);
    const first = event.contentChanges[0];
    const lastEdit = {
      path: displayPath(event.document.uri),
      line: Number(first?.range?.start?.line || editor.selection.active.line) + 1,
      removed_characters: (event.contentChanges || []).reduce((total, item) => total + Number(item.rangeLength || 0), 0),
      inserted_text: (event.contentChanges || []).map((item) => String(item.text || '')).join('').slice(0, 1600),
    };
    const delay = Number(config.get('nextEdit.delayMs', 1800));
    this.timer = setTimeout(() => void this.predict(editor, lastEdit, true), Math.max(200, delay));
  }

  candidateFor(document, centerLine, maximumCharacters) {
    const lines = splitLines(document.getText());
    const radius = Math.max(20, Math.floor(maximumCharacters / 160));
    const start = Math.max(0, Math.min(lines.length, Number(centerLine || 0)) - radius);
    const end = Math.min(lines.length, start + radius * 2 + 1);
    return {
      path: displayPath(document.uri),
      language: document.languageId,
      excerpt_start_line: start + 1,
      excerpt: lines.slice(start, end).join('\n').slice(0, maximumCharacters),
    };
  }

  async predict(editor = vscode.window.activeTextEditor, lastEdit, silent = false) {
    if (!editor) return;
    clearTimeout(this.timer);
    const requestId = ++this.serial;
    const document = editor.document;
    const version = document.version;
    try {
      if (!(await this.aiClient.supports('edit'))) {
        if (!silent) vscode.window.showInformationMessage('当前没有可用于 Next Edit 的 edit 模型角色');
        return;
      }
      const candidates = [this.candidateFor(document, editor.selection.active.line, 16000)];
      for (const visible of vscode.window.visibleTextEditors || []) {
        if (visible.document.uri.toString() === document.uri.toString() || candidates.length >= 5) continue;
        candidates.push(this.candidateFor(visible.document, visible.selection.active.line, 6500));
      }
      const result = await this.aiClient.request('next-edit', {
        current_path: displayPath(document.uri),
        last_edit: lastEdit || {
          path: displayPath(document.uri),
          line: editor.selection.active.line + 1,
          inserted_text: document.lineAt(editor.selection.active.line).text.slice(0, 1000),
        },
        candidates,
      }, 45000);
      if (requestId !== this.serial || document.version !== version) {
        this.metrics.bump('nextEditsStaleDiscarded');
        return;
      }
      const minimumConfidence = Number(vscode.workspace.getConfiguration('egoagent').get('nextEdit.minimumConfidence', 0.35));
      if (Number(result.confidence || 0) < minimumConfidence) return this.dismiss();
      const target = (vscode.workspace.textDocuments || []).find((item) => sameDocumentPath(item.uri, result.path));
      const targetDocument = target || await vscode.workspace.openTextDocument(workspaceUriForPath(result.path));
      const start = Math.max(0, Math.min(targetDocument.lineCount, Number(result.start_line || 1) - 1));
      const end = Math.max(start, Math.min(targetDocument.lineCount, Number(result.end_line || result.start_line || 1)));
      const hunk = { start, end, newLines: splitLines(result.replacement || ''), label: result.label || 'Next edit' };
      const eol = targetDocument.eol === vscode.EndOfLine.CRLF ? '\r\n' : '\n';
      const proposed = applyLineHunks(targetDocument.getText(), [hunk], eol);
      if (proposed === targetDocument.getText()) return this.dismiss();
      this.prediction = {
        path: result.path,
        document: targetDocument,
        documentVersion: targetDocument.version,
        hunk,
        label: result.label || 'Suggested next edit',
        confidence: Number(result.confidence || 0),
        crossFile: !sameDocumentPath(document.uri, result.path),
      };
      this.metrics.bump('nextEditsOffered');
      this.render();
    } catch (error) {
      if (!silent) vscode.window.showWarningMessage(`Next Edit 预测失败：${error.message || error}`);
    }
  }

  render() {
    for (const editor of vscode.window.visibleTextEditors || []) editor.setDecorations(this.decoration, []);
    if (!this.prediction) {
      this.status.hide();
      return;
    }
    const visible = (vscode.window.visibleTextEditors || []).find((editor) => sameDocumentPath(editor.document.uri, this.prediction.path));
    if (visible) {
      const start = Math.max(0, Math.min(visible.document.lineCount - 1, this.prediction.hunk.start));
      const end = Math.max(start, Math.min(visible.document.lineCount - 1, Math.max(start, this.prediction.hunk.end - 1)));
      const range = new vscode.Range(start, 0, end, visible.document.lineAt(end).text.length);
      visible.setDecorations(this.decoration, [{
        range,
        hoverMessage: `${this.prediction.label} · ${Math.round(this.prediction.confidence * 100)}% · 点击状态栏预览`,
        renderOptions: { after: { contentText: `  ↪ Next Edit: ${this.prediction.label.slice(0, 70)}` } },
      }]);
    }
    this.status.text = `$(lightbulb-autofix) Next Edit ${Math.round(this.prediction.confidence * 100)}%`;
    this.status.show();
  }

  async preview() {
    const prediction = this.prediction;
    if (!prediction) return vscode.window.showInformationMessage('当前没有待预览的 Next Edit');
    if (prediction.document.version !== prediction.documentVersion) {
      this.dismiss();
      return vscode.window.showWarningMessage('目标文件已变化，过期的 Next Edit 已丢弃');
    }
    const document = prediction.document;
    const eol = document.eol === vscode.EndOfLine.CRLF ? '\r\n' : '\n';
    const proposed = applyLineHunks(document.getText(), [prediction.hunk], eol);
    await this.reviewManager.showDraftPreview(document, proposed, `EgoAgent Next Edit · ${prediction.label}`);
    const decision = await vscode.window.showQuickPick([
      { label: '$(check) 应用并进入逐段审阅', description: prediction.crossFile ? '跨文件修改只会在确认后写入' : '写入后仍可 Accept / Refuse；Ctrl+Z 撤销审阅决定', value: 'apply' },
      { label: '$(close) 忽略建议', description: '保持所有文件不变', value: 'dismiss' },
    ], { title: 'Next Edit 预览', placeHolder: `${prediction.path} · ${Math.round(prediction.confidence * 100)}%` });
    if (decision?.value === 'apply') {
      this.applying = true;
      try {
        await this.reviewManager.propose(document, `Next Edit · ${prediction.label}`, [prediction.hunk]);
        this.metrics.bump('nextEditsAccepted');
      } finally {
        this.applying = false;
      }
      this.dismiss(false);
    } else if (decision?.value === 'dismiss') {
      this.metrics.bump('nextEditsRejected');
      this.dismiss(false);
    }
  }

  dismiss(invalidate = true) {
    if (invalidate) this.serial += 1;
    clearTimeout(this.timer);
    this.prediction = undefined;
    this.render();
  }
}

class LocalReviewer {
  constructor(context, metrics) {
    this.metrics = metrics;
    this.collection = vscode.languages.createDiagnosticCollection('egoagent-local-review');
    context.subscriptions.push(this.collection);
  }

  run(document) {
    const diagnostics = [];
    const issues = [];
    const rules = [
      { regex: /\b(eval|exec)\s*\(/, severity: vscode.DiagnosticSeverity.Warning, label: '动态执行代码会扩大注入风险', code: 'security.dynamic-exec' },
      { regex: /\b(api[_-]?key|password|secret|token)\s*[:=]\s*["'][^"']{8,}["']/i, severity: vscode.DiagnosticSeverity.Error, label: '疑似硬编码凭据，请改用环境变量或密钥存储', code: 'security.hardcoded-secret' },
      { regex: /^\s*except\s*:/, severity: vscode.DiagnosticSeverity.Warning, label: '裸 except 会吞掉系统退出等异常', code: 'quality.bare-except' },
      { regex: /\bconsole\.log\s*\(/, severity: vscode.DiagnosticSeverity.Information, label: '发布前请确认调试日志是否需要保留', code: 'quality.console-log' },
      { regex: /\b(TODO|FIXME)\b/i, severity: vscode.DiagnosticSeverity.Hint, label: '存在待完成事项', code: 'quality.todo' },
    ];
    for (let line = 0; line < document.lineCount; line += 1) {
      const text = document.lineAt(line).text;
      for (const rule of rules) {
        const match = rule.regex.exec(text);
        rule.regex.lastIndex = 0;
        if (!match) continue;
        const range = new vscode.Range(line, match.index, line, match.index + Math.max(1, match[0].length));
        const diagnostic = new vscode.Diagnostic(range, `EgoAgent：${rule.label}`, rule.severity);
        diagnostic.source = 'EgoAgent Local Review';
        diagnostic.code = rule.code;
        diagnostics.push(diagnostic);
        issues.push({ line: line + 1, severity: rule.severity, message: rule.label, code: rule.code });
      }
    }
    this.collection.set(document.uri, diagnostics);
    this.metrics.bump('reviewsRun');
    return issues;
  }

  async runAI(document, aiClient) {
    const result = await aiClient.request('review', {
      code: document.getText(),
      language: document.languageId,
      path: displayPath(document.uri),
    });
    const severityMap = {
      error: vscode.DiagnosticSeverity.Error,
      warning: vscode.DiagnosticSeverity.Warning,
      info: vscode.DiagnosticSeverity.Information,
      hint: vscode.DiagnosticSeverity.Hint,
    };
    const diagnostics = [];
    const issues = [];
    for (const issue of result.issues || []) {
      const startLine = Math.max(0, Math.min(document.lineCount - 1, Number(issue.line || 1) - 1));
      const endLine = Math.max(startLine, Math.min(document.lineCount - 1, Number(issue.endLine || issue.line || 1) - 1));
      const range = new vscode.Range(startLine, 0, endLine, document.lineAt(endLine).text.length);
      const severityName = String(issue.severity || 'warning').toLowerCase();
      const message = String(issue.message || '').trim();
      if (!message) continue;
      const diagnostic = new vscode.Diagnostic(range, `EgoAgent AI：${message}`, severityMap[severityName] ?? vscode.DiagnosticSeverity.Warning);
      diagnostic.source = `EgoAgent AI · ${result.model || 'model'}`;
      diagnostic.code = issue.code || 'ai.review';
      diagnostics.push(diagnostic);
      issues.push({
        line: startLine + 1,
        endLine: endLine + 1,
        severity: diagnostic.severity,
        message,
        suggestion: String(issue.suggestion || ''),
        code: diagnostic.code,
      });
    }
    this.collection.set(document.uri, diagnostics);
    this.metrics.bump('reviewsRun');
    return issues;
  }
}

function commentPrefix(language) {
  if (['python', 'ruby', 'shellscript', 'yaml'].includes(language)) return '#';
  if (['markdown'].includes(language)) return '<!--';
  return '//';
}

function commentLine(language, indent, text) {
  const prefix = commentPrefix(language);
  return prefix === '<!--' ? `${indent}<!-- ${text} -->` : `${indent}${prefix} ${text}`;
}

function buildMockHunks(document, mode) {
  const lines = splitLines(document.getText());
  const language = document.languageId;
  const candidates = [];
  const functionPattern = language === 'python'
    ? /^(\s*)(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(/
    : /^(\s*)(?:(?:export|public|private|protected|static|async)\s+)*(?:function\s+)?([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*(?:[:\w<>,\[\]| ]+)?\s*(?:=>\s*)?\{/;
  lines.forEach((line, index) => {
    const match = functionPattern.exec(line);
    if (match) candidates.push({ index, indent: match[1] || '', name: match[2] || 'function' });
  });

  if (mode === 'observability') {
    const targets = candidates.slice(0, 3);
    return targets.map((target) => {
      const bodyIndent = target.indent + (language === 'python' ? '    ' : '  ');
      const statement = language === 'python'
        ? `${bodyIndent}print("[EgoAgent] enter ${target.name}")`
        : `${bodyIndent}console.debug('[EgoAgent] enter ${target.name}');`;
      return { start: target.index + 1, end: target.index + 1, newLines: [statement], label: `为 ${target.name} 增加入口日志` };
    });
  }

  if (mode === 'guards') {
    const targets = candidates.slice(0, 3);
    return targets.map((target) => {
      const bodyIndent = target.indent + (language === 'python' ? '    ' : '  ');
      const linesToInsert = language === 'python'
        ? [`${bodyIndent}if locals().get("value") is None:`, `${bodyIndent}    raise ValueError("value is required")`]
        : [`${bodyIndent}if (typeof value === 'undefined') {`, `${bodyIndent}  throw new TypeError('value is required');`, `${bodyIndent}}`];
      return { start: target.index + 1, end: target.index + 1, newLines: linesToInsert, label: `为 ${target.name} 增加输入保护` };
    });
  }

  const hunks = [];
  const firstContent = lines.findIndex((line) => line.trim());
  const top = firstContent < 0 ? 0 : firstContent;
  hunks.push({
    start: top,
    end: top,
    newLines: [commentLine(language, '', `Module responsibility: ${displayPath(document.uri)}`)],
    label: '补充模块职责说明',
  });
  for (const target of candidates.slice(0, 2)) {
    hunks.push({
      start: target.index,
      end: target.index,
      newLines: [commentLine(language, target.indent, `${target.name}: keep inputs, side effects, and return contract explicit.`)],
      label: `补充 ${target.name} 的维护说明`,
    });
  }
  if (hunks.length === 1 && lines.length > 4) {
    const middle = Math.floor(lines.length / 2);
    hunks.push({ start: middle, end: middle, newLines: [commentLine(language, '', 'Local review boundary.')], label: '标记审查边界' });
  }
  return hunks.slice(0, 3);
}

function buildInlineHunks(document, selection, instruction) {
  const lines = splitLines(document.getText());
  const start = selection.isEmpty ? selection.active.line : selection.start.line;
  const end = selection.isEmpty ? start + 1 : Math.min(lines.length, selection.end.line + (selection.end.character ? 1 : 0));
  const oldLines = lines.slice(start, Math.max(start + 1, end));
  const baseIndent = /^\s*/.exec(oldLines[0] || '')?.[0] || '';
  const language = document.languageId;
  const normalized = instruction.toLowerCase();
  if (/try|catch|错误|异常|错误处理/.test(normalized)) {
    if (language === 'python') {
      return [{
        start, end: Math.max(start + 1, end), label: '增加明确的异常上下文',
        newLines: [`${baseIndent}try:`, ...oldLines.map((line) => `${baseIndent}    ${line.slice(baseIndent.length)}`), `${baseIndent}except Exception as error:`, `${baseIndent}    raise RuntimeError("operation failed") from error`],
      }];
    }
    return [{
      start, end: Math.max(start + 1, end), label: '增加明确的错误传播',
      newLines: [`${baseIndent}try {`, ...oldLines.map((line) => `${baseIndent}  ${line.slice(baseIndent.length)}`), `${baseIndent}} catch (error) {`, `${baseIndent}  throw new Error('operation failed', { cause: error });`, `${baseIndent}}`],
    }];
  }
  if (/简化|simplify|format|格式|清理/.test(normalized)) {
    const cleaned = oldLines.map((line) => line.replace(/\s+$/, '')).filter((line, index, all) => !(line === '' && all[index - 1] === ''));
    return [{ start, end: Math.max(start + 1, end), newLines: cleaned, label: '清理格式与重复空行' }];
  }
  return [{
    start,
    end: start,
    newLines: [commentLine(language, baseIndent, instruction)],
    label: `本地指令：${instruction}`,
  }];
}

async function captureEditorContext() {
  const editor = vscode.window.activeTextEditor;
  const defaultFolder = vscode.workspace.workspaceFolders?.[0];
  if (!editor) return {
    available: false,
    workspace: defaultFolder?.uri.toString() || '',
    workspacePath: fsPathForBackend(defaultFolder?.uri),
  };
  const document = editor.document;
  let symbols = [];
  try {
    const documentSymbols = await vscode.commands.executeCommand('vscode.executeDocumentSymbolProvider', document.uri) || [];
    symbols = documentSymbols.slice(0, 30).map((symbol) => ({ name: symbol.name, kind: vscode.SymbolKind[symbol.kind] || symbol.kind, line: (symbol.range?.start?.line || 0) + 1 }));
  } catch {}
  if (!symbols.length) symbols = extractLocalSymbols(document).slice(0, 30);
  const position = editor.selection.active;
  const [definitionResult, referenceResult] = await Promise.allSettled([
    vscode.commands.executeCommand('vscode.executeDefinitionProvider', document.uri, position),
    vscode.commands.executeCommand('vscode.executeReferenceProvider', document.uri, position),
  ]);
  const locations = (result) => (result.status === 'fulfilled' && Array.isArray(result.value) ? result.value : [])
    .slice(0, 30)
    .map((location) => {
      const uri = location.uri || location.targetUri;
      const range = location.range || location.targetSelectionRange || location.targetRange;
      return {
        path: displayPath(uri),
        absolutePath: fsPathForBackend(uri),
        start_line: Number(range?.start?.line || 0) + 1,
        end_line: Number(range?.end?.line || range?.start?.line || 0) + 1,
      };
    });
  const diagnostics = (vscode.languages.getDiagnostics(document.uri) || []).slice(0, 50).map((diagnostic) => ({
    path: displayPath(document.uri),
    start_line: diagnostic.range.start.line + 1,
    end_line: diagnostic.range.end.line + 1,
    content: diagnostic.message,
    metadata: { severity: vscode.DiagnosticSeverity[diagnostic.severity], source: diagnostic.source, code: diagnostic.code },
  }));
  const excerptStart = Math.max(0, position.line - 80);
  const excerptEnd = Math.min(document.lineCount, position.line + 81);
  const excerptRange = new vscode.Range(
    new vscode.Position(excerptStart, 0),
    excerptEnd >= document.lineCount ? document.positionAt(document.getText().length) : new vscode.Position(excerptEnd, 0),
  );
  const fileExcerpt = document.getText(excerptRange).slice(0, 16000);
  const imports = document.getText().split(/\r?\n/)
    .filter((line) => /^\s*(?:import\b|from\s+\S+\s+import\b|.*\bfrom\s+['\"]|.*require\s*\()/i.test(line))
    .slice(0, 60);
  const rawSelectionText = editor.selection.isEmpty ? '' : document.getText(editor.selection);
  const selectionText = rawSelectionText.slice(0, 50000);
  const selectionRange = selectionLineRange(editor.selection);
  return {
    available: true,
    uri: document.uri.toString(),
    path: displayPath(document.uri),
    absolutePath: fsPathForBackend(document.uri),
    language: document.languageId,
    line: editor.selection.active.line + 1,
    selectionText,
    selectionStartLine: selectionRange.startLine,
    selectionEndLine: selectionRange.endLine,
    selectionLines: selectionRange.lineCount,
    selectionTruncated: rawSelectionText.length > selectionText.length,
    symbols,
    definitions: locations(definitionResult),
    references: locations(referenceResult),
    diagnostics,
    imports,
    fileExcerpt,
    excerptStartLine: excerptStart + 1,
    excerptEndLine: excerptEnd,
    documentVersion: document.version,
    workspace: vscode.workspace.getWorkspaceFolder(document.uri)?.uri.toString() || defaultFolder?.uri.toString() || '',
    workspacePath: fsPathForBackend(vscode.workspace.getWorkspaceFolder(document.uri)?.uri || defaultFolder?.uri),
  };
}

async function sendIdeContextToEvaluation(primaryUri, selectedUris, selectionOnly = false) {
  let uris = Array.isArray(selectedUris) && selectedUris.length ? selectedUris : primaryUri ? [primaryUri] : [];
  if (!uris.length && vscode.window.activeTextEditor) uris = [vscode.window.activeTextEditor.document.uri];
  uris = uris.filter(Boolean).slice(0, 20);
  if (!uris.length) return vscode.window.showWarningMessage('请先在编辑器或 Explorer 中选择文件');
  const activeEditor = vscode.window.activeTextEditor;
  const items = [];
  for (const uri of uris) {
    const document = activeEditor?.document?.uri?.toString() === uri.toString()
      ? activeEditor.document
      : await vscode.workspace.openTextDocument(uri);
    const useSelection = selectionOnly && activeEditor?.document?.uri?.toString() === document.uri.toString() && !activeEditor.selection.isEmpty;
    const content = (useSelection ? document.getText(activeEditor.selection) : document.getText()).slice(0, 60000);
    items.push({
      kind: useSelection ? 'selection' : 'file',
      path: fsPathForBackend(document.uri),
      relativePath: displayPath(document.uri),
      language: document.languageId,
      startLine: useSelection ? activeEditor.selection.start.line + 1 : 1,
      endLine: useSelection ? activeEditor.selection.end.line + 1 : document.lineCount,
      content,
    });
  }
  pendingWorkbenchHandoff = items;
  openWorkbench('tasks');
  vscode.window.showInformationMessage(`已将 ${items.length} 个 IDE ${items.some((item) => item.kind === 'selection') ? '选区/文件' : '文件'}附加到 Agent Evaluation`);
}

class DagChatViewProvider {
  constructor(context, reviewManager, completionProvider, reviewer, metrics, aiClient) {
    this.context = context;
    this.extensionUri = context.extensionUri;
    this.reviewManager = reviewManager;
    this.completionProvider = completionProvider;
    this.reviewer = reviewer;
    this.metrics = metrics;
    this.aiClient = aiClient;
    this.view = undefined;
    this.reviewIssues = [];
    this.aiStatus = { configured: false, fallback: 'deterministic-local' };
    this.backendRefreshPromise = undefined;
    this.copiedContext = undefined;
  }

  resolveWebviewView(view) {
    this.view = view;
    const webview = view.webview;
    webview.options = { enableScripts: true, localResourceRoots: [vscode.Uri.joinPath(this.extensionUri, 'media')] };
    webview.html = this.getHtml(webview);
    webview.onDidReceiveMessage(async (message) => {
      try {
        if (message.type === 'webviewReady') {
          this.postSnapshot();
          this.sendEditorContext();
          await Promise.all([this.refreshAIStatus(), this.refreshBackendReviewState(), refreshWorkbenchRuntimeStatus()]);
          return;
        }
        if (message.type === 'openWorkbench' || message.type === 'openStudio') return openWorkbench(message.tab || 'home', { linkRunId: message.linkRunId });
        if (message.type === 'openRemoteWorkspace') return remoteWorkspaces.openRemoteWorkspaces();
        if (message.type === 'notifyError') return vscode.window.showErrorMessage(message.message || 'EgoAgent request failed');
        if (message.type === 'requestEditorContext') return this.sendEditorContext(message.requestId);
        if (message.type === 'attachTerminalContext') return vscode.commands.executeCommand('egoagent.attachTerminalSelectionToChat');
        if (message.type === 'resolveContextPaste') return this.resolveContextPaste(message);
        if (message.type === 'resolveContextDrop') return this.resolveContextDrop(message);
        if (message.type === 'openContextLocation') return this.openContextLocation(message.context);
        if (message.type === 'openBackendDiff') return this.reviewManager.openBackendDiff(message.id, message.hunkId);
        if (message.type === 'openChangeFile') {
          if (message.transactionId) this.reviewManager.selectBackendTransaction(message.transactionId);
          return this.openContextLocation({
            absolutePath: message.path,
            startLine: Number(message.line || 1),
            endLine: Number(message.line || 1),
          });
        }
        if (message.type === 'mockEdit') return vscode.commands.executeCommand('egoagent.mockAgentEdit', message.mode || 'maintainability');
        if (message.type === 'inlineEdit') return vscode.commands.executeCommand('egoagent.inlineEdit', message.instruction);
        if (message.type === 'localReview') return vscode.commands.executeCommand('egoagent.localReview');
        if (message.type === 'codeMap') return vscode.commands.executeCommand('egoagent.codeMap');
        if (message.type === 'preview') return vscode.commands.executeCommand('egoagent.preview');
        if (message.type === 'commitMessage') return vscode.commands.executeCommand('egoagent.generateCommitMessage');
        if (message.type === 'terminalCommand') return vscode.commands.executeCommand('egoagent.runTerminalCommand', message.command);
        if (message.type === 'backendChangesSnapshot') {
          return this.reviewManager.syncBackendChanges(message.changes, message.activeTransactionId);
        }
        if (message.type === 'backendChangeAction') return this.applyBackendChange(message);
        if (message.type === 'changeAction') {
          if (message.action === 'accept') await this.reviewManager.updateHunk(message.proposalId, message.hunkId, 'accepted');
          if (message.action === 'reject') await this.reviewManager.updateHunk(message.proposalId, message.hunkId, 'rejected');
          if (message.action === 'undo') await this.reviewManager.undoHunk(message.proposalId, message.hunkId);
          if (message.action === 'acceptAll') await this.reviewManager.updateAll(message.proposalId, 'accepted');
          if (message.action === 'rejectAll') await this.reviewManager.updateAll(message.proposalId, 'rejected');
          if (message.action === 'diff') await this.reviewManager.openDiff(message.proposalId);
        }
      } catch (error) {
        vscode.window.showErrorMessage(`EgoAgent：${error.message || error}`);
      }
    });
    this.postSnapshot();
    this.sendEditorContext();
    this.refreshAIStatus();
    this.refreshBackendReviewState();
  }

  refresh() {
    if (this.view) {
      // Force the Webview document and script to reload. Void can restore an
      // old iframe from workspace storage even after the extension itself was
      // upgraded, so a state-only postMessage is not sufficient here.
      this.view.webview.html = this.getHtml(this.view.webview);
    }
    this.view?.webview.postMessage({ type: 'refresh' });
    this.postSnapshot();
    this.sendEditorContext();
    this.refreshAIStatus();
    this.refreshBackendReviewState();
  }

  postSnapshot() {
    this.view?.webview.postMessage({
      type: 'localState',
      proposals: this.reviewManager.serialize(),
      metrics: this.metrics.snapshot(),
      completionEnabled: this.completionProvider.enabled,
      reviewIssues: this.reviewIssues,
      aiStatus: this.aiStatus,
      workbenchStatus: workbenchStatusSnapshot(),
    });
  }

  async refreshAIStatus() {
    this.aiStatus = await this.aiClient.status(true);
    this.postSnapshot();
  }

  async refreshBackendReviewState() {
    if (this.backendRefreshPromise) return this.backendRefreshPromise;
    this.backendRefreshPromise = (async () => {
      try {
        const workspace = fsPathForBackend(vscode.workspace.workspaceFolders?.[0]?.uri);
        const query = workspace ? `?workspace=${encodeURIComponent(workspace)}` : '';
        const [response, executionResponse] = await Promise.all([
          fetch(`${this.aiClient.backendUrl}/api/session/changes${query}`),
          workspace
            ? fetch(`${this.aiClient.backendUrl}/api/execution/state?workspace=${encodeURIComponent(workspace)}`).catch(() => undefined)
            : Promise.resolve(undefined),
        ]);
        if (!response.ok) return;
        const changes = await response.json();
        let activeTransactionId;
        if (executionResponse?.ok) {
          const execution = await executionResponse.json();
          if (execution.running || execution.waiting_for_input) {
            activeTransactionId = String(
              execution.change_transaction_id
              || (execution.pipeline_run_id ? `run-${execution.pipeline_run_id}` : '')
              || latestPendingReviewTransaction(changes)
            );
          }
        }
        this.reviewManager.syncBackendChanges(changes, activeTransactionId);
        this.view?.webview.postMessage({ type: 'trackedChanges', changes });
      } catch (error) {
        this.aiStatus = { ...this.aiStatus, reviewError: String(error?.message || error) };
        this.postSnapshot();
      }
    })();
    try {
      return await this.backendRefreshPromise;
    } finally {
      this.backendRefreshPromise = undefined;
    }
  }

  async applyBackendChange(message) {
    const selector = message.id ?? message.index;
    const hunkId = message.hunkId === undefined ? undefined : String(message.hunkId);
    const action = String(message.action || '');
    const change = this.reviewManager.getBackendChange(selector);
    if (!change) throw new Error('找不到对应的 Agent 改动，请刷新后重试');
    let confirmDelete = message.confirmDelete === true;
    if ((action === 'reject' || action === 'rejectAll') && change.is_new_file && !confirmDelete) {
      const choice = await vscode.window.showWarningMessage(
        '这个改动创建了一个新文件。拒绝完整写入会删除该文件，是否继续？',
        { modal: true, detail: change.file_path },
        '删除文件',
      );
      if (choice !== '删除文件') return false;
      confirmDelete = true;
    }
    const endpoint = action === 'undo' ? 'undo' : action.startsWith('accept') ? 'accept' : 'reject';
    const response = await fetch(`${this.aiClient.backendUrl}/api/session/changes/${endpoint}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        id: change.id,
        index: change.index,
        hunk_id: action.endsWith('All') ? undefined : hunkId,
        reason: endpoint === 'reject' ? 'Rejected in Void editor review' : undefined,
        confirm_delete: endpoint === 'reject' && change.is_new_file && confirmDelete,
      }),
    });
    const text = await response.text();
    let data = {};
    try { data = text ? JSON.parse(text) : {}; } catch { data = { error: text }; }
    if (!response.ok) throw new Error(data.error || `改动操作失败 (${response.status})`);
    await this.refreshBackendReviewState();
    await this.reviewManager.reconcileBackendReview(change.id || change.index, {
      reopenPending: endpoint === 'undo',
      hunkId,
    });
    this.view?.webview.postMessage({ type: 'refreshTrackedChanges' });
    return true;
  }

  async applyAllInActiveFile(action) {
    const editor = vscode.window.activeTextEditor;
    if (!editor) return vscode.window.showWarningMessage('请先打开一个有 Agent 改动的文件');
    const uri = editor.document.uri.toString().toLowerCase();
    let changed = 0;
    for (const proposal of this.reviewManager.proposals.filter((item) => item.uri.toLowerCase() === uri)) {
      changed += Number(await this.reviewManager.updateAll(proposal.id, action === 'accept' ? 'accepted' : 'rejected'));
    }
    const backend = this.reviewManager.backendChanges.filter((change) => {
      try { return sameDocumentPath(editor.document.uri, change.file_path); } catch { return false; }
    });
    for (const change of backend) {
      const pending = (change.hunks || []).some((hunk) => hunk.status === 'pending');
      if (!pending) continue;
      changed += Number(await this.applyBackendChange({ action: action === 'accept' ? 'acceptAll' : 'rejectAll', id: change.id || change.index }));
    }
    if (!changed) vscode.window.showInformationMessage('当前文件没有可处理的待审 Agent 改动');
    return Boolean(changed);
  }

  async undoLatestReviewDecision() {
    const editor = vscode.window.activeTextEditor;
    if (!editor) return false;
    await this.refreshBackendReviewState();
    const target = this.reviewManager.latestUndoTarget(editor.document);
    if (!target) return false;
    const changed = target.source === 'local'
      ? await this.reviewManager.undoHunk(target.proposalId, target.hunkId)
      : await this.applyBackendChange({ action: 'undo', id: target.changeId, hunkId: target.hunkId });
    if (changed) {
      vscode.window.showInformationMessage('已撤销最近一次 Accept / Refuse，改动块重新进入待审状态');
      this.reviewManager.decorate(vscode.window.activeTextEditor);
    }
    return Boolean(changed);
  }

  async applyAllChanges(action) {
    const localTargets = this.reviewManager.proposals.filter((proposal) => proposal.hunks.some((hunk) => hunk.status === 'pending'));
    const backendTargets = this.reviewManager.backendChanges.filter((change) => (change.hunks || []).some((hunk) => hunk.status === 'pending'));
    if (!localTargets.length && !backendTargets.length) return vscode.window.showInformationMessage('当前没有待审 Agent 改动');
    const newFiles = backendTargets.filter((change) => change.is_new_file);
    let confirmDelete = false;
    if (action === 'reject' && newFiles.length) {
      const choice = await vscode.window.showWarningMessage(
        `全部拒绝会删除 ${newFiles.length} 个 Agent 新建文件。是否继续？`,
        { modal: true, detail: newFiles.map((change) => change.file_path).join('\n') },
        '全部拒绝并删除',
      );
      if (choice !== '全部拒绝并删除') return false;
      confirmDelete = true;
    }
    for (const proposal of localTargets) await this.reviewManager.updateAll(proposal.id, action === 'accept' ? 'accepted' : 'rejected');
    for (const change of backendTargets) {
      await this.applyBackendChange({
        action: action === 'accept' ? 'acceptAll' : 'rejectAll',
        id: change.id || change.index,
        confirmDelete: confirmDelete && change.is_new_file,
      });
    }
    return true;
  }

  async sendEditorContext(requestId) {
    this.view?.webview.postMessage({
      type: 'editorContext',
      requestId,
      context: await captureEditorContext(),
    });
  }

  rememberCopiedContext(context) {
    if (!context?.content) return;
    this.copiedContext = { ...context, copiedAt: Date.now() };
  }

  async resolveContextPaste(message) {
    const requestId = message.requestId;
    const clipboardText = String(message.text || '');
    if (!clipboardText) {
      this.view?.webview.postMessage({ type: 'contextPasteResolved', requestId, context: null });
      return;
    }
    const context = await this.contextForClipboardText(clipboardText);
    this.view?.webview.postMessage({ type: 'contextPasteResolved', requestId, context });
  }

  async contextForClipboardText(clipboardText) {
    const comparable = normalizedClipboardText(clipboardText);
    let context;
    const remembered = this.copiedContext;
    if (
      remembered
      && Date.now() - Number(remembered.copiedAt || 0) < 10 * 60 * 1000
      && normalizedClipboardText(remembered.content) === comparable
    ) {
      context = { ...remembered };
    } else {
      const editor = await captureEditorContext();
      if (editor.selectionText && normalizedClipboardText(editor.selectionText) === comparable) {
        context = {
          kind: 'selection',
          title: `${editor.path}:${editor.selectionStartLine}-${editor.selectionEndLine}`,
          path: editor.path,
          absolutePath: editor.absolutePath,
          startLine: editor.selectionStartLine,
          endLine: editor.selectionEndLine,
          language: editor.language,
          content: clipboardText.slice(0, 50000),
          truncated: clipboardText.length > 50000,
        };
      }
    }
    if (!context) {
      const lineCount = clipboardText.replaceAll('\r\n', '\n').split('\n').length;
      context = {
        kind: 'clipboard',
        title: `Clipboard · ${lineCount} ${lineCount === 1 ? 'line' : 'lines'}`,
        language: 'text',
        content: clipboardText.slice(0, 50000),
        truncated: clipboardText.length > 50000,
      };
    }
    return context;
  }

  droppedResourceStrings(transfer) {
    const found = new Set();
    const isResource = (value) => /^(?:file|vscode-remote):\//i.test(value)
      || /^[A-Za-z]:[\\/]/.test(value) || /^\/(?!\/)/.test(value) || /^\\\\[^\\]/.test(value);
    const visit = (value) => {
      if (Array.isArray(value)) { value.forEach(visit); return; }
      if (value && typeof value === 'object') {
        // CodeEditors can serialize a URI as components instead of a string.
        // Keep its authority: a file from another remote must not be silently
        // interpreted as a same-named file in the current workspace.
        if (['file', 'vscode-remote'].includes(value.scheme) && typeof value.path === 'string') {
          try { found.add(vscode.Uri.from(value).toString()); } catch {}
          return;
        }
        Object.values(value).forEach(visit); return;
      }
      if (typeof value !== 'string') return;
      const text = value.trim();
      if (!text) return;
      // Parse JSON first: otherwise a serialized Linux path could accidentally
      // be treated as an entire resource including its enclosing quotes.
      try { visit(JSON.parse(text)); return; } catch {}
      if (!/[\r\n]/.test(text) && isResource(text)) found.add(text);
      for (const line of text.split(/\r?\n/)) {
        const candidate = line.trim().replace(/^<|>$/g, '');
        if (isResource(candidate)) found.add(candidate);
      }
    };
    Object.values(transfer || {}).forEach(visit);
    return [...found];
  }

  async contextForDroppedResource(value) {
    let uri;
    try {
      if (/^(?:file|vscode-remote):\//i.test(value)) {
        uri = vscode.Uri.parse(value);
        // Explorer's CodeFiles uses filesystem paths/file: URIs even when the
        // editor lives in WSL/SSH. Rebind only these local filesystem references
        // to this workspace; preserve explicit remote authorities for validation.
        if (uri.scheme === 'file' && !uri.authority) uri = workspaceUriForPath(uri.fsPath);
      } else uri = workspaceUriForPath(value);
    } catch { return null; }
    if (!vscode.workspace.getWorkspaceFolder(uri)) return null;
    try {
      const stat = await vscode.workspace.fs.stat(uri);
      if (stat.type & vscode.FileType.Directory) {
        const relativePath = displayPath(uri).replace(/[\\/]?$/, '/');
        const lines = [];
        let truncated = false;
        const maxEntries = 400;
        const maxDepth = 3;
        const visitDirectory = async (directory, depth) => {
          if (lines.length >= maxEntries) { truncated = true; return; }
          let entries;
          try { entries = await vscode.workspace.fs.readDirectory(directory); } catch { return; }
          entries.sort((left, right) => {
            const leftDir = Boolean(left[1] & vscode.FileType.Directory);
            const rightDir = Boolean(right[1] & vscode.FileType.Directory);
            return leftDir === rightDir ? left[0].localeCompare(right[0]) : leftDir ? -1 : 1;
          });
          for (const [name, type] of entries) {
            if (lines.length >= maxEntries) { truncated = true; break; }
            const child = vscode.Uri.joinPath(directory, name);
            const childPath = displayPath(child).replace(/\\/g, '/');
            const directoryEntry = Boolean(type & vscode.FileType.Directory);
            lines.push(`${directoryEntry ? '[dir]' : '[file]'} ${childPath}${directoryEntry ? '/' : ''}`);
            if (directoryEntry && !(type & vscode.FileType.SymbolicLink)) {
              if (depth < maxDepth) await visitDirectory(child, depth + 1);
              else truncated = true;
            }
          }
        };
        await visitDirectory(uri, 1);
        const listing = [`Directory attached from current Workspace: ${relativePath}`, ...lines].join('\n');
        return {
          kind: 'folder',
          title: relativePath,
          path: relativePath,
          absolutePath: fsPathForBackend(uri),
          language: 'directory',
          content: listing.slice(0, 50000),
          truncated: truncated || listing.length > 50000,
        };
      }
      const document = await vscode.workspace.openTextDocument(uri);
      const content = document.getText();
      const relativePath = displayPath(uri);
      return {
        kind: 'file',
        title: relativePath,
        path: relativePath,
        absolutePath: fsPathForBackend(uri),
        startLine: 1,
        endLine: Math.max(1, document.lineCount),
        language: document.languageId || 'text',
        content: content.slice(0, 50000),
        truncated: content.length > 50000,
      };
    } catch { return null; }
  }

  async resolveContextDrop(message) {
    const requestId = message.requestId;
    const transfer = message.transfer && typeof message.transfer === 'object' ? message.transfer : {};
    const resources = this.droppedResourceStrings(transfer);
    const contexts = (await Promise.all(resources.slice(0, 8).map((value) => this.contextForDroppedResource(value)))).filter(Boolean);
    if (!contexts.length) {
      const text = String(transfer['text/plain'] || '');
      if (text) {
        const context = await this.contextForClipboardText(text);
        if (context?.kind === 'selection') contexts.push(context);
      }
    }
    this.view?.webview.postMessage({
      type: 'contextDropResolved',
      requestId,
      contexts,
      error: contexts.length ? '' : '只能拖入当前 Workspace 内的文件、文件夹或当前编辑器选区',
    });
  }

  async attachResourcesToChat(uri, selectedUris, selectionOnly = false) {
    const requested = Array.isArray(selectedUris) && selectedUris.length
      ? selectedUris
      : uri ? [uri] : vscode.window.activeTextEditor?.document?.uri ? [vscode.window.activeTextEditor.document.uri] : [];
    const contexts = [];
    if (selectionOnly) {
      const editor = vscode.window.activeTextEditor;
      if (editor && !editor.selection.isEmpty) {
        const range = selectionLineRange(editor.selection);
        contexts.push({
          kind: 'selection',
          title: `${displayPath(editor.document.uri)}:${range.startLine}-${range.endLine}`,
          path: displayPath(editor.document.uri),
          absolutePath: fsPathForBackend(editor.document.uri),
          startLine: range.startLine,
          endLine: range.endLine,
          language: editor.document.languageId,
          content: editor.document.getText(editor.selection).slice(0, 50000),
          truncated: editor.document.getText(editor.selection).length > 50000,
        });
      }
    } else {
      for (const resource of requested.slice(0, 8)) {
        const context = await this.contextForDroppedResource(resource.toString());
        if (context) contexts.push(context);
      }
    }
    if (!contexts.length) {
      return vscode.window.showWarningMessage(selectionOnly ? '请先在编辑器中选中代码' : '只能附加当前 Workspace 内的文件或文件夹');
    }
    this.view?.show?.(true);
    try { await vscode.commands.executeCommand('egoagent.dagChat.focus'); } catch {}
    this.view?.webview.postMessage({ type: 'externalContextsAttached', contexts });
    vscode.window.showInformationMessage(`已把 ${contexts.length} 个${selectionOnly ? '代码选区' : '文件/文件夹'}插入 EgoAgent Chat`);
    return contexts;
  }

  async openContextLocation(context) {
    if (!context?.absolutePath) return;
    const uri = workspaceUriForPath(context.absolutePath);
    const stat = await vscode.workspace.fs.stat(uri);
    if (stat.type & vscode.FileType.Directory) {
      await vscode.commands.executeCommand('revealInExplorer', uri);
      return;
    }
    const document = await vscode.workspace.openTextDocument(uri);
    const editor = await vscode.window.showTextDocument(document, { preview: false });
    const start = Math.min(Math.max(0, Number(context.startLine || 1) - 1), Math.max(0, document.lineCount - 1));
    const end = Math.min(Math.max(start, Number(context.endLine || context.startLine || 1) - 1), Math.max(0, document.lineCount - 1));
    const range = new vscode.Range(start, 0, end, document.lineAt(end).text.length);
    editor.selection = new vscode.Selection(range.start, range.end);
    editor.revealRange(range, vscode.TextEditorRevealType.InCenterIfOutsideViewport);
  }

  revealChanges() {
    this.view?.show?.(true);
    this.postSnapshot();
    this.view?.webview.postMessage({ type: 'showTab', tab: 'changes' });
  }

  setReviewIssues(issues) {
    this.reviewIssues = issues;
    this.postSnapshot();
  }

  getHtml(webview) {
    const media = webview.asWebviewUri(vscode.Uri.joinPath(this.extensionUri, 'media'));
    const backendUrl = remoteWorkspaces.backendUrl();
    const wsUrl = remoteWorkspaces.webSocketUrl(backendUrl);
    const csp = [
      "default-src 'none'",
      `style-src ${webview.cspSource}`,
      `script-src ${webview.cspSource}`,
      `img-src ${webview.cspSource} data:`,
      `connect-src ${backendUrl} ${wsUrl}`,
    ].join('; ');

    return `<!doctype html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="${csp}"><link rel="stylesheet" href="${media}/chat.css?v=48"><title>EgoAgent</title></head>
  <body data-api="${escapeHtml(backendUrl)}" data-ws="${escapeHtml(wsUrl)}" data-api-token="${escapeHtml(remoteWorkspaces.accessToken)}"><script src="${media}/remote-network.js"></script><script src="${media}/vendor/markdown-it.umd.min.js?v=15.0.2"></script><script src="${media}/markdown.js?v=1"></script>
  <header class="topbar"><div class="brand"><span class="brand-mark">E</span><span>EgoAgent</span><span class="local-badge">AI + LOCAL 0.21.24</span></div><div class="topbar-actions"><button id="remoteQuick" class="workbench-link" title="打开 SSH 或 WSL 项目；文件、终端和 Agent 一起切换">SSH / WSL</button><button id="workbenchQuick" class="workbench-link" title="在编辑区打开 Agent Workbench">Workbench</button><div id="connection" class="connection offline"><span></span>连接中</div></div></header>
  <details id="agentConfigDetails" class="agent-config">
    <summary><span>Agent 配置</span><small id="agentConfigSummary">同一 Session 可逐轮切换 · 加载中…</small></summary>
  <section class="selectors">
<label>模式<select id="modeSelect" aria-label="运行模式"><option value="chat">Chat · 只读问答</option><option value="plan">Plan · 只读规划</option><option value="agent">Agent · 执行任务</option><option value="debug">Debug · 复现修复</option><option value="evolve">Evolve · 限域进化</option><option value="evaluate">Evaluate · 评测权限</option></select></label>
    <label>搜索 Harness<input id="harnessFilter" type="search" placeholder="例如 aider / research / browser" autocomplete="off"></label>
    <label>Harness<select id="harnessSelect" aria-label="Harness"></select></label>
    <label>Flow 版本<select id="harnessVersionSelect" aria-label="Flow 版本"></select></label>
    <div id="flowVersionNotice" class="harness-meta" hidden></div>
    <div class="harness-options"><small>内部组件仅在 Build 中作为 SubFlow 复用</small><span id="harnessCount"></span></div>
    <label>默认 Identity<select id="identitySelect" aria-label="默认 Identity"></select></label>
    <div id="harnessMeta" class="harness-meta"></div><details id="bindingsDetails"><summary>Agent 绑定与 DAG</summary><div id="slotBindings" class="slot-bindings"></div><div id="dagNodes" class="dag-nodes"></div></details>
  </section></details>
  <div class="session-strip" aria-label="当前项目的 Agent Sessions"><div id="sessionTabs" class="session-tabs"><span class="session-empty">新 Session</span></div><button id="newSession" class="new-session" title="在当前项目新建独立 Session" aria-label="新建 Session">＋</button><button id="openSessionPortfolio" class="new-session" title="打开跨项目 Session Portfolio" aria-label="打开 Session Portfolio">▥</button><button id="linkSessionWorkbench" class="new-session observe-session-button" title="在 Build 中只读观察当前 Session" aria-label="在 Build 中观察当前 Session" disabled>观察</button></div>
  <div id="sessionContextMenu" class="session-context-menu" role="menu" hidden><button data-session-action="rename" role="menuitem">重命名</button><button data-session-action="observe" role="menuitem">在 Build 中观察</button><button data-session-action="fork" role="menuitem">Fork Session</button><button data-session-action="stop" role="menuitem">结束运行</button><button data-session-action="delete" class="danger" role="menuitem">移到回收站</button></div>
  <nav class="tabs" aria-label="EgoAgent views"><button class="tab active" data-tab="chat">对话</button><button class="tab" data-tab="changes">改动 <span id="pendingBadge" class="count-badge">0</span></button><button class="tab" data-tab="context">上下文</button></nav>
  <button id="workbenchStatus" class="workbench-status" hidden><span class="workbench-status-dot"></span><strong>Agent 就绪</strong><small></small></button>
  <div class="approval-controls"><button id="approvalMode" title="只影响当前 Session 的工具审批，不会关闭沙箱或解除禁止规则">工具审批：手动审批</button><small id="approvalModeHint">高风险操作需要你确认</small></div>
  <dialog id="approvalModeDialog" aria-labelledby="approvalModeTitle"><h3 id="approvalModeTitle">自动批准当前 Session 的工具操作？</h3><p>后续工具权限请求（包括当前等待的请求）将自动批准，可能修改文件、执行命令或访问网络。Host / Workspace guard 模式下命令以你的账号运行，并非操作系统沙箱。</p><p>明确禁止的操作、只读模式、文件访问边界和容器限制仍然生效。Flow 的人工审核/输入节点仍需你回答。只对当前 Session 生效，可随时切回手动。</p><div class="approval-actions"><button id="cancelAutoApproval">保持手动</button><button id="confirmAutoApproval">确认自动批准</button></div></dialog>
  <main>
    <section id="chatTab" class="tab-panel active"><div id="messages" class="messages"><div id="emptyState" class="empty-state"><div class="empty-icon">⌁</div><strong>用自己的 DAG 开始工作</strong><span>聊天、补全、编辑与审查优先使用已配置模型；服务不可用时自动回退本地能力。</span></div></div>
      <div id="contextChips" class="context-chips"></div><div class="composer"><div id="prompt" class="composer-input" contenteditable="true" role="textbox" aria-multiline="true" data-placeholder="给 DAG Agent 一个任务… 可粘贴或拖入文件 / 选区"></div><div id="agentActivity" class="agent-activity idle" role="status" aria-live="polite" aria-busy="false"><span class="agent-activity-indicator" aria-hidden="true"></span><span id="composerHint">就绪 · 发送消息开始</span><button id="stopCurrentRun" class="agent-stop" title="停止当前 Session" hidden>停止</button></div><div class="composer-actions"><div class="context-picker-wrap"><button id="attachContext" class="icon-button" title="插入结构化上下文">＠</button><div id="contextPicker" class="context-picker" hidden><button data-attach-kind="file"><strong>@file</strong><small>当前文件</small></button><button data-attach-kind="selection"><strong>@selection</strong><small>当前选区</small></button><button data-attach-kind="workspace"><strong>@workspace</strong><small>当前项目代码地图</small></button><button data-attach-kind="terminal"><strong>@terminal</strong><small>当前终端选区</small></button></div></div><span class="composer-meta">Enter 发送 · Shift+Enter 换行</span><button id="send" class="primary">发送</button></div></div>
    </section>
    <section id="changesTab" class="tab-panel"><div class="change-toolbar"><button id="mockChanges" class="primary">✦ AI 多段改动</button><button id="inlineEdit">AI 内联编辑</button><button id="localReview">AI 代码审查</button><button id="refreshChanges">↻</button></div><div id="changeSummary" class="context-summary"></div><div id="reviewIssues" class="review-issues"></div><div id="changeList" class="change-list"><div class="muted">尚无改动</div></div></section>
    <section id="contextTab" class="tab-panel"><div class="context-actions workbench-actions"><button id="openWorkbench">工作台</button><button id="openHarnessBuilder">DAG 构建</button><button id="openEvaluation">评测</button><button id="openEvolution">进化</button><button id="openSecurity">安全设置</button></div><div class="context-actions"><button id="refreshContext">↻ 刷新</button><button id="createCheckpoint">＋ 检查点</button><button id="codeMap">代码地图</button><button id="previewApp">应用预览</button><button id="commitMessage">提交消息</button></div><div id="editorContext" class="editor-context"></div><div id="contextSummary" class="context-summary"></div><details open><summary>本轮上下文计划</summary><div id="contextPlan" class="context-list"><div class="muted">发送消息后显示自动选择、排除原因与 token 预算。</div></div></details><details><summary>记忆</summary><div id="memoryList" class="context-list"></div></details><details><summary>项目规则 / AGENTS.md</summary><div id="rulesList" class="context-list"></div></details><details><summary>检查点</summary><div id="checkpointsList" class="context-list"></div></details><details><summary>历史 Sessions</summary><div id="sessionsList" class="context-list"></div></details></section>
  </main><dialog id="attachmentEditor" class="attachment-editor" aria-labelledby="attachmentEditorTitle"><form method="dialog"><header><div><strong id="attachmentEditorTitle">文本附件</strong><small id="attachmentEditorMeta"></small></div><button id="attachmentEditorClose" value="cancel" title="关闭" aria-label="关闭">×</button></header><textarea id="attachmentEditorContent" spellcheck="false" aria-label="附件内容"></textarea><footer><span id="attachmentEditorNotice">修改只会更新本次尚未发送的上下文。</span><button id="attachmentEditorCancel" value="cancel">取消</button><button id="attachmentEditorSave" value="default" class="primary">保存</button></footer></form></dialog><div id="toast" class="toast" role="status"></div><script src="${media}/chat.js?v=51"></script></body></html>`;
  }
}

let workbenchPanel;
let workbenchTab = 'home';
let workbenchContext;
let workbenchProvider;
let workbenchReviewManager;
let workbenchStatusItem;
let pendingWorkbenchHandoff;
let workbenchRuntimeStatus = { running: false, scope: 'builder', status: 'idle', evolutionProposals: 0, online: false };

const WORKBENCH_TABS = new Set(['home', 'harness', 'ir', 'tasks', 'research', 'background', 'library', 'packages', 'changes', 'checkpoints', 'identity', 'environment', 'sessions', 'settings', 'evolution', 'coc', 'flow']);
const WORKBENCH_ROUTE_LABELS = { home: 'Home', harness: 'Build', tasks: 'Evaluate', evolution: 'Improve', library: 'Library', packages: 'Deploy', flow: 'Heart Flow' };

function workbenchWorkspaceKey() {
  const workspace = normalizedFsPath(vscode.workspace.workspaceFolders?.[0]?.uri) || 'standalone';
  return `egoagent.workbench.route:${workspace}`;
}

function pendingWorkbenchChanges() {
  if (!workbenchReviewManager) return 0;
  const local = workbenchReviewManager.proposals.reduce((count, proposal) => count + proposal.hunks.filter((hunk) => hunk.status === 'pending').length, 0);
  const backend = workbenchReviewManager.activeBackendChanges().reduce((count, change) => count + (change.hunks || []).filter((hunk) => hunk.status === 'pending').length, 0);
  return local + backend;
}

function workbenchStatusSnapshot() {
  return { ...workbenchRuntimeStatus, pendingChanges: pendingWorkbenchChanges() };
}

function updateWorkbenchStatusSurface() {
  const snapshot = workbenchStatusSnapshot();
  if (workbenchStatusItem) {
    if (snapshot.running) {
      const icon = snapshot.waitingForInput ? '$(comment-discussion)' : snapshot.paused ? '$(debug-pause)' : '$(sync~spin)';
      const label = snapshot.scope === 'evaluate' ? '评测' : snapshot.scope === 'evolution' ? '进化' : 'Agent';
      workbenchStatusItem.text = `${icon} ${label}${snapshot.waitingForInput ? ' · 等待输入' : snapshot.currentNode ? ` · ${snapshot.currentNode}` : ''}`;
    } else if (snapshot.pendingChanges) {
      workbenchStatusItem.text = `$(diff) ${snapshot.pendingChanges} 待审改动`;
    } else if (snapshot.evolutionProposals) {
      workbenchStatusItem.text = `$(beaker) ${snapshot.evolutionProposals} 进化提案`;
    } else {
      workbenchStatusItem.text = '$(hubot) EgoAgent 就绪';
    }
    workbenchStatusItem.tooltip = [
      snapshot.harness ? `Harness: ${snapshot.harness}` : '',
      snapshot.status ? `状态: ${snapshot.status}` : '',
      snapshot.pendingChanges ? `待审代码块: ${snapshot.pendingChanges}` : '',
      snapshot.evolutionProposals ? `待处理进化提案: ${snapshot.evolutionProposals}` : '',
    ].filter(Boolean).join('\n') || '打开 Agent Workbench';
    workbenchStatusItem.show();
  }
  workbenchProvider?.view?.webview.postMessage({ type: 'workbenchStatus', status: snapshot });
}

async function refreshWorkbenchRuntimeStatus() {
  const backendUrl = remoteWorkspaces.backendUrl();
  const workspace = fsPathForBackend(vscode.workspace.workspaceFolders?.[0]?.uri);
  try {
    const [healthResponse, proposalsResponse] = await Promise.all([
      fetch(`${backendUrl}/api/workspace${workspace ? `?workspace=${encodeURIComponent(workspace)}` : ''}`),
      fetch(`${backendUrl}/api/evolution/proposals`),
    ]);
    const proposals = proposalsResponse.ok ? await proposalsResponse.json() : [];
    const proposalList = Array.isArray(proposals) ? proposals : (proposals.proposals || []);
    const pendingProposals = proposalList.filter((proposal) => !['accepted', 'applied', 'rejected', 'rolled_back', 'failed'].includes(String(proposal.status || '').toLowerCase())).length;
    const childStatusIsFresh = workbenchRuntimeStatus.reportedAt && Date.now() - workbenchRuntimeStatus.reportedAt < 15000;
    if (!childStatusIsFresh) {
      workbenchRuntimeStatus = {
        ...workbenchRuntimeStatus,
        scope: 'builder',
        running: false,
        observing: false,
        waitingForInput: false,
        paused: false,
        currentNode: undefined,
        runId: undefined,
        status: 'idle',
      };
    }
    workbenchRuntimeStatus = { ...workbenchRuntimeStatus, evolutionProposals: pendingProposals, online: healthResponse.ok };
  } catch {
    workbenchRuntimeStatus = { ...workbenchRuntimeStatus, online: false };
  }
  updateWorkbenchStatusSurface();
}

function getWorkbenchUrl(backendUrl, tab, options = {}) {
  const url = new URL(backendUrl);
  url.searchParams.set('embed', '1');
  url.searchParams.set('tab', tab);
  url.searchParams.set('apiBase', backendUrl.replace(/\/$/, ''));
  url.searchParams.set('wsBase', remoteWorkspaces.webSocketUrl(backendUrl));
  const workspace = fsPathForBackend(vscode.workspace.workspaceFolders?.[0]?.uri);
  if (workspace) url.searchParams.set('workspace', workspace);
  if (options.linkRunId) url.searchParams.set('link_run', String(options.linkRunId));
  return url.toString();
}

function renderRemoteWorkbench(panel, tab, options = {}) {
  const backendUrl = remoteWorkspaces.backendUrl();
  const frameUrl = getWorkbenchUrl(backendUrl, tab, options);
  panel.title = `EgoAgent · ${WORKBENCH_ROUTE_LABELS[tab] || 'Workbench'}`;
  panel.webview.html = `<!doctype html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; frame-src ${backendUrl}; style-src 'unsafe-inline'; script-src 'unsafe-inline';"><style>html,body,iframe{width:100%;height:100%;margin:0;border:0;background:var(--vscode-editor-background,#1e1e1e)}body{overflow:hidden}iframe{display:block}</style></head><body><iframe id="egoagent-workbench-frame" src="${escapeHtml(frameUrl)}" title="EgoAgent Agent Workbench"></iframe><script>const vscode=acquireVsCodeApi();const frame=document.getElementById('egoagent-workbench-frame');window.addEventListener('message',(event)=>{const message=event.data||{};if(event.source===frame.contentWindow&&message.source==='egoagent-workbench'){vscode.postMessage(message);return;}if(message.source==='egoagent-shell'){frame.contentWindow.postMessage(message,'*');}});</script></body></html>`;
}

async function renderWorkbench(panel, tab, options = {}) {
  const backendUrl = remoteWorkspaces.backendUrl();
  const wsUrl = remoteWorkspaces.webSocketUrl(backendUrl);
  panel.title = `EgoAgent · ${WORKBENCH_ROUTE_LABELS[tab] || 'Workbench'}`;
  try {
    const root = vscode.Uri.joinPath(workbenchContext.extensionUri, 'workbench');
    const indexBytes = await vscode.workspace.fs.readFile(vscode.Uri.joinPath(root, 'index.html'));
    let html = new TextDecoder('utf-8').decode(indexBytes);
    html = html.replace(/(src|href)="\.\/([^"?#]+)([^"]*)"/g, (_match, attribute, relative, suffix) => {
      const resource = panel.webview.asWebviewUri(vscode.Uri.joinPath(root, ...String(relative).split('/')));
      return `${attribute}="${resource}${suffix || ''}"`;
    });
    const bootstrap = JSON.stringify({
      workspace: fsPathForBackend(vscode.workspace.workspaceFolders?.[0]?.uri),
      apiBase: backendUrl,
      accessToken: remoteWorkspaces.accessToken,
      runtimeLabel: remoteWorkspaces.runtimeLabel,
      wsBase: wsUrl,
      tab,
      linkRunId: options.linkRunId ? String(options.linkRunId) : '',
    }).replaceAll('<', '\\u003c');
    const csp = [
      "default-src 'none'",
      `script-src ${panel.webview.cspSource} 'unsafe-inline'`,
      `style-src ${panel.webview.cspSource} 'unsafe-inline'`,
      `img-src ${panel.webview.cspSource} data: blob:`,
      `font-src ${panel.webview.cspSource}`,
      `connect-src ${backendUrl} ${wsUrl}`,
      'worker-src blob:',
    ].join('; ');
    const networkScript = panel.webview.asWebviewUri(vscode.Uri.joinPath(workbenchContext.extensionUri, 'media', 'remote-network.js'));
    html = html.replace('<head>', `<head><meta http-equiv="Content-Security-Policy" content="${escapeHtml(csp)}"><script>window.__EGOAGENT_WORKBENCH__=${bootstrap};</script><script src="${networkScript}"></script>`);
    panel.webview.html = html;
  } catch (error) {
    console.warn('Packaged Agent Workbench unavailable, using local backend frontend:', error);
    renderRemoteWorkbench(panel, tab, options);
  }
}

function postWorkbenchShellMessage(message) {
  return workbenchPanel?.webview.postMessage({ source: 'egoagent-shell', ...message });
}

async function openWorkbenchFile(message) {
  const filePath = String(message.path || '');
  if (!filePath) return;
  const document = await vscode.workspace.openTextDocument(workspaceUriForPath(filePath));
  const editor = await vscode.window.showTextDocument(document, { preview: false });
  const requestedLine = Math.max(1, Number(message.line || 1));
  const requestedEnd = Math.max(requestedLine, Number(message.endLine || requestedLine));
  const start = new vscode.Position(Math.min(document.lineCount - 1, requestedLine - 1), 0);
  const endLine = Math.min(document.lineCount - 1, requestedEnd - 1);
  const end = new vscode.Position(endLine, document.lineAt(endLine).text.length);
  editor.selection = new vscode.Selection(start, end);
  editor.revealRange(new vscode.Range(start, end), vscode.TextEditorRevealType.InCenterIfOutsideViewport);
}

async function openWorkbenchWorkspace(message) {
  const folderPath = String(message.path || '').trim();
  if (!folderPath) return;
  const target = workspaceUriForPath(folderPath);
  await vscode.commands.executeCommand('vscode.openFolder', target, Boolean(message.newWindow ?? true));
}

async function pickWorkbenchProjectFolder(message) {
  const selected = await vscode.window.showOpenDialog({
    title: String(message.title || '选择 Project 文件夹'),
    openLabel: String(message.openLabel || '选择文件夹'),
    canSelectFiles: false,
    canSelectFolders: true,
    canSelectMany: false,
  });
  return selected?.[0] ? fsPathForBackend(selected[0]) : '';
}

function openWorkbench(requestedTab, options = {}) {
  const restoredTab = workbenchContext?.workspaceState.get(workbenchWorkspaceKey(), 'home');
  const tab = WORKBENCH_TABS.has(requestedTab) ? requestedTab : WORKBENCH_TABS.has(restoredTab) ? restoredTab : 'home';
  if (workbenchPanel) {
    workbenchPanel.reveal(vscode.ViewColumn.One);
    workbenchTab = tab;
    workbenchPanel.title = `EgoAgent · ${WORKBENCH_ROUTE_LABELS[tab] || 'Workbench'}`;
    workbenchPanel.webview.postMessage({ source: 'egoagent-shell', type: 'navigate', tab });
    if (options.linkRunId) {
      postWorkbenchShellMessage({ type: 'link-session', runId: String(options.linkRunId) });
    }
    if (pendingWorkbenchHandoff) {
      postWorkbenchShellMessage({ type: 'context-handoff', items: pendingWorkbenchHandoff });
      pendingWorkbenchHandoff = undefined;
    }
    return workbenchPanel;
  }
  workbenchTab = tab;
  workbenchPanel = vscode.window.createWebviewPanel('egoagent.workbench', 'EgoAgent Workbench', vscode.ViewColumn.One, {
    enableScripts: true,
    // Builder drafts and route selections are workspace-scoped in the React
    // session store, so the heavy graph view does not need to consume CPU and
    // memory while the user is editing code in another tab.
    retainContextWhenHidden: false,
    localResourceRoots: [
      vscode.Uri.joinPath(workbenchContext.extensionUri, 'workbench'),
      vscode.Uri.joinPath(workbenchContext.extensionUri, 'media'),
    ],
  });
  workbenchPanel.webview.onDidReceiveMessage(async (message) => {
    if (message?.source !== 'egoagent-workbench') return;
    if (message.type === 'route-change' && WORKBENCH_TABS.has(message.tab)) {
      workbenchTab = message.tab;
      workbenchPanel.title = `EgoAgent · ${WORKBENCH_ROUTE_LABELS[workbenchTab] || 'Workbench'}`;
      void workbenchContext?.workspaceState.update(workbenchWorkspaceKey(), workbenchTab);
      if (pendingWorkbenchHandoff) {
        postWorkbenchShellMessage({ type: 'context-handoff', items: pendingWorkbenchHandoff });
        pendingWorkbenchHandoff = undefined;
      }
      return;
    }
    if (message.type === 'runtime-status') {
      workbenchRuntimeStatus = { ...workbenchRuntimeStatus, ...message, reportedAt: Date.now() };
      updateWorkbenchStatusSurface();
      return;
    }
    if (message.type === 'harness-version-created') {
      workbenchProvider?.view?.webview.postMessage({
        type: 'harnessVersionCreated',
        harness: message.harness,
        version: message.version,
      });
      return;
    }
    if (message.type === 'open-change') {
      try {
        await workbenchProvider.refreshBackendReviewState();
        const opened = await workbenchProvider.reviewManager.openBackendDiff(message.id, message.hunkId);
        if (!opened) throw new Error('找不到可审阅的文本改动，请刷新后重试');
        postWorkbenchShellMessage({ type: 'request-result', requestId: message.requestId, ok: true, value: true });
      } catch (error) {
        postWorkbenchShellMessage({ type: 'request-result', requestId: message.requestId, ok: false, error: error?.message || String(error) });
      }
      return;
    }
    if (message.type === 'open-file') void openWorkbenchFile(message);
    if (message.type === 'open-workspace') void openWorkbenchWorkspace(message);
    if (message.type === 'pick-project-folder') {
      try {
        const path = await pickWorkbenchProjectFolder(message);
        postWorkbenchShellMessage({ type: 'request-result', requestId: message.requestId, ok: true, value: path });
      } catch (error) {
        postWorkbenchShellMessage({ type: 'request-result', requestId: message.requestId, ok: false, error: error?.message || String(error) });
      }
    }
    if (message.type === 'review-changes') void vscode.commands.executeCommand('egoagent.reviewChanges');
    if (message.type === 'review-change') {
      try {
        await workbenchProvider.applyBackendChange(message);
        postWorkbenchShellMessage({ type: 'request-result', requestId: message.requestId, ok: true });
      } catch (error) {
        postWorkbenchShellMessage({ type: 'request-result', requestId: message.requestId, ok: false, error: error?.message || String(error) });
      }
    }
  });
  workbenchPanel.onDidDispose(() => { workbenchPanel = undefined; workbenchTab = 'home'; });
  void renderWorkbench(workbenchPanel, tab, options);
  void workbenchContext?.workspaceState.update(workbenchWorkspaceKey(), tab);
  return workbenchPanel;
}

async function openCodeMap() {
  const files = await vscode.workspace.findFiles(
    '**/*.{py,js,jsx,ts,tsx,rs,go,java}',
    '**/{node_modules,.git,.runtime,.egoagent,.egoagent_checkpoints,__pycache__,void-web,dist,build,tmp,logs,sessions,research,experiments/external,experiments/**/_runs}/**',
    60,
  );
  if (!files.length) return vscode.window.showInformationMessage('当前工作区没有可建立代码地图的源文件');
  const mapped = await Promise.all(files.map(async (uri) => {
    try {
      const symbols = await vscode.commands.executeCommand('vscode.executeDocumentSymbolProvider', uri) || [];
      const document = symbols.length ? undefined : await vscode.workspace.openTextDocument(uri);
      const fallback = document ? extractLocalSymbols(document) : [];
      return {
        path: displayPath(uri),
        symbols: symbols.length ? symbols.slice(0, 25).map((symbol) => ({
          name: symbol.name,
          detail: symbol.detail || '',
          kind: vscode.SymbolKind[symbol.kind] || 'Symbol',
          line: (symbol.range?.start?.line || 0) + 1,
        })) : fallback.slice(0, 25),
      };
    } catch { return { path: displayPath(uri), symbols: [] }; }
  }));
  const panel = vscode.window.createWebviewPanel('egoagent.codeMap', 'EgoAgent Code Map', vscode.ViewColumn.One, { enableScripts: false, retainContextWhenHidden: true });
  const fileHtml = mapped.map((file) => `<details ${file.symbols.length ? '' : 'class="empty"'}><summary>${escapeHtml(file.path)} <span>${file.symbols.length}</span></summary><div class="symbols">${file.symbols.length ? file.symbols.map((symbol) => `<div class="symbol"><b>${escapeHtml(symbol.name)}</b><span>${escapeHtml(symbol.kind)} · L${symbol.line}</span>${symbol.detail ? `<small>${escapeHtml(symbol.detail)}</small>` : ''}</div>`).join('') : '<em>No document symbols</em>'}</div></details>`).join('');
  panel.webview.html = `<!doctype html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{font-family:var(--vscode-font-family);color:var(--vscode-foreground);background:var(--vscode-editor-background);padding:18px;max-width:1100px;margin:auto}header{display:flex;justify-content:space-between;align-items:end;margin-bottom:14px}h1{font-size:20px;margin:0}header span,summary span{color:var(--vscode-descriptionForeground)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:8px}details{border:1px solid var(--vscode-widget-border);border-radius:6px;background:var(--vscode-sideBar-background)}summary{padding:9px;cursor:pointer;font-weight:600;display:flex;justify-content:space-between}.symbols{padding:0 8px 8px}.symbol{display:grid;grid-template-columns:1fr auto;gap:2px 8px;padding:5px;border-top:1px solid var(--vscode-widget-border);font-size:12px}.symbol span,.symbol small,em{color:var(--vscode-descriptionForeground)}.symbol small{grid-column:1/-1}</style></head><body><header><div><h1>EgoAgent Code Map</h1><span>本地符号索引，不上传代码</span></div><span>${mapped.length} files · ${mapped.reduce((n, file) => n + file.symbols.length, 0)} symbols</span></header><div class="grid">${fileHtml}</div></body></html>`;
}

async function previewApplication() {
  const configured = vscode.workspace.getConfiguration('egoagent').get('previewUrl', 'http://127.0.0.1:8765');
  const remote = Boolean(remoteWorkspaces.accessToken);
  const url = await vscode.window.showInputBox({
    prompt: remote ? '输入浏览器能访问的应用地址；SSH 应用请先转发对应端口，localhost 指 Windows 浏览器所在机器' : '输入本地应用地址',
    value: remote && configured === 'http://127.0.0.1:8765' ? '' : configured,
    validateInput: (value) => /^https?:\/\//i.test(value) ? undefined : '请输入 http:// 或 https:// 地址',
  });
  if (!url) return;
  await vscode.commands.executeCommand('simpleBrowser.show', url);
}

async function generateCommitMessage(aiClient) {
  const gitExtension = vscode.extensions.getExtension('vscode.git') || vscode.extensions.getExtension('vscode.git-base');
  if (!gitExtension) return vscode.window.showWarningMessage('Void 当前没有可用的 Git 扩展 API');
  const exports = gitExtension.isActive ? gitExtension.exports : await gitExtension.activate();
  const api = exports?.getAPI?.(1);
  const repository = api?.repositories?.[0];
  if (!repository) return vscode.window.showWarningMessage('当前工作区没有已打开的 Git 仓库');
  const state = repository.state;
  const changes = [...(state.indexChanges || []), ...(state.workingTreeChanges || []), ...(state.mergeChanges || [])];
  const paths = [...new Set(changes.map((change) => displayPath(change.uri || change.originalUri)).filter(Boolean))];
  if (!paths.length) return vscode.window.showInformationMessage('当前没有可生成提交消息的代码变更');
  const docsOnly = paths.every((path) => /(?:^|\/)(?:docs?|README)|\.md$/i.test(path));
  const testsOnly = paths.every((path) => /(?:test|spec|swebench)/i.test(path));
  const type = docsOnly ? 'docs' : testsOnly ? 'test' : 'feat';
  const topFolders = [...new Set(paths.map((path) => path.replaceAll('\\', '/').split('/')[0]).filter((part) => part && !part.includes('.')))];
  const scope = topFolders.length === 1 ? `(${topFolders[0]})` : '';
  const subject = paths.length === 1
    ? `update ${paths[0].replaceAll('\\', '/').split('/').pop()}`
    : `update ${paths.length} files across ${Math.max(1, topFolders.length)} areas`;
  let message = `${type}${scope}: ${subject}`;
  let generatedByAI = false;
  try {
    const statuses = changes.map((change) => `${change.status ?? 'changed'} ${displayPath(change.uri || change.originalUri)}`);
    const result = await aiClient.request('commit-message', { changes: statuses.join('\n') });
    if (result.message) {
      message = result.message;
      generatedByAI = true;
    }
  } catch {
    // Keep the deterministic Conventional Commit draft when the provider is
    // unavailable or the weak model returns an invalid subject.
  }
  repository.inputBox.value = message;
  await vscode.commands.executeCommand('workbench.view.scm');
  vscode.window.showInformationMessage(generatedByAI ? 'EgoAgent AI 已生成提交消息草稿' : 'EgoAgent 已使用本地规则生成提交消息草稿');
}

function activate(context) {
  remoteWorkspaces.registerRemoteWorkspaces(context);
  const metrics = new LocalMetrics(context);
  const aiClient = new AIClient();
  let provider;
  const reviewManager = new ChangeReviewManager(context, metrics, () => provider?.postSnapshot(), aiClient);
  const completionProvider = new LocalCompletionProvider(context, metrics, aiClient, () => provider?.postSnapshot());
  const nextEditPredictor = new NextEditPredictor(context, aiClient, reviewManager, metrics);
  const reviewer = new LocalReviewer(context, metrics);
  provider = new DagChatViewProvider(context, reviewManager, completionProvider, reviewer, metrics, aiClient);
  workbenchContext = context;
  workbenchProvider = provider;
  workbenchReviewManager = reviewManager;
  workbenchStatusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 78);
  workbenchStatusItem.command = 'egoagent.openWorkbench';
  context.subscriptions.push(workbenchStatusItem);
  // Review state must stay current even when the Chat webview is closed. This
  // also rehydrates durable backend transactions immediately after a restart.
  void Promise.all([provider.refreshBackendReviewState(), refreshWorkbenchRuntimeStatus()]);
  const workbenchPoller = setInterval(() => {
    void Promise.all([provider.refreshBackendReviewState(), refreshWorkbenchRuntimeStatus()]);
  }, 3500);
  context.subscriptions.push({ dispose: () => clearInterval(workbenchPoller) });

  const runMockEdit = async (requestedMode) => {
    const editor = vscode.window.activeTextEditor;
    if (!editor) return vscode.window.showWarningMessage('请先打开一个代码文件');
    let mode = requestedMode;
    if (!mode || typeof mode !== 'string') {
      const choice = await vscode.window.showQuickPick([
        { label: '文档与可维护性', value: 'maintainability', description: '由模型生成多段可独立审查的改动' },
        { label: '可观测性', value: 'observability', description: '由模型为重要函数增加合理观测能力' },
        { label: '输入保护', value: 'guards', description: '由模型生成输入校验提案' },
      ], { placeHolder: '选择 AI Agent 的改动策略' });
      if (!choice) return;
      mode = choice.value;
    }
    const modeInstructions = {
      maintainability: 'Improve documentation and maintainability in several independent places without changing behavior.',
      observability: 'Add useful, non-sensitive observability to up to three important functions. Avoid noisy logs.',
      guards: 'Add appropriate input validation to up to three public functions while preserving valid behavior.',
    };
    let hunks;
    let aiGenerated = false;
    try {
      const result = await aiClient.request('edit', {
        code: editor.document.getText(),
        language: editor.document.languageId,
        path: displayPath(editor.document.uri),
        instruction: modeInstructions[mode] || String(mode),
      });
      hunks = result.hunks || [];
      aiGenerated = true;
    } catch (error) {
      hunks = buildMockHunks(editor.document, mode);
      vscode.window.showWarningMessage(`EgoAgent AI 多段编辑不可用，已使用本地方案：${error.message || error}`);
    }
    if (!hunks.length) return vscode.window.showInformationMessage('当前文件没有适合此策略的函数；请换一个文件或使用“内联编辑”');
    await reviewManager.propose(editor.document, `${aiGenerated ? 'AI Agent' : '本地 Agent'} · ${mode}`, hunks);
    provider.revealChanges();
    vscode.window.showInformationMessage('Agent 改动已应用；请直接在编辑器绿色代码块上接受或拒绝');
  };

  const runInlineEdit = async (requested) => {
    const editor = vscode.window.activeTextEditor;
    if (!editor) return vscode.window.showWarningMessage('请先打开一个代码文件');
    const options = requested && typeof requested === 'object' ? requested : { instruction: requested };
    const document = editor.document;
    const originalText = document.getText();
    const documentLines = splitLines(originalText);
    const selection = editor.selection;
    const availableScopes = [
      ...(selection.isEmpty ? [] : [{ label: '选区', description: `${selection.end.line - selection.start.line + 1} 行`, value: 'selection' }]),
      { label: '光标所在行', description: `第 ${selection.active.line + 1} 行`, value: 'cursor' },
      { label: '整个文件', description: `${document.lineCount} 行，将由整文件 edit 角色处理`, value: 'file' },
    ];
    const scopeChoice = options.scope
      ? availableScopes.find((item) => item.value === options.scope)
      : await vscode.window.showQuickPick(availableScopes, {
        placeHolder: '选择 Inline Edit 的作用范围',
        title: 'EgoAgent Inline Edit',
      });
    if (!scopeChoice) return;
    const instruction = options.instruction || await vscode.window.showInputBox({
      prompt: `描述要对${scopeChoice.label}执行的修改（生成后先预览，可以继续追问）`,
      placeHolder: '例如：增加错误处理 / 重构为纯函数 / 补充参数说明',
    });
    if (!instruction) return;

    const scope = scopeChoice.value;
    const start = scope === 'file' ? 0 : scope === 'selection' ? selection.start.line : selection.active.line;
    const end = scope === 'file'
      ? documentLines.length
      : scope === 'selection'
        ? Math.min(documentLines.length, selection.end.line + (selection.end.character ? 1 : 0))
        : Math.min(documentLines.length, start + 1);
    const eol = document.eol === vscode.EndOfLine.CRLF ? '\r\n' : '\n';
    const before = documentLines.slice(Math.max(0, start - 45), start).join('\n');
    const after = documentLines.slice(end, Math.min(documentLines.length, end + 45)).join('\n');
    const baseRegion = documentLines.slice(start, Math.max(start + 1, end)).join(eol);
    let currentRegion = baseRegion;
    let proposedText = originalText;
    let currentInstruction = String(instruction);
    let aiGenerated = true;
    let previewUri;
    let generation = 0;

    const materializeRegion = (replacement) => applyLineHunks(originalText, [{
      start,
      end: Math.max(start + 1, end),
      newLines: splitLines(replacement),
    }], eol);

    const generate = async (task) => vscode.window.withProgress({
      location: vscode.ProgressLocation.Notification,
      title: `EgoAgent 正在生成${scopeChoice.label}编辑预览`,
      cancellable: false,
    }, async (progress) => {
      progress.report({ message: generation ? `继续改进（第 ${generation + 1} 版）` : '调用 edit 模型角色…' });
      if (scope === 'file') {
        const result = await aiClient.request('edit', {
          code: currentRegion,
          instruction: task,
          language: document.languageId,
          path: displayPath(document.uri),
        });
        if (!result.changed || !Array.isArray(result.hunks) || !result.hunks.length) return currentRegion;
        return applyLineHunks(currentRegion, result.hunks, eol);
      }
      const result = await aiClient.request('inline-edit', {
        code: currentRegion,
        before,
        after,
        instruction: task,
        language: document.languageId,
        path: displayPath(document.uri),
      });
      return String(result.replacement ?? currentRegion).replaceAll('\r\n', '\n').replaceAll('\n', eol);
    });

    try {
      currentRegion = await generate(currentInstruction);
      proposedText = scope === 'file' ? currentRegion : materializeRegion(currentRegion);
    } catch (error) {
      aiGenerated = false;
      const endPosition = end >= document.lineCount
        ? document.positionAt(originalText.length)
        : new vscode.Position(end, 0);
      const scopedSelection = new vscode.Selection(new vscode.Position(start, 0), endPosition);
      const fallbackHunks = buildInlineHunks(document, scopedSelection, currentInstruction);
      proposedText = applyLineHunks(originalText, fallbackHunks, eol);
      vscode.window.showWarningMessage(`EgoAgent AI 内联编辑不可用，已使用本地方案：${error.message || error}`);
    }
    if (proposedText === originalText) return vscode.window.showInformationMessage('模型没有生成任何代码变化');

    while (true) {
      generation += 1;
      previewUri = await reviewManager.showDraftPreview(
        document,
        proposedText,
        `EgoAgent Inline Edit 预览 #${generation} · ${displayPath(document.uri)}`,
        previewUri,
      );
      const decision = options.autoApply ? { value: 'apply' } : await vscode.window.showQuickPick([
        { label: '$(check) 应用并进入逐段审阅', description: '立即写入文件；之后可逐段 Accept / Refuse，Ctrl+Z 撤销决定', value: 'apply' },
        { label: '$(edit) 继续追问改进', description: '以当前预览为基础追加要求', value: 'refine' },
        { label: '$(refresh) 重新生成', description: '回到原始代码并重新生成这一版', value: 'regenerate' },
        { label: '$(close) 取消', description: '不修改文件', value: 'cancel' },
      ], { placeHolder: `检查第 ${generation} 版红绿 Diff，然后选择下一步`, title: 'EgoAgent Inline Edit 预览' });

      if (!decision || decision.value === 'cancel') {
        await reviewManager.closeDraftPreview(previewUri);
        return vscode.window.showInformationMessage('已取消 Inline Edit，文件没有变化');
      }
      if (decision.value === 'refine' || decision.value === 'regenerate') {
        if (!aiGenerated) {
          vscode.window.showWarningMessage('本地降级编辑不支持追问；请应用当前预览或取消');
          continue;
        }
        const followUp = decision.value === 'regenerate' ? currentInstruction : await vscode.window.showInputBox({
          prompt: '继续描述要改进的地方',
          placeHolder: '例如：保持 API 不变，并补上空输入测试',
        });
        if (!followUp) continue;
        if (decision.value === 'regenerate') currentRegion = baseRegion;
        currentInstruction = String(followUp);
        try {
          currentRegion = await generate(currentInstruction);
          proposedText = scope === 'file' ? currentRegion : materializeRegion(currentRegion);
          continue;
        } catch (error) {
          vscode.window.showErrorMessage(`继续改进失败，保留上一版预览：${error.message || error}`);
          continue;
        }
      }

      await reviewManager.closeDraftPreview(previewUri);
      if (document.getText() !== originalText) {
        return vscode.window.showWarningMessage('文件在预览期间被修改，已取消应用以保护你的代码');
      }
      if (!await document.save()) return vscode.window.showErrorMessage('无法保存当前文件，Inline Edit 未应用');
      if (document.getText() !== originalText) {
        return vscode.window.showWarningMessage('保存时格式化器修改了文件，请重新运行 Inline Edit');
      }
      const workspaceFolder = vscode.workspace.getWorkspaceFolder(document.uri) || vscode.workspace.workspaceFolders?.[0];
      if (!workspaceFolder) return vscode.window.showErrorMessage('Inline Edit 需要一个已打开的工作区');
      const transactionId = `void-inline-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      const response = await fetch(`${aiClient.backendUrl}/api/session/changes/apply-text`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace: fsPathForBackend(workspaceFolder.uri),
          file: fsPathForBackend(document.uri),
          old_text: originalText,
          new_text: proposedText,
          transaction_id: transactionId,
          tool_name: `${aiGenerated ? 'AI' : 'Local'} Inline Edit · ${instruction}`,
        }),
      });
      const responseText = await response.text();
      let result = {};
      try { result = responseText ? JSON.parse(responseText) : {}; } catch { result = { error: responseText }; }
      if (!response.ok) throw new Error(result.error || `Inline Edit 写入失败 (${response.status})`);

      if (document.getText() === originalText) {
        const edit = new vscode.WorkspaceEdit();
        edit.replace(document.uri, fullDocumentRange(document), proposedText);
        await vscode.workspace.applyEdit(edit);
        await document.save();
      }
      reviewManager.selectBackendTransaction(transactionId);
      await provider.refreshBackendReviewState();
      provider.revealChanges();
      vscode.window.showInformationMessage('Inline Edit 已写入；可在编辑器红绿代码块逐段 Accept / Refuse，Ctrl+Z 撤销最近决定');
      return result.change;
    }
  };

  const runLocalReview = async () => {
    const editor = vscode.window.activeTextEditor;
    if (!editor) return vscode.window.showWarningMessage('请先打开一个代码文件');
    let issues;
    let aiGenerated = false;
    try {
      issues = await reviewer.runAI(editor.document, aiClient);
      aiGenerated = true;
    } catch (error) {
      issues = reviewer.run(editor.document);
      vscode.window.showWarningMessage(`EgoAgent AI 审查不可用，已使用本地规则：${error.message || error}`);
    }
    provider.setReviewIssues(issues);
    provider.revealChanges();
    vscode.window.showInformationMessage(issues.length ? `EgoAgent ${aiGenerated ? 'AI' : '本地'}审查发现 ${issues.length} 个问题` : `EgoAgent ${aiGenerated ? 'AI' : '本地'}审查未发现问题`);
  };

  const runTerminalCommand = async (requestedCommand) => {
    let command = String(requestedCommand || '').trim();
    if (!command) command = await vscode.window.showInputBox({ prompt: '要在集成终端运行的命令' }) || '';
    if (!command) return;
    const choice = await vscode.window.showWarningMessage(
      `EgoAgent 请求运行终端命令`,
      { modal: true, detail: command },
      '运行',
      '编辑',
    );
    if (choice === '编辑') return runTerminalCommand(await vscode.window.showInputBox({ value: command, prompt: '检查并编辑命令后再审批' }));
    if (choice !== '运行') {
      provider.view?.webview.postMessage({ type: 'commandResult', ok: false, command, message: '用户取消了终端命令' });
      return;
    }
    const terminal = vscode.window.createTerminal({ name: 'EgoAgent', cwd: vscode.workspace.workspaceFolders?.[0]?.uri });
    terminal.show(true);
    terminal.sendText(command, true);
    provider.view?.webview.postMessage({ type: 'commandResult', ok: true, command, message: '命令已发送到集成终端' });
  };

  const copyEditorContext = async () => {
    const editor = vscode.window.activeTextEditor;
    if (!editor || editor.selection.isEmpty) return vscode.commands.executeCommand('editor.action.clipboardCopyAction');
    const document = editor.document;
    const range = selectionLineRange(editor.selection);
    const selectedText = document.getText(editor.selection);
    await vscode.commands.executeCommand('editor.action.clipboardCopyAction');
    let clipboardText = '';
    try { clipboardText = await vscode.env.clipboard.readText(); } catch {}
    provider.rememberCopiedContext({
      kind: 'selection',
      title: `${displayPath(document.uri)}:${range.startLine}-${range.endLine}`,
      path: displayPath(document.uri),
      absolutePath: fsPathForBackend(document.uri),
      startLine: range.startLine,
      endLine: range.endLine,
      language: document.languageId,
      content: (clipboardText || selectedText).slice(0, 50000),
      truncated: (clipboardText || selectedText).length > 50000,
    });
  };

  const captureTerminalContext = async () => {
    const terminalName = vscode.window.activeTerminal?.name || 'Terminal';
    let previousClipboard = '';
    try { previousClipboard = await vscode.env.clipboard.readText(); } catch {}
    await vscode.commands.executeCommand('workbench.action.terminal.copySelection');
    const clipboardText = await readClipboardAfterCopy(previousClipboard);
    if (!clipboardText) {
      vscode.window.showWarningMessage('EgoAgent 没有读取到终端选区。请重新选中文本，再点击终端右上角的“加入对话”按钮。');
      return null;
    }
    const lines = clipboardLineCount(clipboardText);
    const terminalContext = {
      kind: 'terminal',
      title: `Terminal · ${terminalName} · ${lines} ${lines === 1 ? 'line' : 'lines'}`,
      terminalName,
      language: 'shell',
      content: clipboardText.slice(0, 50000),
      truncated: clipboardText.length > 50000,
    };
    provider.rememberCopiedContext(terminalContext);
    return terminalContext;
  };

  const copyTerminalContext = async () => {
    const terminalContext = await captureTerminalContext();
    if (!terminalContext) return;
    const lines = clipboardLineCount(terminalContext.content);
    vscode.window.setStatusBarMessage(`$(copy) 已复制终端上下文 · 回到 Chat 按 Ctrl+V 插入 · ${lines} ${lines === 1 ? 'line' : 'lines'}`, 3500);
  };

  const attachTerminalSelectionToChat = async () => {
    const terminalContext = await captureTerminalContext();
    if (!terminalContext) return;
    const lines = clipboardLineCount(terminalContext.content);
    provider.view?.show?.(true);
    try { await vscode.commands.executeCommand('egoagent.dagChat.focus'); } catch {}
    provider.view?.webview.postMessage({ type: 'externalContextsAttached', contexts: [terminalContext] });
    vscode.window.setStatusBarMessage(`$(check) 已将终端选区加入 EgoAgent 对话 · ${lines} ${lines === 1 ? 'line' : 'lines'}`, 2500);
  };

  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 80);
  completionProvider.onStateChanged = (state) => {
    const enabled = completionProvider.enabled && vscode.workspace.getConfiguration('egoagent').get('localCompletion.enabled', true);
    const labels = { ready: 'Tab', loading: '补全中', suggested: 'Tab 接受', local: '本地词补全', timeout: '补全超时', unavailable: '模型不可用', excluded: '已跳过敏感内容' };
    status.text = `${!enabled ? '$(circle-slash)' : state === 'loading' ? '$(loading~spin)' : '$(sparkle)'} EgoAgent ${enabled ? labels[state] || 'Tab' : '补全暂停'}`;
    status.tooltip = `点击${enabled ? '暂停' : '开启'}补全。Tab 接受 · Esc 取消 · Alt+\\ 手动触发 · Ctrl+Right 接受下一词。${state === 'timeout' ? '可在 EgoAgent 设置调整 Completion Timeout。' : ''}`;
  };
  completionProvider.setState('ready');
  status.command = 'egoagent.toggleLocalCompletion';
  status.show();
  const reviewStatus = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 79);
  reviewStatus.command = 'egoagent.reviewChanges';
  const updateReviewStatus = () => {
    const local = reviewManager.proposals.reduce((count, proposal) => count + proposal.hunks.filter((hunk) => hunk.status === 'pending').length, 0);
    const backend = reviewManager.backendChanges.reduce((count, change) => count + (change.hunks || []).filter((hunk) => hunk.status === 'pending').length, 0);
    const pending = local + backend;
    reviewStatus.text = `$(diff) ${pending} Agent 改动`;
    reviewStatus.tooltip = '打开逐段 Agent 改动审阅；文件已写入并同步到源代码管理';
    if (pending) reviewStatus.show(); else reviewStatus.hide();
  };
  reviewManager.onStateChanged = () => { provider?.postSnapshot(); updateReviewStatus(); updateWorkbenchStatusSurface(); };
  updateReviewStatus();

  context.subscriptions.push(
    status,
    reviewStatus,
    // Recreate the Webview whenever the Chat view is reopened. Keeping the
    // iframe alive made old cached scripts survive extension upgrades and was
    // the reason polling fixes did not reach an already-open Void window.
    vscode.window.registerWebviewViewProvider('egoagent.dagChat', provider, { webviewOptions: { retainContextWhenHidden: false } }),
    vscode.window.onDidChangeActiveTextEditor(() => {
      void provider.sendEditorContext();
      void provider.refreshBackendReviewState();
    }),
    vscode.workspace.onDidChangeWorkspaceFolders(() => {
      void provider.sendEditorContext();
      void provider.refreshBackendReviewState();
      void refreshWorkbenchRuntimeStatus();
      if (workbenchPanel) {
        const restored = context.workspaceState.get(workbenchWorkspaceKey(), 'home');
        workbenchTab = WORKBENCH_TABS.has(restored) ? restored : 'home';
        void renderWorkbench(workbenchPanel, workbenchTab);
      }
    }),
    vscode.languages.registerInlineCompletionItemProvider(DOCUMENT_SELECTOR, completionProvider),
    vscode.commands.registerCommand('egoagent.openWorkbench', () => openWorkbench()),
    vscode.commands.registerCommand('egoagent.openHarnessBuilder', () => openWorkbench('harness')),
    vscode.commands.registerCommand('egoagent.openEvaluation', () => openWorkbench('tasks')),
    vscode.commands.registerCommand('egoagent.openEvolution', () => openWorkbench('evolution')),
    vscode.commands.registerCommand('egoagent.sendFileToEvaluation', (uri, selectedUris) => sendIdeContextToEvaluation(uri, selectedUris, false)),
    vscode.commands.registerCommand('egoagent.sendSelectionToEvaluation', () => sendIdeContextToEvaluation(vscode.window.activeTextEditor?.document?.uri, undefined, true)),
    vscode.commands.registerCommand('egoagent.attachFileToChat', (uri, selectedUris) => provider.attachResourcesToChat(uri, selectedUris, false)),
    vscode.commands.registerCommand('egoagent.attachSelectionToChat', () => provider.attachResourcesToChat(vscode.window.activeTextEditor?.document?.uri, undefined, true)),
    // Compatibility for older keybindings and restored Void workspace state.
    vscode.commands.registerCommand('egoagent.openStudio', () => openWorkbench('home')),
    vscode.commands.registerCommand('egoagent.refreshDagChat', () => provider.refresh()),
    vscode.commands.registerCommand('egoagent.mockAgentEdit', runMockEdit),
    vscode.commands.registerCommand('egoagent.inlineEdit', runInlineEdit),
    vscode.commands.registerCommand('egoagent.localReview', runLocalReview),
    vscode.commands.registerCommand('egoagent.codeMap', openCodeMap),
    vscode.commands.registerCommand('egoagent.preview', previewApplication),
    vscode.commands.registerCommand('egoagent.generateCommitMessage', () => generateCommitMessage(aiClient)),
    vscode.commands.registerCommand('egoagent.runTerminalCommand', runTerminalCommand),
    vscode.commands.registerCommand('egoagent.copyEditorContext', copyEditorContext),
    vscode.commands.registerCommand('egoagent.copyTerminalContext', copyTerminalContext),
    vscode.commands.registerCommand('egoagent.attachTerminalSelectionToChat', attachTerminalSelectionToChat),
    vscode.commands.registerCommand('egoagent.reviewChanges', () => provider.revealChanges()),
    vscode.commands.registerCommand('egoagent.acceptHunk', (proposalId, hunkId) => reviewManager.updateHunk(proposalId, hunkId, 'accepted')),
    vscode.commands.registerCommand('egoagent.rejectHunk', (proposalId, hunkId) => reviewManager.updateHunk(proposalId, hunkId, 'rejected')),
    vscode.commands.registerCommand('egoagent.undoHunkDecision', (proposalId, hunkId) => reviewManager.undoHunk(proposalId, hunkId)),
    vscode.commands.registerCommand('egoagent.acceptBackendHunk', (id, hunkId) => provider.applyBackendChange({ action: 'accept', id, hunkId })),
    vscode.commands.registerCommand('egoagent.rejectBackendHunk', (id, hunkId) => provider.applyBackendChange({ action: 'reject', id, hunkId })),
    vscode.commands.registerCommand('egoagent.openBackendDiff', (id, hunkId) => reviewManager.openBackendDiff(id, hunkId)),
    vscode.commands.registerCommand('egoagent.undoBackendDecision', (id, hunkId) => provider.applyBackendChange({ action: 'undo', id, hunkId })),
    vscode.commands.registerCommand('egoagent.undoLatestReviewDecision', () => provider.undoLatestReviewDecision()),
    vscode.commands.registerCommand('egoagent.nextPendingChange', () => reviewManager.navigatePending(1)),
    vscode.commands.registerCommand('egoagent.previousPendingChange', () => reviewManager.navigatePending(-1)),
    vscode.commands.registerCommand('egoagent.acceptCurrentFileChanges', () => provider.applyAllInActiveFile('accept')),
    vscode.commands.registerCommand('egoagent.rejectCurrentFileChanges', () => provider.applyAllInActiveFile('reject')),
    vscode.commands.registerCommand('egoagent.acceptAllChanges', () => provider.applyAllChanges('accept')),
    vscode.commands.registerCommand('egoagent.rejectAllChanges', () => provider.applyAllChanges('reject')),
    vscode.commands.registerCommand('egoagent.openProposalDiff', (proposalId) => reviewManager.openDiff(proposalId)),
    vscode.commands.registerCommand('egoagent.completionAccepted', (key) => completionProvider.accept(key)),
    vscode.commands.registerCommand('egoagent.triggerCompletion', () => vscode.commands.executeCommand('editor.action.inlineSuggest.trigger')),
    vscode.commands.registerCommand('egoagent.dismissCompletion', async () => {
      completionProvider.reject();
      await vscode.commands.executeCommand('editor.action.inlineSuggest.hide');
    }),
    vscode.commands.registerCommand('egoagent.predictNextEdit', () => nextEditPredictor.predict()),
    vscode.commands.registerCommand('egoagent.previewNextEdit', () => nextEditPredictor.preview()),
    vscode.commands.registerCommand('egoagent.dismissNextEdit', () => nextEditPredictor.dismiss()),
    vscode.commands.registerCommand('egoagent.toggleLocalCompletion', async () => {
      await completionProvider.toggle();
      provider.postSnapshot();
    }),
  );
}

function deactivate() {}

module.exports = { activate, deactivate, splitLines, buildMockHunks, buildInlineHunks, extractLocalSymbols };
