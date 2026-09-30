'use strict';

// Native inline-completion items own rendering, acceptance and undo. This
// module only retrieves a bounded suggestion; it never edits a document.
const { createHash } = require('crypto');
const MAX_DOCUMENT = 500000;
const DEFAULT_EXCLUDES = ['**/.env*', '**/*secret*', '**/*secret*/**', '**/*credential*', '**/*credential*/**', '**/*.pem', '**/*.key', '**/id_rsa*', '**/id_ed25519*', '**/node_modules/**', '**/.git/**', '**/dist/**', '**/package-lock.json', '**/yarn.lock'];

function matchesGlob(path, glob) {
  const pattern = String(glob).split(/(\*\*\/|\*\*|\*|\?)/).map(part => {
    if (part === '**/') return '(?:.*/)?';
    if (part === '**') return '.*';
    if (part === '*') return '[^/]*';
    if (part === '?') return '[^/]';
    return part.replace(/[.+^${}()|[\]\\]/g, '\\$&');
  }).join('');
  return new RegExp(`^${pattern}$`, 'i').test(String(path).replaceAll('\\', '/'));
}

function containsCredential(text) {
  return /-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----|\bsk-[a-zA-Z0-9_-]{20,}|\b(?:api[_-]?key|access[_-]?token|password)\s*[:=]\s*["'][^"'\s]{12,}["']/i.test(text);
}

function normalizeSuggestion(raw, prefix, suffix) {
  if (typeof raw !== 'string') return '';
  let text = raw.replaceAll('\u0000', '').replace(/\r\n/g, '\n');
  text = text.replace(/^```[^\n]*\n/, '').replace(/\n?```\s*$/, '');
  text = text.replace(/<\|(?:fim_prefix|fim_suffix|fim_middle|endoftext|eot_id)\|>/g, '');
  const tail = prefix.slice(-500);
  if (tail.trim() && text.startsWith(tail)) text = text.slice(tail.length);
  // Chat-based providers often repeat indentation on the first line although
  // those spaces already exist before the cursor. Strip only that overlap;
  // subsequent lines and any additional block indentation must stay intact.
  const linePrefix = prefix.slice(prefix.lastIndexOf('\n') + 1);
  if (/^[\t ]+$/.test(linePrefix) && text.startsWith(linePrefix)) text = text.slice(linePrefix.length);
  // Do not strip arbitrary one-character overlaps (e.g. completing 'item'
  // before a suffix starting with 'm'). Closing brackets are safe to dedupe.
  for (let size = Math.min(text.length, suffix.length, 500); size > 0; size--) {
    const overlap = suffix.slice(0, size);
    if (text.endsWith(overlap) && ((size >= 3 && overlap.trim()) || /^[)\]}]+$/.test(overlap))) {
      text = text.slice(0, -size);
      break;
    }
  }
  return text.trim() ? text.slice(0, 6000) : '';
}

function localWord(text, before, suffix) {
  if (/^[\w$]/.test(suffix)) return '';
  const word = /[A-Za-z_$][\w$]{2,}$/.exec(before)?.[0];
  if (!word) return '';
  const words = text.match(/[A-Za-z_$][\w$]*/g) || [];
  const candidate = words.find(item => item.length > word.length && item.startsWith(word));
  return candidate ? candidate.slice(word.length) : '';
}

function cancellableDelay(ms, token) {
  return new Promise(resolve => {
    let subscription;
    const finish = value => { clearTimeout(timer); subscription?.dispose(); resolve(value); };
    const timer = setTimeout(() => finish(true), ms);
    subscription = token.onCancellationRequested(() => finish(false));
    if (token.isCancellationRequested) finish(false);
  });
}

