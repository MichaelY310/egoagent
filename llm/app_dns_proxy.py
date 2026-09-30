"""Process-local DNS fallback for HTTPS model providers.

The operating system resolver is sometimes unavailable on restricted or
misconfigured networks even though direct UDP DNS and outbound HTTPS still
work.  Replacing the system DNS or connecting to a bare IP are both poor
product defaults.  This module instead runs a localhost-only HTTP CONNECT
proxy for model-provider hosts:

* DNS A records are queried directly from configurable public resolvers.
* TLS stays end-to-end between ``requests`` and the original hostname, so SNI
  and certificate verification are unchanged.
* Exact host and port allow-lists prevent the listener becoming an open proxy.
* The proxy sees only encrypted TLS bytes and never logs request headers,
  bodies, API keys, or model output.

Only ``CustomLLM`` opts into the returned proxy URL. Other application HTTP
traffic is unaffected.
"""

from __future__ import annotations

import ipaddress
import os
import secrets
import select
import socket
import socketserver
import struct
import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Optional
from urllib.parse import urlsplit


DEFAULT_RESOLVERS = ("223.5.5.5", "119.29.29.29")
_MAX_HEADER_BYTES = 32 * 1024
_DNS_CACHE_MIN_TTL = 5
_DNS_CACHE_MAX_TTL = 300


class AppDNSProxyError(ConnectionError):
    """Raised when the application-local resolver or tunnel cannot proceed."""


def _encode_dns_name(hostname: str) -> bytes:
    labels = hostname.rstrip(".").split(".")
    encoded = bytearray()
    for label in labels:
        raw = label.encode("idna")
        if not raw or len(raw) > 63:
            raise AppDNSProxyError(f"invalid DNS label in {hostname!r}")
        encoded.append(len(raw))
        encoded.extend(raw)
    encoded.append(0)
    return bytes(encoded)


def build_dns_query(hostname: str, transaction_id: int) -> bytes:
    """Build a standard recursive IPv4 DNS query."""

    header = struct.pack("!HHHHHH", int(transaction_id) & 0xFFFF, 0x0100, 1, 0, 0, 0)
    return header + _encode_dns_name(hostname) + struct.pack("!HH", 1, 1)


def _skip_dns_name(packet: bytes, offset: int) -> int:
    while True:
        if offset >= len(packet):
            raise AppDNSProxyError("truncated DNS name")
        length = packet[offset]
        if length == 0:
            return offset + 1
        if length & 0xC0 == 0xC0:
            if offset + 1 >= len(packet):
                raise AppDNSProxyError("truncated DNS compression pointer")
            return offset + 2
        if length & 0xC0:
            raise AppDNSProxyError("unsupported DNS label encoding")
        offset += 1 + length


def parse_dns_a_response(packet: bytes, transaction_id: int) -> list[tuple[str, int]]:
    """Return ``(IPv4, TTL)`` records from answer and additional sections."""

    if len(packet) < 12:
        raise AppDNSProxyError("truncated DNS response")
    response_id, flags, question_count, answer_count, authority_count, additional_count = struct.unpack(
        "!HHHHHH", packet[:12]
    )
    if response_id != (int(transaction_id) & 0xFFFF):
        raise AppDNSProxyError("DNS transaction id mismatch")
    if not flags & 0x8000:
        raise AppDNSProxyError("DNS packet is not a response")
    rcode = flags & 0x000F
    if rcode:
        raise AppDNSProxyError(f"DNS resolver returned rcode {rcode}")

    offset = 12
    for _ in range(question_count):
        offset = _skip_dns_name(packet, offset)
        if offset + 4 > len(packet):
            raise AppDNSProxyError("truncated DNS question")
        offset += 4

    records: list[tuple[str, int]] = []
    for _ in range(answer_count + authority_count + additional_count):
        offset = _skip_dns_name(packet, offset)
        if offset + 10 > len(packet):
            raise AppDNSProxyError("truncated DNS resource record")
        record_type, record_class, ttl, data_length = struct.unpack("!HHIH", packet[offset:offset + 10])
        offset += 10
        end = offset + data_length
        if end > len(packet):
            raise AppDNSProxyError("truncated DNS resource data")
        if record_type == 1 and record_class == 1 and data_length == 4:
            address = socket.inet_ntoa(packet[offset:end])
            if address not in {item[0] for item in records}:
                records.append((address, int(ttl)))
        offset = end
    return records


