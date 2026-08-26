export type IdeContextItem = {
  kind: 'file' | 'selection';
  path: string;
  relativePath?: string;
  language?: string;
  startLine?: number;
  endLine?: number;
  content: string;
};

declare function acquireVsCodeApi(): { postMessage: (message: unknown) => void };
const vscodeApi = typeof acquireVsCodeApi === 'function' ? acquireVsCodeApi() : null;

const pendingRequests = new Map<string, { resolve: (value: boolean) => void; reject: (reason: Error) => void; timer: number }>();

window.addEventListener('message', (event) => {
  const message = event.data || {};
  if (message.source !== 'egoagent-shell' || message.type !== 'request-result') return;
  const pending = pendingRequests.get(String(message.requestId || ''));
  if (!pending) return;
  window.clearTimeout(pending.timer);
  pendingRequests.delete(String(message.requestId));
  if (message.ok) pending.resolve(true);
  else pending.reject(new Error(String(message.error || 'IDE operation failed')));
});

export function postToIde(type: string, payload: Record<string, unknown> = {}): boolean {
  if (vscodeApi) {
    vscodeApi.postMessage({ source: 'egoagent-workbench', type, ...payload });
    return true;
  }
  if (window.parent === window) return false;
  window.parent.postMessage({ source: 'egoagent-workbench', type, ...payload }, '*');
  return true;
}

export function openFileInIde(path: string, line = 1, endLine?: number): boolean {
  if (!path) return false;
  return postToIde('open-file', { path, line, endLine });
}

export function openWorkspaceInIde(path: string, newWindow = true): boolean {
  if (!path) return false;
  return postToIde('open-workspace', { path, newWindow });
}

export function revealAgentChangesInIde(): boolean {
  return postToIde('review-changes');
}

export function reviewAgentChangeInIde(action: 'accept' | 'reject' | 'undo', id: string, hunkId?: string, confirmDelete = false): Promise<boolean> {
  if (!vscodeApi && window.parent === window) return Promise.resolve(false);
  const requestId = `review-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      pendingRequests.delete(requestId);
      reject(new Error('Void did not acknowledge the change review operation'));
    }, 15000);
    pendingRequests.set(requestId, { resolve, reject, timer });
    postToIde('review-change', { requestId, action, id, hunkId, confirmDelete });
  });
}
