#!/usr/bin/env python3
"""Single-port proxy: Void IDE + EgoAgent API on one port. Stdlib only.
Injects EgoAgent panel scripts into workbench HTML responses.
Serves custom JS from /ego/ path prefix.
Supports SSE streaming passthrough for /v1/chat/completions.
Supports WebSocket tunneling for Void IDE remote connections."""
import os, http.server, urllib.request, urllib.error, socketserver, mimetypes, http.client, socket, threading
from pathlib import Path

for k in list(os.environ.keys()):
    if 'proxy' in k.lower():
        del os.environ[k]

VOID_PORT = 8869
BACKEND_PORT = 8765
LISTEN_PORT = 8880
VOID_ORIGIN = f'http://127.0.0.1:{VOID_PORT}'
BACKEND_ORIGIN = f'http://127.0.0.1:{BACKEND_PORT}'

# Custom JS directory
JS_DIR = Path(__file__).parent / 'void-web' / 'out' / 'vs' / 'code' / 'browser' / 'workbench'

# Script injection snippet (added before </html> in workbench pages)
INJECT_SCRIPTS = b'''
<script src="/ego/egoagent-panel.js"></script>
<script src="/ego/egoagent-p1.js"></script>
<script src="/ego/egoagent-p2.js"></script>
<script src="/ego/egoagent-editor.js"></script>
'''

class ProxyHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _target(self):
        if self.path.startswith('/v1/') or self.path.startswith('/api/'):
            return BACKEND_ORIGIN
        return VOID_ORIGIN

    def _serve_ego_file(self):
        """Serve custom JS files from /ego/ path."""
        filename = self.path.split('/ego/', 1)[1].split('?')[0]
        filepath = JS_DIR / filename
        if not filepath.exists() or '..' in filename:
            self.send_response(404)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Not found')
            return
        content = filepath.read_bytes()
        mime = mimetypes.guess_type(filename)[0] or 'application/javascript'
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(content)

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
                if key.lower() not in ('transfer-encoding', 'connection', 'content-length'):
                    self.send_header(key, val)
            self.send_header('Access-Control-Allow-Origin', '*')
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
        try:
            backend = socket.create_connection(('127.0.0.1', VOID_PORT), timeout=10)
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
        t1.join(timeout=300)
        t2.join(timeout=300)
        try:
            backend.close()
        except OSError:
            pass

    def _proxy(self):
        # Serve custom JS files directly
        if self.path.startswith('/ego/'):
            self._serve_ego_file()
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
        req = urllib.request.Request(url, data=body, headers=hdrs, method=self.command)
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                data = r.read()
                # Inject scripts into workbench HTML and rewrite remoteAuthority
                if b'</html>' in data and b'workbench' in data and (self.path == '/' or self.path.endswith('.html')):
                    # Rewrite remoteAuthority so WebSocket goes through this proxy
                    data = data.replace(
                        f'127.0.0.1:{VOID_PORT}'.encode(),
                        f'127.0.0.1:{LISTEN_PORT}'.encode()
                    )
                    data = data.replace(b'</html>', INJECT_SCRIPTS + b'</html>')
                self.send_response(r.status)
                for k,v in r.getheaders():
                    if k.lower() not in ('transfer-encoding','connection','content-length'):
                        self.send_header(k, v)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as e:
            data = e.read()
            self.send_response(e.code)
            for k,v in e.headers.items():
                if k.lower() not in ('transfer-encoding','connection'):
                    self.send_header(k, v)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self.send_response(502)
            self.send_header('Content-Type','text/plain')
            self.end_headers()
            self.wfile.write(f'Proxy error: {e}'.encode())

    def do_GET(self):
        # WebSocket upgrade: tunnel directly
        if self.headers.get('Upgrade', '').lower() == 'websocket':
            self._ws_tunnel()
        else:
            self._proxy()

    do_POST = do_PUT = do_DELETE = lambda s: s._proxy()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin','*')
        self.send_header('Access-Control-Allow-Methods','GET,POST,PUT,DELETE,OPTIONS')
        self.send_header('Access-Control-Allow-Headers','Content-Type,Authorization')
        self.end_headers()

class S(socketserver.ThreadingMixIn, http.server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

if __name__ == '__main__':
    s = S(('0.0.0.0', LISTEN_PORT), ProxyHandler)
    print(f'EgoAgent+Void on http://localhost:{LISTEN_PORT}/')
    print(f'  /v1/* /api/* -> backend:{BACKEND_PORT}')
    print(f'  /ego/*       -> custom JS from {JS_DIR}')
    print(f'  /*           -> void:{VOID_PORT}')
    print(f'  WebSocket upgrade -> tunnel to void:{VOID_PORT}')
    print(f'  SSE streaming for /v1/chat/completions')
    s.serve_forever()