class DirectDNSResolver:
    """Small cached IPv4 resolver that does not use ``socket.getaddrinfo``."""

    def __init__(self, servers: Iterable[str] = DEFAULT_RESOLVERS, timeout: float = 2.0):
        self.servers = tuple(str(server).strip() for server in servers if str(server).strip())
        if not self.servers:
            raise ValueError("at least one DNS resolver is required")
        self.timeout = max(0.1, float(timeout))
        self._cache: dict[str, tuple[float, tuple[str, ...]]] = {}
        self._lock = threading.RLock()

    def resolve(self, hostname: str) -> list[str]:
        clean = str(hostname or "").strip().rstrip(".").lower()
        if not clean:
            raise AppDNSProxyError("empty provider hostname")
        try:
            parsed = ipaddress.ip_address(clean)
            if parsed.version != 4:
                raise AppDNSProxyError("the application DNS tunnel currently requires an IPv4 target")
            return [str(parsed)]
        except ValueError:
            pass

        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(clean)
            if cached and cached[0] > now:
                return list(cached[1])

        errors = []
        for server in self.servers:
            transaction_id = secrets.randbelow(65536)
            query = build_dns_query(clean, transaction_id)
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                    client.settimeout(self.timeout)
                    client.sendto(query, (server, 53))
                    packet, source = client.recvfrom(65535)
                if source[0] != server:
                    raise AppDNSProxyError("DNS response came from an unexpected server")
                records = parse_dns_a_response(packet, transaction_id)
                if not records:
                    raise AppDNSProxyError("DNS response contained no IPv4 addresses")
                ttl = min(item[1] for item in records)
                expires = now + min(_DNS_CACHE_MAX_TTL, max(_DNS_CACHE_MIN_TTL, ttl))
                addresses = tuple(item[0] for item in records)
                with self._lock:
                    self._cache[clean] = (expires, addresses)
                return list(addresses)
            except (OSError, AppDNSProxyError) as error:
                errors.append(f"{server}: {error}")
        raise AppDNSProxyError("direct DNS lookup failed (" + "; ".join(errors) + ")")


def _split_connect_target(target: str) -> tuple[str, int]:
    value = target.strip()
    if value.startswith("["):
        closing = value.find("]")
        if closing < 0 or closing + 1 >= len(value) or value[closing + 1] != ":":
            raise AppDNSProxyError("invalid CONNECT target")
        host, raw_port = value[1:closing], value[closing + 2:]
    else:
        host, separator, raw_port = value.rpartition(":")
        if not separator:
            raise AppDNSProxyError("CONNECT target must include a port")
    try:
        port = int(raw_port)
    except ValueError as error:
        raise AppDNSProxyError("invalid CONNECT port") from error
    return host.rstrip(".").lower(), port


class _ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


class _ConnectHandler(socketserver.BaseRequestHandler):
    def handle(self):
        client = self.request
        client.settimeout(10)
        header = bytearray()
        while b"\r\n\r\n" not in header:
            chunk = client.recv(4096)
            if not chunk:
                return
            header.extend(chunk)
            if len(header) > _MAX_HEADER_BYTES:
                self._reply(431, "Request Header Fields Too Large")
                return
        try:
            first_line = bytes(header).split(b"\r\n", 1)[0].decode("ascii")
            method, target, _version = first_line.split(" ", 2)
            if method.upper() != "CONNECT":
                self._reply(405, "Method Not Allowed")
                return
            host, port = _split_connect_target(target)
        except (UnicodeError, ValueError, AppDNSProxyError):
            self._reply(400, "Bad Request")
            return

        service: AppDNSConnectProxy = self.server.proxy_service  # type: ignore[attr-defined]
        if not service.is_allowed(host, port):
            self._reply(403, "Forbidden")
            return
        try:
            addresses = service.resolver(host)
            upstream = service.connect(addresses, port)
        except (OSError, AppDNSProxyError):
            self._reply(502, "Bad Gateway")
            return

        with upstream:
            client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            client.settimeout(None)
            upstream.settimeout(None)
            self._relay(client, upstream, service.idle_timeout)

    def _reply(self, status: int, reason: str):
        try:
            self.request.sendall(
                f"HTTP/1.1 {status} {reason}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n".encode("ascii")
            )
        except OSError:
            pass

    @staticmethod
    def _relay(client: socket.socket, upstream: socket.socket, idle_timeout: float):
        sockets = (client, upstream)
        while True:
            try:
                readable, _, exceptional = select.select(sockets, (), sockets, idle_timeout)
            except OSError:
                return
            if exceptional or not readable:
                return
            for source in readable:
                target = upstream if source is client else client
                try:
                    data = source.recv(64 * 1024)
                    if not data:
                        return
                    target.sendall(data)
                except OSError:
                    return


@dataclass
class AppDNSConnectProxy:
    """Lifecycle and allow-list for one localhost CONNECT listener."""

    allowed_hosts: set[str]
    resolver: Callable[[str], list[str]]
    allowed_ports: set[int]
    idle_timeout: float = 300.0

    def __post_init__(self):
        self.allowed_hosts = {str(host).strip().rstrip(".").lower() for host in self.allowed_hosts if str(host).strip()}
        self.allowed_ports = {int(port) for port in self.allowed_ports}
        self._lock = threading.RLock()
        self._server: Optional[_ThreadingTCPServer] = None
        self._thread: Optional[threading.Thread] = None

    def add_hosts(self, hosts: Iterable[str]):
        with self._lock:
            self.allowed_hosts.update(
                str(host).strip().rstrip(".").lower() for host in hosts if str(host).strip()
            )

    def is_allowed(self, host: str, port: int) -> bool:
        with self._lock:
            return host.rstrip(".").lower() in self.allowed_hosts and int(port) in self.allowed_ports

    @staticmethod
    def connect(addresses: Iterable[str], port: int) -> socket.socket:
        errors = []
        for address in addresses:
            try:
                return socket.create_connection((address, int(port)), timeout=10)
            except OSError as error:
                errors.append(str(error))
        raise AppDNSProxyError("provider connection failed (" + "; ".join(errors) + ")")

    def start(self) -> str:
        with self._lock:
            if self._server is not None:
                port = self._server.server_address[1]
                return f"http://127.0.0.1:{port}"
            server = _ThreadingTCPServer(("127.0.0.1", 0), _ConnectHandler)
            server.proxy_service = self  # type: ignore[attr-defined]
            thread = threading.Thread(target=server.serve_forever, name="egoagent-app-dns", daemon=True)
            thread.start()
            self._server = server
            self._thread = thread
            return f"http://127.0.0.1:{server.server_address[1]}"

    def close(self):
        with self._lock:
            server, thread = self._server, self._thread
            self._server = None
            self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None and thread.is_alive():
            thread.join(timeout=2)