function createCompletionProvider(vscode, displayPath) {
  return class CompletionProvider {
    constructor(context, metrics, aiClient, onMetricsChanged) {
      Object.assign(this, { context, metrics, aiClient, onMetricsChanged });
      this.enabled = context.globalState.get('egoagent.localCompletionEnabled', true);
      this.cache = new Map();
      this.lastSuggestion = undefined;
      this.state = 'ready';
      this.onStateChanged = undefined;
      context.subscriptions.push(this,
        vscode.workspace.onDidChangeTextDocument(event => {
          if (event.contentChanges.length && this.active?.uri === event.document.uri.toString()) this.cancel();
        }),
        vscode.workspace.onDidChangeConfiguration(event => {
          if (event.affectsConfiguration('egoagent')) { this.cancel(); this.cache.clear(); this.lastSuggestion = undefined; }
        }),
        vscode.window.onDidChangeTextEditorSelection(() => this.cancel()),
        vscode.window.onDidChangeActiveTextEditor(() => this.cancel()),
      );
    }

    config(document) { return vscode.workspace.getConfiguration('egoagent', document?.uri); }
    setState(state) { this.state = state; this.onStateChanged?.(state); }
    cancel() { this.active?.source.cancel(); this.active = undefined; this.setState('ready'); }
    dispose() { this.cancel(); this.cache.clear(); }
    async toggle() {
      this.enabled = !this.enabled;
      this.cancel(); this.lastSuggestion = undefined;
      await this.context.globalState.update('egoagent.localCompletionEnabled', this.enabled);
      await vscode.commands.executeCommand('editor.action.inlineSuggest.hide');
      this.setState(this.enabled ? 'ready' : 'paused');
      return this.enabled;
    }
    accept(key) {
      if (!this.lastSuggestion || (key && key !== this.lastSuggestion.key)) return false;
      this.metrics.bump('completionsAccepted'); this.onMetricsChanged?.();
      this.lastSuggestion = undefined; this.setState('ready'); return true;
    }
    reject(key) {
      this.cancel();
      if (!this.lastSuggestion || (key && key !== this.lastSuggestion.key)) return false;
      this.dismissedKey = this.lastSuggestion.cacheKey;
      this.metrics.bump('completionsRejected'); this.onMetricsChanged?.();
      this.lastSuggestion = undefined; return true;
    }
    eligible(document, config) {
      const scheme = document.uri.scheme;
      if (!['file', 'vscode-remote', 'untitled'].includes(scheme) || vscode.workspace.isTrusted === false) return false;
      const path = document.uri.path || document.fileName || '';
      return ![...DEFAULT_EXCLUDES, ...config.get('localCompletion.exclude', [])].some(glob => matchesGlob(path, glob));
    }
    extraContext(document, text, config) {
      const folder = vscode.workspace.getWorkspaceFolder(document.uri)?.uri.toString();
      const openFiles = config.get('localCompletion.includeOpenFiles', false) && folder
        ? (vscode.window.visibleTextEditors || []).map(e => e.document).filter(doc =>
          doc.uri.toString() !== document.uri.toString() && this.eligible(doc, this.config(doc)) &&
          vscode.workspace.getWorkspaceFolder(doc.uri)?.uri.toString() === folder,
        ).slice(0, 2).flatMap(doc => {
          const excerpt = doc.getText();
          return excerpt.length > MAX_DOCUMENT || containsCredential(excerpt) ? [] : [{ path: displayPath(doc.uri), language: doc.languageId, excerpt: excerpt.slice(0, 1500) }];
        }) : [];
      return { imports: text.split(/\r?\n/).filter(line => /^\s*(?:import\b|from\s+\S+\s+import\b)/.test(line)).slice(0, 20).map(line => line.slice(0, 300)), open_files: openFiles };
    }
    cacheGet(key) {
      const item = this.cache.get(key);
      if (!item || Date.now() - item.at > 60000) { this.cache.delete(key); return undefined; }
      this.cache.delete(key); this.cache.set(key, item); return item;
    }
    cacheSet(key, item) {
      this.cache.set(key, { ...item, at: Date.now() });
      while (this.cache.size > 64) this.cache.delete(this.cache.keys().next().value);
    }
    async provideInlineCompletionItems(document, position, context, externalToken) {
      this.cancel();
      const config = this.config(document);
      if (!this.enabled || !config.get('localCompletion.enabled', true) || !this.eligible(document, config) || externalToken?.isCancellationRequested) return [];
      // Let the language server's completion widget/snippet choices take priority.
      if (context?.selectedCompletionInfo) return [];
      const editor = vscode.window.activeTextEditor;
      if (editor?.document === document && (editor.selections?.length > 1 || editor.selection?.isEmpty === false)) return [];
      const text = document.getText();
      if (text.length > MAX_DOCUMENT || containsCredential(text)) { this.setState('excluded'); return []; }
      const offset = document.offsetAt(position);
      const prefix = text.slice(Math.max(0, offset - 6000), offset);
      const suffix = text.slice(offset, offset + 2000);
      const before = document.lineAt(position.line).text.slice(0, position.character);
      if (!prefix.trim()) return [];
      const extra = this.extraContext(document, text, config);
      const scope = `${this.aiClient.backendUrl}|${document.uri}|${document.languageId}|${JSON.stringify(extra)}`;
      const cacheKey = createHash('sha256').update(`${scope}|${prefix}|${suffix}`).digest('hex');
      const explicit = context?.triggerKind === vscode.InlineCompletionTriggerKind.Invoke;
      if (this.dismissedKey === cacheKey && !explicit) return [];
      if (explicit) this.dismissedKey = undefined;
      let cached = this.cacheGet(cacheKey);
      const previous = this.lastSuggestion;
      // Typing the start of a visible suggestion should reuse its remainder.
      if (!cached && previous?.scope === scope && Date.now() - previous.at < 60000 && previous.suffix === suffix && prefix.startsWith(previous.prefix)) {
        const typed = prefix.slice(previous.prefix.length);
        if (typed && previous.text.startsWith(typed)) cached = { text: previous.text.slice(typed.length), source: previous.source };
      }
      const source = new vscode.CancellationTokenSource();
      const token = source.token;
      const subscription = externalToken?.onCancellationRequested(() => source.cancel());
      if (externalToken?.isCancellationRequested) source.cancel();
      const request = { uri: document.uri.toString(), source };
      this.active = request;
      const version = document.version;
      const started = Date.now();
      let timeout;
      let cancellation;
      try {
        let result = cached;
        if (cached) this.metrics.bump('completionCacheHits');
        if (!result) {
          if (!explicit && !(await cancellableDelay(Math.max(0, config.get('ai.completionDelayMs', 280)), token))) return [];
          if (token.isCancellationRequested) return [];
          if (this.aiClient.enabled) {
            this.setState('loading');
            const timeoutMs = Math.max(1000, config.get('ai.completionTimeoutMs', 8000));
            let timedOut = false;
            timeout = setTimeout(() => { timedOut = true; source.cancel(); }, timeoutMs);
            const cancelled = new Promise(resolve => { cancellation = token.onCancellationRequested(() => resolve(null)); });
            try {
              const data = await Promise.race([this.aiClient.request('completion', { prefix, suffix, language: document.languageId, path: displayPath(document.uri), trigger_kind: context?.triggerKind, ...extra }, timeoutMs, token), cancelled]);
              if (timedOut) { this.metrics.bump('completionTimeouts'); this.setState('timeout'); return []; }
              if (!data || token.isCancellationRequested) return [];
              result = { text: normalizeSuggestion(data.completion, prefix, suffix), source: 'model' };
            } catch {
              if (token.isCancellationRequested) return [];
              this.metrics.bump('completionErrors'); this.setState('unavailable');
            } finally { clearTimeout(timeout); cancellation?.dispose(); }
          }
          if (!result) result = { text: config.get('localCompletion.localWordFallback', true) ? localWord(text, before, suffix) : '', source: 'local' };
        }
        if (token.isCancellationRequested || this.active !== request || document.version !== version) return [];
        // A model declining to complete is a valid cached answer, not a cue to invent code.
        this.cacheSet(cacheKey, result);
        if (!result.text) { if (this.state === 'loading') this.setState('ready'); return []; }
        const key = `${cacheKey}:${result.text}`;
        if (this.lastSuggestion?.key !== key) { this.metrics.bump('completionsOffered'); this.onMetricsChanged?.(); }
        this.lastSuggestion = { ...result, key, cacheKey, prefix, suffix, scope, uri: request.uri, at: Date.now() };
        this.metrics.bump('completionLatencyTotalMs', Date.now() - started); this.metrics.bump('completionLatencySamples');
        this.setState(result.source === 'local' ? 'local' : 'suggested');
        const item = new vscode.InlineCompletionItem(result.text, new vscode.Range(position, position));
        item.command = { command: 'egoagent.completionAccepted', title: 'Accept completion', arguments: [key] };
        return [item];
      } finally {
        clearTimeout(timeout); cancellation?.dispose(); subscription?.dispose(); source.dispose();
        if (this.active === request) {
          this.active = undefined;
          if (this.state === 'loading') this.setState('ready');
        }
      }
    }
  };
}

module.exports = { createCompletionProvider, normalizeSuggestion, localWord, matchesGlob, containsCredential };
