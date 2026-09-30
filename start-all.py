#!/usr/bin/env python3
"""Single-port proxy: Void IDE + EgoAgent API on one port. Stdlib only.
Installs the native EgoAgent DAG Chat extension and starts missing services.
Supports SSE streaming passthrough for /v1/chat/completions.
Supports WebSocket tunneling for Void IDE remote connections."""
import argparse, os, http.server, urllib.request, urllib.error, socketserver, http.client, socket, threading, shutil, subprocess, sys, time
import contextlib, hmac
from pathlib import Path

from runtime_endpoints import runtime_ports
_ports = runtime_ports()
VOID_PORT = _ports['VOID']
BACKEND_PORT = _ports['BACKEND']
LISTEN_PORT = _ports['LISTEN']
LISTEN_HOST = os.environ.get('EGOAGENT_HOST', '127.0.0.1')
VOID_ORIGIN = f'http://127.0.0.1:{VOID_PORT}'
BACKEND_ORIGIN = f'http://127.0.0.1:{BACKEND_PORT}'

ROOT_DIR = Path(__file__).parent
from llm.env_config import load_local_env
from product_runtime import apply_product_environment
from local_api_security import is_trusted_local_origin, remote_request_authorized, remote_cookie_name

load_local_env(ROOT_DIR)
apply_product_environment(ROOT_DIR)
VOID_ROOT = Path(os.environ.get('EGOAGENT_VOID_ROOT', str(ROOT_DIR / 'void-web'))).resolve()
VOID_NODE = VOID_ROOT / ('node.exe' if os.name == 'nt' else 'node')
VOID_SERVER = VOID_ROOT / 'out' / 'server-main.js'
EXTENSION_SOURCE = ROOT_DIR / 'void_extension' / 'egoagent-dag-chat'
EXTENSION_TARGET = VOID_ROOT / 'extensions' / 'egoagent-dag-chat'
WORKBENCH_BUNDLE = VOID_ROOT / 'out' / 'vs' / 'code' / 'browser' / 'workbench' / 'workbench.js'
WORKBENCH_STYLE = VOID_ROOT / 'out' / 'vs' / 'code' / 'browser' / 'workbench' / 'workbench.css'
WEBVIEW_ENDPOINT = (
    f'http://{{{{uuid}}}}.localhost:{LISTEN_PORT}/'
    + (f'auth/{os.environ["EGOAGENT_REMOTE_TOKEN"]}/' if os.environ.get('EGOAGENT_REMOTE_TOKEN') else '')
    +
    '{{quality}}-{{commit}}/static/out/vs/workbench/contrib/webview/browser/pre/'
)
VOID_SOCKET = os.environ.get('EGOAGENT_VOID_SOCKET', '')
WORKBENCH_CACHE_KEY = 'egoagent-native-chat-v12'
WORKBENCH_DROP_BRIDGE_MARKER = '/*egoagent-resource-drop-bridge-v1*/'
WORKBENCH_FLAT_DIFF_MARKER = '/*egoagent-flat-review-diff-v2*/'
WORKBENCH_FLAT_DIFF_STYLE = r'''
/*egoagent-flat-review-diff-v2*/
/* EgoAgent reviews use GitHub-style line-level color. Monaco normally layers
   a second word/character background on top, which makes only part of a
   deleted or inserted line look darker and visually suggests another state. */
.monaco-diff-editor .char-delete,
.monaco-diff-editor .char-insert {
  background-color: transparent !important;
}
/* The extension contributes one native CodeLens per pending hunk. The runtime
   marker below turns only those EgoAgent lenses into a compact hunk toolbar;
   other extensions' CodeLens layout is left untouched. */
.monaco-diff-editor .codelens-decoration.egoagent-review-toolbar {
  width: var(--egoagent-review-width, auto) !important;
  max-width: var(--egoagent-review-width, none) !important;
  transform: translateY(calc(-1 * var(--egoagent-review-lift, 0px)));
  display: flex !important;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  overflow: visible !important;
  pointer-events: none;
  z-index: 80;
}
.monaco-diff-editor .codelens-decoration.egoagent-review-toolbar > span,
.monaco-diff-editor .codelens-decoration.egoagent-review-toolbar > a:first-of-type {
  display: none !important;
}
.monaco-diff-editor .codelens-decoration.egoagent-review-toolbar > a:nth-of-type(n+2) {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 1px 9px;
  border: 1px solid var(--vscode-button-border, var(--vscode-contrastBorder, transparent));
  border-radius: 4px;
  background: var(--vscode-editorWidget-background, #252526);
  box-shadow: 0 1px 3px #0005;
  color: var(--vscode-editorWidget-foreground, var(--vscode-editor-foreground));
  font-size: 12px;
  font-weight: 600;
  line-height: 18px;
  text-decoration: none;
  pointer-events: auto;
}
.monaco-diff-editor .codelens-decoration.egoagent-review-toolbar > a:nth-of-type(2) {
  color: var(--vscode-testing-iconPassed, #3fb950);
}
.monaco-diff-editor .codelens-decoration.egoagent-review-toolbar > a:nth-of-type(3) {
  color: var(--vscode-testing-iconFailed, #f85149);
}
.monaco-diff-editor .codelens-decoration.egoagent-review-toolbar > a:nth-of-type(n+2):hover {
  background: var(--vscode-toolbar-hoverBackground, #5a5d5e50);
}
'''
WORKBENCH_DROP_BRIDGE = r'''
;/*egoagent-resource-drop-bridge-v1*/(()=>{
  if(window.__egoagentResourceDropBridge)return;
  window.__egoagentResourceDropBridge=true;
  const acceptedTypes=new Set(['resourceurls','codeeditors','codefiles','application/vnd.code.uri-list','text/uri-list','text/plain']);
  let target=null,activeTransfer=null,lastPoint=null,capturingTransfer=null;
  const nativeSetData=globalThis.DataTransfer?.prototype?.setData;
  if(nativeSetData){
    // The Explorer writes CodeFiles/ResourceURLs during its target-phase
    // dragstart listener. Capture that exact standards-based write because
    // Chromium protects getData() again as soon as dragstart dispatch ends.
    DataTransfer.prototype.setData=function(type,value){
      const result=nativeSetData.call(this,type,value);
      if(this===capturingTransfer&&acceptedTypes.has(String(type).toLowerCase())){
        activeTransfer=activeTransfer||{};
        activeTransfer[type]=String(value||'').slice(0,131072);
      }
      return result;
    };
  }
  const targetFrame=()=>{
    if(!target?.origin)return null;
    return [...document.querySelectorAll('iframe')].find(frame=>{
      try{return new URL(frame.src,location.href).origin===target.origin}catch{return false}
    })||null;
  };
  const insideTarget=(x,y)=>{
    const frame=targetFrame();
    if(!frame||!Number.isFinite(x)||!Number.isFinite(y))return false;
    const rect=frame.getBoundingClientRect();
    return rect.width>180&&rect.height>120&&x>=rect.left&&x<=rect.right&&y>=rect.top&&y<=rect.bottom;
  };
  const snapshot=transfer=>{
    const result={};
    for(const type of Array.from(transfer?.types||[])){
      if(!acceptedTypes.has(String(type).toLowerCase()))continue;
      try{result[type]=String(transfer.getData(type)||'').slice(0,131072)}catch{}
    }
    const resourceValue=Object.entries(result).some(([type,value])=>(type!=='text/plain'&&value)||/^(?:file|vscode-remote):\//im.test(value)||/^(?:[A-Za-z]:[\\/]|\/(?!\/)|\\\\)/m.test(value));
    return resourceValue?result:null;
  };
  addEventListener('message',event=>{
    if(event.data?.type!=='egoagent-drop-target-register'||!event.ports?.[0])return;
    const frame=[...document.querySelectorAll('iframe')].find(item=>{
      try{return new URL(item.src,location.href).origin===event.origin}catch{return false}
    });
    if(!frame)return;
    const rect=frame.getBoundingClientRect();
    if(rect.width<180||rect.height<120)return;
    try{target?.port?.close()}catch{}
    target={origin:event.origin,port:event.ports[0]};
    target.port.start?.();
  },true);
  document.addEventListener('dragstart',event=>{
    // Explorer writes ResourceURLs/CodeEditors in its own dragstart handler and
    // may stop propagation.  Keep the live DataTransfer from the capture phase,
    // then read it after all handlers for this event have populated it.
    const transfer=event.dataTransfer;
    capturingTransfer=transfer;
    activeTransfer=null;
    lastPoint={x:event.clientX,y:event.clientY};
    const capture=()=>{
      const live=snapshot(transfer);
      if(live)activeTransfer=live;
    };
    queueMicrotask(capture);
    setTimeout(capture,0);
  },true);
  document.addEventListener('dragover',event=>{
    const live=snapshot(event.dataTransfer);
    if(live)activeTransfer=live;
    const hasResourceType=Array.from(event.dataTransfer?.types||[]).some(type=>acceptedTypes.has(String(type).toLowerCase()));
    if(activeTransfer||hasResourceType)lastPoint={x:event.clientX,y:event.clientY};
    if(target?.port&&insideTarget(event.clientX,event.clientY)){
      // Declaring the iframe as a copy drop target removes Chromium's
      // misleading forbidden cursor while preserving Explorer's source item.
      event.preventDefault();
      if(event.dataTransfer)event.dataTransfer.dropEffect='copy';
    }
  },true);
  const finish=event=>{
    const live=snapshot(event.dataTransfer);
    if(live)activeTransfer=live;
    if(!activeTransfer)return;
    const point=Number.isFinite(event.clientX)&&Number.isFinite(event.clientY)&&event.clientX+event.clientY>0
      ?{x:event.clientX,y:event.clientY}:lastPoint;
    if(target?.port&&point&&insideTarget(point.x,point.y)){
      try{target.port.postMessage({type:'egoagent-workbench-resource-drop',transfer:activeTransfer})}catch{}
    }
    activeTransfer=null;lastPoint=null;capturingTransfer=null;
  };
  document.addEventListener('drop',finish,true);
  document.addEventListener('dragend',finish,true);
  const enhanceReviewToolbar=toolbar=>{
    const text=String(toolbar?.textContent||'');
    if(!text.includes('Review Diff')||!text.includes('Accept')||!text.includes('Refuse'))return;
    toolbar.classList.add('egoagent-review-toolbar');
    const editor=toolbar.closest('.monaco-editor');
    const width=toolbar.style.maxWidth||`${Math.max(180,(editor?.clientWidth||260)-57)}px`;
    if(toolbar.style.getPropertyValue('--egoagent-review-width')!==width){
      toolbar.style.setProperty('--egoagent-review-width',width);
    }
    const oldCount=Number((text.match(/[−-](\d+)/)||[])[1]||0);
    const lineNode=editor?.querySelector('.view-lines');
    const lineHeight=parseFloat(lineNode?getComputedStyle(lineNode).lineHeight:'')||19;
    const lensHeight=parseFloat(editor?.parentElement?getComputedStyle(editor.parentElement).getPropertyValue('--vscode-editorCodeLens-lineHeight'):'')||16;
    const lift=oldCount>0?`${Math.round(oldCount*lineHeight+lensHeight+1)}px`:'0px';
    if(toolbar.style.getPropertyValue('--egoagent-review-lift')!==lift){
      toolbar.style.setProperty('--egoagent-review-lift',lift);
    }
  };
  const enhanceReviewToolbars=()=>document.querySelectorAll('.monaco-diff-editor .codelens-decoration').forEach(enhanceReviewToolbar);
  let reviewToolbarScanQueued=false;
  const queueReviewToolbarScan=()=>{
    if(reviewToolbarScanQueued)return;
    reviewToolbarScanQueued=true;
    requestAnimationFrame(()=>{reviewToolbarScanQueued=false;enhanceReviewToolbars()});
  };
  new MutationObserver(queueReviewToolbarScan).observe(document.documentElement,{childList:true,subtree:true,attributes:true,attributeFilter:['style']});
  addEventListener('resize',queueReviewToolbarScan,true);
  queueReviewToolbarScan();
})();
'''


