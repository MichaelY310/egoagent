const query = new URLSearchParams(window.location.search);
const bootstrap = window.__EGOAGENT_WORKBENCH__ || {};

declare global {
  interface Window {
    __EGOAGENT_WORKBENCH__?: {
      workspace?: string;
      apiBase?: string;
      wsBase?: string;
      tab?: string;
    };
  }
}

function trimTrailingSlash(value: string): string {
  return value.replace(/\/+$/, '');
}

export const WORKSPACE = bootstrap.workspace || query.get('workspace') || '';
export const API_BASE = trimTrailingSlash(
  bootstrap.apiBase || query.get('apiBase') || `http://${window.location.hostname}:8765`,
);
export const WS_BASE = trimTrailingSlash(
  bootstrap.wsBase || query.get('wsBase') || API_BASE.replace(/^http/i, 'ws').replace(/:8765$/, ':8766'),
);
export const INITIAL_TAB = bootstrap.tab || query.get('tab') || '';
export const EMBEDDED_IN_IDE = Boolean(window.__EGOAGENT_WORKBENCH__) || query.get('embed') === '1';

export function canonicalWorkspace(value: unknown): string {
  let normalized = String(value || '').trim().replace(/\\/g, '/');
  normalized = normalized.replace(/^\/([A-Za-z]:\/)/, '$1').replace(/\/+$/, '');
  return /^[A-Za-z]:\//.test(normalized) ? normalized.toLowerCase() : normalized;
}

export function isCurrentWorkspace(value: unknown): boolean {
  const expected = canonicalWorkspace(WORKSPACE);
  return !expected || canonicalWorkspace(value) === expected;
}