_SINGLETON_LOCK = threading.RLock()
_SINGLETON: Optional[AppDNSConnectProxy] = None
_SYSTEM_DNS_CACHE: dict[str, bool] = {}


def _system_dns_available(hostname: str, timeout: float = 0.75) -> bool:
    """Bound a potentially wedged OS resolver without blocking model setup."""

    clean = hostname.rstrip(".").lower()
    with _SINGLETON_LOCK:
        if clean in _SYSTEM_DNS_CACHE:
            return _SYSTEM_DNS_CACHE[clean]
    completed = threading.Event()
    result = {"ok": False}

    def lookup():
        try:
            result["ok"] = bool(socket.getaddrinfo(clean, 443, socket.AF_UNSPEC, socket.SOCK_STREAM))
        except OSError:
            result["ok"] = False
        finally:
            completed.set()

    threading.Thread(target=lookup, name="egoagent-system-dns-probe", daemon=True).start()
    completed.wait(max(0.05, float(timeout)))
    available = completed.is_set() and result["ok"]
    with _SINGLETON_LOCK:
        _SYSTEM_DNS_CACHE[clean] = available
    return available


def _resolver_servers() -> tuple[str, ...]:
    configured = os.environ.get("EGOAGENT_LLM_DNS_SERVERS", "")
    values = tuple(item.strip() for item in configured.split(",") if item.strip())
    return values or DEFAULT_RESOLVERS


def ensure_app_dns_proxy(hostname: str) -> str:
    global _SINGLETON
    clean = hostname.rstrip(".").lower()
    with _SINGLETON_LOCK:
        if _SINGLETON is None:
            resolver = DirectDNSResolver(_resolver_servers())
            _SINGLETON = AppDNSConnectProxy({clean}, resolver.resolve, {443})
        else:
            _SINGLETON.add_hosts([clean])
        return _SINGLETON.start()


def app_dns_proxy_for_url(url: str) -> Optional[str]:
    """Return an LLM-only proxy URL according to the configured fallback mode."""

    parsed = urlsplit(str(url or ""))
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if parsed.scheme.lower() != "https" or not hostname:
        return None
    try:
        if ipaddress.ip_address(hostname).is_loopback:
            return None
    except ValueError:
        if hostname in {"localhost"}:
            return None

    explicit = os.environ.get("EGOAGENT_LLM_HTTPS_PROXY", "").strip()
    if explicit:
        return explicit
    # A user-configured process proxy already controls DNS behavior. Do not
    # silently replace it with the local direct-DNS path.
    if any(os.environ.get(name, "").strip() for name in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy")):
        return None

    mode = os.environ.get("EGOAGENT_LLM_APP_DNS_PROXY", "auto").strip().lower()
    if mode in {"0", "false", "off", "disabled"}:
        return None
    if mode in {"1", "true", "on", "enabled"} or not _system_dns_available(hostname):
        return ensure_app_dns_proxy(hostname)
    return None


def is_name_resolution_error(error: BaseException) -> bool:
    """Recognize requests/urllib3 DNS failures without importing either."""

    current: Optional[BaseException] = error
    visited = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        name = type(current).__name__.lower()
        message = str(current).lower()
        if (
            "nameresolutionerror" in name
            or "getaddrinfo failed" in message
            or "failed to resolve" in message
            or "name or service not known" in message
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


def is_recoverable_direct_connection_error(error: BaseException) -> bool:
    """Return whether the provider request should try the app DNS route once.

    Windows can surface a blocked hostname route as ``WSAEACCES`` (10013)
    instead of a ``NameResolutionError``.  The fallback remains deliberately
    narrow: it is only used by :class:`CustomLLM` for the already selected
    HTTPS provider host, and the CONNECT proxy keeps its exact host/port
    allow-list.
    """

    if is_name_resolution_error(error):
        return True
    current: Optional[BaseException] = error
    visited = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        message = str(current).lower()
        if (
            "winerror 10013" in message
            or "wsaeacces" in message
            or "access a socket in a way forbidden by its access permissions" in message
        ):
            return True
        current = current.__cause__ or current.__context__
    return False