def _port_is_open(port):
    try:
        with socket.create_connection(('127.0.0.1', int(port)), timeout=0.25):
            return True
    except OSError:
        return False


def _connect_void():
    if VOID_SOCKET:
        stream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        stream.settimeout(10)
        try:
            stream.connect(VOID_SOCKET)
        except BaseException:
            stream.close()
            raise
        return stream
    return socket.create_connection(('127.0.0.1', VOID_PORT), timeout=10)


def _void_is_open():
    try:
        with _connect_void():
            return True
    except OSError:
        return False


def start_backend_if_needed():
    """Make the documented two-terminal startup actually self-contained.

    Reuse an explicitly started backend, otherwise own a hidden child process
    and stop it when the unified proxy exits.
    """
    if _port_is_open(BACKEND_PORT):
        return None
    kwargs = {
        'cwd': str(ROOT_DIR / 'harness_editor'),
        'env': os.environ.copy(),
    }
    if os.name == 'nt':
        kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    process = subprocess.Popen([sys.executable, 'server.py'], **kwargs)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f'EgoAgent backend exited with code {process.returncode}')
        if _port_is_open(BACKEND_PORT):
            return process
        time.sleep(0.15)
    process.terminate()
    raise RuntimeError(f'EgoAgent backend did not listen on {BACKEND_PORT}')


