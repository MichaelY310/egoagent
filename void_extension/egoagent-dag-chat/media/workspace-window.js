/* A renderer-owned opener: unlike extension-host openExternal, button clicks
 * here retain browser user activation. Only local workspace navigation is allowed. */
function createWorkspaceWindowOpener(host) {
  function workspaceUrl(value) {
    const url = new URL(value);
    if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)
        || url.username || url.password || url.hash || url.search
        || !(url.pathname === '/' || /^\/api\/remote\/open\/[a-f0-9]{16}$/.test(url.pathname))) {
      throw new Error('Invalid EgoAgent workspace URL');
    }
    return url.href;
  }
  let pending = null;
  return function openWorkspace(value, label = '远程工作区') {
    const url = workspaceUrl(value);
    // WebView2's native NewWindowRequested handler already opens an IDE window.
    if (host.chrome?.webview) return Promise.resolve('external');
    if (pending) pending();
    return new Promise(resolve => {
      const document = host.document;
      const previousFocus = document.activeElement;
      const backdrop = document.createElement('div');
      backdrop.className = 'egoagent-workspace-open-backdrop';
      backdrop.style.cssText = 'position:fixed;inset:0;z-index:100000;display:grid;place-items:center;background:#0006';
      const panel = document.createElement('section');
      panel.setAttribute('role', 'dialog');
      panel.setAttribute('aria-modal', 'true');
      panel.setAttribute('aria-label', '打开 EgoAgent 工作区');
      panel.style.cssText = 'width:min(540px,85vw);padding:24px;border:1px solid var(--vscode-widget-border,#888);border-radius:8px;background:var(--vscode-editorWidget-background,#fff);color:var(--vscode-editor-foreground,#222);box-shadow:0 12px 48px #0005;font:14px/1.6 sans-serif';
      const heading = document.createElement('h2');
      heading.textContent = '工作区已就绪';
      const name = document.createElement('p');
      name.textContent = String(label);
      const detail = document.createElement('p');
      detail.textContent = '选择打开位置。新页面会保留本机项目；在当前页面打开时，请先保存未保存的文件。';
      const address = document.createElement('input');
      address.readOnly = true;
      address.value = url;
      address.setAttribute('aria-label', '工作区地址（可复制）');
      address.style.cssText = 'box-sizing:border-box;width:100%;padding:6px;color:inherit;background:transparent;border:1px solid #888';
      const status = document.createElement('p');
      status.setAttribute('role', 'status');
      const actions = document.createElement('div');
      actions.style.cssText = 'display:flex;flex-wrap:wrap;gap:10px;justify-content:flex-end;margin-top:18px';
      function finish(result) {
        pending = null;
        backdrop.remove();
        previousFocus?.focus();
        resolve(result);
      }
      pending = () => finish('cancelled');
      function button(text, action) {
        const control = document.createElement('button');
        control.textContent = text;
        control.style.cssText = 'cursor:pointer;padding:7px 12px;border-radius:4px;border:1px solid var(--vscode-button-border,#888);background:var(--vscode-button-background,#006bb3);color:var(--vscode-button-foreground,#fff)';
        control.addEventListener('click', action);
        actions.append(control);
        return control;
      }
      button('暂不打开', () => finish('cancelled'));
      button('在当前页面打开', () => { host.location.assign(url); finish('navigating'); });
      const open = button('在新页面打开', () => {
        // Use the real URL: embedded browser hosts dispatch NewWindowRequested
        // by URL and may discard an about:blank placeholder window altogether.
        const tab = host.open(url, '_blank');
        if (!tab) {
          status.textContent = '浏览器阻止了新页面。请选择“在当前页面打开”，或复制上方地址打开。';
          return;
        }
        tab.opener = null;
        finish('opened');
      });
      panel.append(heading, name, detail, address, status, actions);
      backdrop.append(panel);
      document.body.append(backdrop);
      backdrop.addEventListener('keydown', event => {
        if (event.key === 'Escape') { event.preventDefault(); finish('cancelled'); }
        if (event.key === 'Tab') {
          if (event.shiftKey && document.activeElement === address) { event.preventDefault(); open.focus(); }
          else if (!event.shiftKey && document.activeElement === open) { event.preventDefault(); address.focus(); }
        }
      });
      open.focus();
    });
  };
}

if (typeof module !== 'undefined') module.exports = { createWorkspaceWindowOpener };
