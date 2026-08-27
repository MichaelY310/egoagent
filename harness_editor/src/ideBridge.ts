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

const pendingRequests = new Map<string, { resolve: (value: unknown) => void; reject: (reason: Error) => void; timer: number }>();

window.addEventListener('message', (event) => {
  const message = event.data || {};
  if (message.source !== 'egoagent-shell' || message.type !== 'request-result') return;
  const pending = pendingRequests.get(String(message.requestId || ''));
  if (!pending) return;
  window.clearTimeout(pending.timer);
  pendingRequests.delete(String(message.requestId));
  if (message.ok) pending.resolve(message.value ?? message.path ?? true);
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

function requestFromIde<T>(type: string, payload: Record<string, unknown>, timeout = 30000): Promise<T | null> {
  if (!vscodeApi && window.parent === window) return Promise.resolve(null);
  const requestId = `${type}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      pendingRequests.delete(requestId);
      reject(new Error('Void did not acknowledge the IDE operation'));
    }, timeout);
    pendingRequests.set(requestId, { resolve: (value) => resolve(value as T), reject, timer });
    postToIde(type, { requestId, ...payload });
  });
}

export function pickProjectFolderFromIde(title: string, openLabel: string): Promise<string | null> {
  return requestFromIde<string>('pick-project-folder', { title, openLabel });
}

export function reviewAgentChangeInIde(action: 'accept' | 'reject' | 'undo', id: string, hunkId?: string, confirmDelete = false): Promise<boolean> {
  return requestFromIde<boolean>('review-change', { action, id, hunkId, confirmDelete }, 15000).then(Boolean);
}