def _supervise_backend(process_holder, stop_event):
    """Recover the localhost API if it exits while the unified proxy lives."""
    retry_delay = 1.0
    while not stop_event.wait(1.0):
        previous = process_holder.get('process')
        # Process liveness is authoritative for an owned backend. A TCP probe
        # can time out when several IDE windows fill the accept queue; killing
        # a live process here destroys sessions and its SSH/WSL transports.
        if previous is not None and previous.poll() is None:
            retry_delay = 1.0
            continue
        if _port_is_open(BACKEND_PORT):
            retry_delay = 1.0
            continue
        try:
            process_holder['process'] = start_backend_if_needed()
            retry_delay = 1.0
            print(f'EgoAgent backend recovered on port {BACKEND_PORT}')
        except Exception as error:
            process_holder['process'] = None
            print(f'EgoAgent backend recovery failed: {error}', file=sys.stderr)
            if stop_event.wait(retry_delay):
                return
            retry_delay = min(retry_delay * 2, 15.0)


def start_backend_supervisor(initial_process):
    process_holder = {'process': initial_process}
    stop_event = threading.Event()
    thread = threading.Thread(
        target=_supervise_backend,
        args=(process_holder, stop_event),
        name='egoagent-backend-supervisor',
        daemon=True,
    )
    thread.start()
    return process_holder, stop_event, thread


