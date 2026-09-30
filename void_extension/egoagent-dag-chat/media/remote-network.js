// Runs only inside the Chat/Workbench webview. Never attach the credential to
// arbitrary URLs: skills/previews/external resources are different origins.
(() => {
  const config = window.__EGOAGENT_WORKBENCH__ || {};
  const token = config.accessToken || document.body?.dataset.apiToken;
  const api = config.apiBase || document.body?.dataset.api;
  const ws = config.wsBase || document.body?.dataset.ws;
  if (!token || !api || !ws) return;
  const origin = new URL(api).origin;
  const nativeFetch = window.fetch.bind(window);
  window.fetch = (input, options = {}) => {
    if (new URL(typeof input === 'string' ? input : input.url || String(input), location.href).origin !== origin) {
      return nativeFetch(input, options);
    }
    const headers = new Headers(options.headers || (input instanceof Request ? input.headers : undefined));
    headers.set('X-EgoAgent-Remote-Token', token);
    return nativeFetch(input, { ...options, headers });
  };
  const NativeWebSocket = window.WebSocket;
  window.WebSocket = class extends NativeWebSocket {
    constructor(url, protocols) {
      const values = typeof protocols === 'string' ? [protocols] : protocols || [];
      super(url, new URL(url).origin === new URL(ws).origin ? [...values, 'egoagent-token.' + token] : values);
    }
  };
})();