def stop_backend_supervisor(supervisor):
    if not supervisor:
        return
    process_holder, stop_event, thread = supervisor
    stop_event.set()
    thread.join(timeout=20)
    _stop_owned_process(process_holder.get('process'))


def start_void_if_needed():
    """Start the bundled Void server with stable, localhost-only authentication.

    Void otherwise creates a new connection token on every launch. The 8880
    proxy cannot preserve that changing token across WebSocket and Webview
    subdomains, which leaves the native Chat container blank after restarts.
    Disabling the token is safe here because both Void and the public proxy are
    bound to 127.0.0.1 only.
    """
    if LISTEN_HOST not in {'127.0.0.1', 'localhost'}:
        raise RuntimeError(
            'The tokenless unified Void launcher is localhost-only; '
            'set EGOAGENT_HOST=127.0.0.1'
        )
    if _void_is_open():
        return None
    if VOID_SOCKET and Path(VOID_SOCKET).exists():
        stale_socket = Path(VOID_SOCKET)
        managed_root = VOID_ROOT.parent
        if (stale_socket.parent.resolve() != managed_root.resolve()
                or not (managed_root / '.egoagent-remote').is_file()
                or not stale_socket.is_socket()):
            raise RuntimeError('Refusing to replace an unmanaged Unix socket path')
        stale_socket.unlink()  # Dead IPC endpoint only; never a regular file.
    if not VOID_SERVER.is_file():
        raise RuntimeError(f'Void server not found: {VOID_SERVER}')
    executable = str(VOID_NODE if VOID_NODE.is_file() else (shutil.which('node') or 'node'))
    kwargs = {
        'cwd': str(VOID_ROOT),
        'env': os.environ.copy(),
    }
    if os.name == 'nt':
        kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    arguments = [
        executable,
        str(VOID_SERVER),
        '--host', '127.0.0.1',
        '--without-connection-token',
        '--accept-server-license-terms',
    ]
    if VOID_SOCKET:
        arguments.extend(['--socket-path', VOID_SOCKET])
    else:
        arguments.extend(['--port', str(VOID_PORT)])
    if os.environ.get('EGOAGENT_VOID_DATA'):
        arguments.extend(['--server-data-dir', os.environ['EGOAGENT_VOID_DATA']])
    process = subprocess.Popen(arguments, **kwargs)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f'Void exited with code {process.returncode}')
        if _void_is_open():
            return process
        time.sleep(0.15)
    process.terminate()
    raise RuntimeError(f'Void did not listen on {VOID_PORT}')


def _stop_owned_process(process):
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def install_native_extension():
    """Copy the tracked extension into the downloaded Void runtime."""
    if not EXTENSION_SOURCE.exists() or not EXTENSION_TARGET.parent.exists():
        return False
    # The source is authoritative. Replacing this one generated extension
    # directory prevents removed/versioned entry files from surviving an
    # upgrade and being combined with current Webview media by Void's cache.
    expected_parent = (VOID_ROOT / 'extensions').resolve()
    if EXTENSION_TARGET.resolve().parent != expected_parent:
        raise RuntimeError(f'Unexpected extension target: {EXTENSION_TARGET}')
    if EXTENSION_TARGET.exists():
        shutil.rmtree(EXTENSION_TARGET)
    shutil.copytree(EXTENSION_SOURCE, EXTENSION_TARGET)
    # Target-local extension hosts and browser webviews must reach the same API.
    import json
    manifest_path = EXTENSION_TARGET / 'package.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    properties = manifest['contributes']['configuration']['properties']
    properties['egoagent.backendUrl']['default'] = BACKEND_ORIGIN
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    runtime = {'backendUrl': BACKEND_ORIGIN, 'id': os.environ.get('EGOAGENT_REMOTE_ID', ''),
               'label': os.environ.get('EGOAGENT_REMOTE_LABEL', '本机'),
               'managerUrl': os.environ.get('EGOAGENT_REMOTE_MANAGER_URL', 'http://127.0.0.1:8880/')}
    runtime['accessToken'] = os.environ.get('EGOAGENT_REMOTE_TOKEN', '')
    (EXTENSION_TARGET / 'connection-runtime.js').write_text('module.exports = ' + json.dumps(runtime) + ';\n', encoding='utf-8')
    if runtime['accessToken']:
        (EXTENSION_TARGET / 'connection-runtime.js').chmod(0o600)
    product_path = VOID_ROOT / 'product.json'
    product = json.loads(product_path.read_text(encoding='utf-8'))
    product['webviewContentExternalBaseUrlTemplate'] = WEBVIEW_ENDPOINT
    product_path.write_text(json.dumps(product, ensure_ascii=False, indent=2), encoding='utf-8')
    # Void keys its built-in extension cache by the parent directory mtime.
    # Updating files inside an existing extension directory does not always
    # change that timestamp on Windows, so explicitly invalidate the cache key.
    os.utime(EXTENSION_TARGET.parent, None)
    return True


def configure_native_chat_container():
    """Allow the EgoAgent Webview to live inside Void's native Chat container.

    Void 1.4.9 marks its Chat container as rejecting contributed views. Its
    Electron-only chat view also cannot run in the browser build, so disable
    that view and let the local EgoAgent view occupy the same panel.
    """
    if not WORKBENCH_BUNDLE.exists():
        return False

    source = WORKBENCH_BUNDLE.read_text(encoding='utf-8')
    updated = source.replace(
        'rejectAddedViews:!0,icon:Q.symbolMethod},2',
        'rejectAddedViews:!1,icon:Q.symbolMethod},2',
        1,
    )
    legacy_view_prefixes = (
        'das.registerViews([{id:F5e,hideByDefault:!1',
        'das.registerViews([{id:F5e,hideByDefault:!0',
    )
    legacy_view_suffix = (
        ',name:B(12474,""),ctorDescriptor:new un(tCt),canToggleVisibility:!1,'
        'canMoveView:!1,weight:80,order:1}],cas)'
    )
    for prefix in legacy_view_prefixes:
        updated = updated.replace(
            prefix + legacy_view_suffix,
            'void 0/*egoagent-native-chat*/',
            1,
        )
    # Extension view keys normally only resolve the stock containers
    # (Explorer/SCM/Debug). Add a local "void" alias for Void's native Chat
    # container so the extension registers there instead of falling back to
    # Explorer.
    view_container_switch = (
        'case"remote":return this.viewContainersRegistry.get(Mq);default:'
    )
    updated = updated.replace(
        view_container_switch,
        'case"remote":return this.viewContainersRegistry.get(Mq);'
        'case"void":return this.viewContainersRegistry.get(Nue);default:',
        1,
    )
    bridge_start = updated.rfind('\n;' + WORKBENCH_DROP_BRIDGE_MARKER)
    if bridge_start >= 0:
        # The bridge is appended to the generated bundle, so replace it as one
        # versioned unit when its implementation changes instead of stacking
        # duplicate drag listeners across upgrades.
        updated = updated[:bridge_start + 1] + WORKBENCH_DROP_BRIDGE.lstrip('\n')
    else:
        updated += WORKBENCH_DROP_BRIDGE
    # This command runs in the top-level renderer, not in a sandboxed webview
    # or extension worker. Its buttons therefore retain popup user activation.
    opener_source = EXTENSION_SOURCE / 'media' / 'workspace-window.js'
    if opener_source.exists():
        updated += ('\n;(()=>{\n' + opener_source.read_text(encoding='utf-8')
                    + '\nconst openWorkspace=createWorkspaceWindowOpener(window);'
                    + '\nEt.registerCommand("egoagent.openWorkspaceWindow",'
                    + '(_accessor,url,label)=>openWorkspace(url,label));\n})();\n')
    if updated != source:
        WORKBENCH_BUNDLE.write_text(updated, encoding='utf-8')
    return (
        'rejectAddedViews:!1,icon:Q.symbolMethod},2' in updated
        and 'void 0/*egoagent-native-chat*/' in updated
        and 'case"void":return this.viewContainersRegistry.get(Nue)' in updated
        and WORKBENCH_DROP_BRIDGE_MARKER in updated
    )


def configure_native_review_styles():
    """Keep native diff review colors flat instead of double-shading words."""
    if not WORKBENCH_STYLE.exists():
        return False
    source = WORKBENCH_STYLE.read_text(encoding='utf-8')
    legacy_marker = '\n/*egoagent-flat-review-diff-v1*/'
    legacy_start = source.rfind(legacy_marker)
    if legacy_start >= 0:
        source = source[:legacy_start]
    if WORKBENCH_FLAT_DIFF_MARKER not in source:
        source += WORKBENCH_FLAT_DIFF_STYLE
        WORKBENCH_STYLE.write_text(source, encoding='utf-8')
    return WORKBENCH_FLAT_DIFF_MARKER in source


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _trusted_origin(self):
        return is_trusted_local_origin(self.headers.get('Origin', ''))

    def _security_headers(self, *, cors=True):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        origin = str(self.headers.get('Origin', '') or '').strip()
        if cors and origin and self._trusted_origin():
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')

    def _guard(self):
        expected = os.environ.get('EGOAGENT_REMOTE_TOKEN', '')
        if expected and self.command != 'OPTIONS':
            from urllib.parse import urlsplit, parse_qs, urlencode
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            supplied = query.get('tkn', [''])[0] if parsed.path == '/' and self.command == 'GET' else ''
            # Webview subdomains cannot share the main page's HttpOnly cookie.
            # Their resource base is an authenticated, unguessable URL prefix.
            parts = parsed.path.split('/', 3)
            if len(parts) == 4 and parts[1] == 'auth' and hmac.compare_digest(parts[2], expected):
                self.path = '/' + parts[3] + ('?' + parsed.query if parsed.query else '')
            elif supplied and hmac.compare_digest(supplied, expected):
                query.pop('tkn', None)
                self.send_response(303)
                self.send_header('Location', '/' + ('?' + urlencode(query, doseq=True) if query else ''))
                self.send_header('Set-Cookie', f'{remote_cookie_name()}={expected}; Path=/; HttpOnly; SameSite=Strict')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return False
            elif not remote_request_authorized(self.headers):
                body = 'Remote authentication required. Open this project from the local EgoAgent SSH/WSL menu.'.encode()
                self.send_response(401)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return False
        if self._trusted_origin():
            return True
        body = b'Untrusted browser origin'
        self.send_response(403)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self._security_headers(cors=False)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return False

    def _target(self):
        if self.path.startswith('/v1/') or self.path.startswith('/api/'):
            return BACKEND_ORIGIN
        return VOID_ORIGIN

    def _proxy_streaming(self, url, body, hdrs):
        """Handle streaming (SSE) responses - pass chunks through without buffering."""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        host = parsed.hostname
        port = parsed.port or 80

        conn = http.client.HTTPConnection(host, port, timeout=300)
        headers_sent = False
        try:
            path = parsed.path + ('?' + parsed.query if parsed.query else '')
            conn.request(self.command, path, body=body, headers=hdrs)
            resp = conn.getresponse()

            self.send_response(resp.status)
            for key, val in resp.getheaders():
                if key.lower() not in (
                    'transfer-encoding', 'connection', 'content-length',
                    'access-control-allow-origin', 'vary',
                    'x-content-type-options', 'referrer-policy',
                ):
                    self.send_header(key, val)
            self._security_headers(cors=True)
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()

            headers_sent = True
            while True:
                line = resp.readline()
                if not line:
                    break
                self.wfile.write(line)
                self.wfile.flush()
                if line.strip() == b'data: [DONE]':
                    break
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        except Exception as e:
            if not headers_sent:
                try:
                    self.send_response(502)
                    self.send_header('Content-Type', 'text/plain')
                    self.end_headers()
                    self.wfile.write(f'Proxy streaming error: {e}'.encode())
                except Exception:
                    pass
        finally:
            conn.close()

    def _ws_tunnel(self):
        """Tunnel WebSocket upgrade to Void server via raw TCP relay."""
        if not self._guard():
            return
        try:
            backend = _connect_void()
            # The connection timeout is only for establishing the upstream.
            # A terminal/editor WebSocket must stay alive while the user is
            # reading or thinking, not disconnect after ten idle seconds.
            backend.settimeout(None)
        except Exception as e:
            self.send_response(502)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(f'WebSocket proxy error: {e}'.encode())
            return

        # Reconstruct and forward the original HTTP upgrade request
        req_line = f'{self.command} {self.path} {self.request_version}\r\n'
        backend.sendall(req_line.encode())
        for key, val in self.headers.items():
            if key.lower() == 'host':
                backend.sendall(f'Host: 127.0.0.1:{VOID_PORT}\r\n'.encode())
            else:
                backend.sendall(f'{key}: {val}\r\n'.encode())
        backend.sendall(b'\r\n')

        # Get the raw client socket
        client = self.request

        def relay(src, dst):
            try:
                while True:
                    data = src.recv(65536)
                    if not data:
                        break
                    dst.sendall(data)
            except (OSError, ConnectionResetError, BrokenPipeError):
                pass
            finally:
                try:
                    dst.shutdown(socket.SHUT_WR)
                except OSError:
                    pass

        # Bidirectional relay
        t1 = threading.Thread(target=relay, args=(backend, client), daemon=True)
        t2 = threading.Thread(target=relay, args=(client, backend), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        try:
            backend.close()
        except OSError:
            pass

    def _proxy(self):
        if not self._guard():
            return
        target = self._target()
        url = target + self.path
        cl = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(cl) if cl > 0 else None
        hdrs = {k: self.headers[k] for k in self.headers if k.lower() not in ('host','connection','transfer-encoding')}

        # Use streaming proxy for chat completions (SSE)
        if self.path.startswith('/v1/chat/completions') and self.command == 'POST':
            is_stream = False
            if body:
                try:
                    import json
                    req_body = json.loads(body)
                    is_stream = req_body.get('stream', False)
                except Exception:
                    pass
            if is_stream:
                self._proxy_streaming(url, body, hdrs)
                return

        # Standard proxy (buffered)
        try:
            # A proxy must preserve redirects, not follow them server-side
            # (remote-open's auth-cookie bootstrap belongs to the browser).
            with self._upstream_response(target, body, hdrs) as r:
                data = r.read()
                # Keep Void's remote WebSocket connection on the unified port.
                request_path = self.path.split('?', 1)[0]
                if b'</html>' in data and b'workbench' in data and (request_path == '/' or request_path.endswith('.html')):
                    data = data.replace(
                        f'127.0.0.1:{VOID_PORT}'.encode(),
                        f'127.0.0.1:{LISTEN_PORT}'.encode()
                    )
                    # The Void fork is not published on Microsoft's Webview
                    # CDN. Override the workbench option so native extension
                    # Webviews load from this same local server instead.
                    marker = b'&quot;serverBasePath&quot;:&quot;/&quot;'
                    local_webview = (
                        marker
                        + b',&quot;webviewEndpoint&quot;:&quot;'
                        + WEBVIEW_ENDPOINT.encode()
                        + b'&quot;'
                    )
                    data = data.replace(marker, local_webview, 1)
                    # The upstream path contains an immutable commit hash, but
                    # this local build applies a small runtime integration
                    # patch. Give the patched bundle its own cache identity.
                    data = data.replace(
                        b'workbench.js"></script>',
                        f'workbench.js?{WORKBENCH_CACHE_KEY}"></script>'.encode(),
                        1,
                    )
                    data = data.replace(
                        b'workbench.css">',
                        f'workbench.css?{WORKBENCH_CACHE_KEY}">'.encode(),
                        1,
                    )
                self.send_response(r.status)
                for k,v in r.getheaders():
                    if k.lower() not in (
                        'transfer-encoding', 'connection', 'content-length',
                        'access-control-allow-origin', 'vary',
                        'x-content-type-options', 'referrer-policy',
                    ):
                        if k.lower() == 'content-security-policy':
                            v = v.replace(
                                "frame-src 'self'",
                                f"frame-src 'self' http://*.localhost:{LISTEN_PORT}"
                            )
                        if k.lower() == 'cache-control' and request_path.endswith(('/workbench/workbench.js', '/workbench/workbench.css')):
                            v = 'no-store'
                        self.send_header(k, v)
                self.send_header('Content-Length', str(len(data)))
                self._security_headers(cors=True)
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as e:
            data = e.read()
            self.send_response(e.code)
            for k,v in e.headers.items():
                if k.lower() not in (
                    'transfer-encoding', 'connection', 'access-control-allow-origin', 'vary',
                    'x-content-type-options', 'referrer-policy',
                ):
                    self.send_header(k, v)
            self._security_headers(cors=True)
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self.send_response(502)
            self.send_header('Content-Type','text/plain')
            self.end_headers()
            self.wfile.write(f'Proxy error: {e}'.encode())

    @contextlib.contextmanager
    def _upstream_response(self, target, body, headers):
        port = BACKEND_PORT if target == BACKEND_ORIGIN else VOID_PORT
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=300)
        if target == VOID_ORIGIN and VOID_SOCKET:
            connection.sock = _connect_void()
            connection.sock.settimeout(300)
        try:
            connection.request(self.command, self.path, body=body, headers=headers)
            yield connection.getresponse()
        finally:
            connection.close()

    def do_GET(self):
        # WebSocket upgrade: tunnel directly
        if self.headers.get('Upgrade', '').lower() == 'websocket':
            self._ws_tunnel()
        else:
            self._proxy()

    do_POST = do_PUT = do_DELETE = lambda s: s._proxy()

    def do_OPTIONS(self):
        if not self._guard():
            return
        self.send_response(204)
        self._security_headers(cors=True)
        self.send_header('Access-Control-Allow-Methods','GET,POST,PUT,DELETE,OPTIONS')
        self.send_header('Access-Control-Allow-Headers','Content-Type,Authorization,X-EgoAgent-Remote-Token')
        self.end_headers()

class S(socketserver.ThreadingMixIn, http.server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

if __name__ == '__main__':
    # Parse before installing extensions or starting children. This makes
    # `start-all.py --help` a read-only CLI operation instead of accidentally
    # launching a proxy in the background.
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--stop-file', type=Path, help='Optional private desktop lifecycle marker (no network shutdown endpoint)')
    args = parser.parse_args()
    if args.stop_file:
        marker_root = (ROOT_DIR / '.runtime' / 'desktop').resolve()
        if args.stop_file.resolve().parent != marker_root or args.stop_file.exists():
            parser.error('--stop-file must be a new marker under .runtime/desktop')
    backend_process = None
    backend_supervisor = None
    void_process = None
    try:
        # Install and patch before Void starts so its one-time extension scan
        # always sees the current native Chat implementation.
        extension_installed = install_native_extension()
        chat_container_ready = configure_native_chat_container()
        review_styles_ready = configure_native_review_styles()
        void_process = start_void_if_needed()
        backend_process = start_backend_if_needed()
        backend_supervisor = start_backend_supervisor(backend_process)
        s = S((LISTEN_HOST, LISTEN_PORT), ProxyHandler)
        if args.stop_file:
            def watch_desktop_stop():
                while not args.stop_file.exists():
                    time.sleep(0.5)
                s.shutdown()
            threading.Thread(target=watch_desktop_stop, daemon=True).start()
        print(f'EgoAgent+Void on http://localhost:{LISTEN_PORT}/')
        print(f'  /v1/* /api/* -> backend:{BACKEND_PORT}')
        print(f'  /*           -> void:{VOID_PORT}')
        print(f'  native DAG Chat extension: {"installed" if extension_installed else "not found"}')
        print(f'  Void Chat container: {"integrated" if chat_container_ready else "not patched"}')
        print(f'  Agent review diff: {"flat line colors" if review_styles_ready else "stock colors"}')
        print(f'  local Webview resources -> localhost:{LISTEN_PORT} (authenticated)' if os.environ.get('EGOAGENT_REMOTE_TOKEN') else f'  local Webview resources -> {WEBVIEW_ENDPOINT}')
        print(f'  WebSocket upgrade -> tunnel to void:{VOID_PORT}')
        print(f'  SSE streaming for /v1/chat/completions')
        s.serve_forever()
    finally:
        stop_backend_supervisor(backend_supervisor)
        if backend_supervisor is None:
            _stop_owned_process(backend_process)
        _stop_owned_process(void_process)
