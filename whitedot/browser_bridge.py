"""Paired loopback transport for the optional Chrome/Edge extension."""

from __future__ import annotations

import hmac
import json
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .types import Rect, Target


PORT = 37831
MAX_CHARS = 24_000
MAX_BODY = 300_000  # accommodates JSON-escaped Unicode at the text limit
TTL_SECONDS = 2
_BROWSERS = {"chrome": "Chrome", "edge": "Edge"}
_FIELD = re.compile(r"[A-Za-z0-9_-]{1,128}")
_ORIGIN = re.compile(r"chrome-extension://[a-p]{32}")


class _InvalidRequest(ValueError):
    pass


class _LoopbackServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = not hasattr(socket, "SO_EXCLUSIVEADDRUSE")

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def __init__(self, bridge, port):
        self.bridge = bridge
        self._slots = threading.BoundedSemaphore(8)
        super().__init__(("127.0.0.1", port), _Handler)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def service_actions(self):
        self.bridge._expire()

    def handle_error(self, request, client_address):
        # A tab may disappear in the middle of a request. Never log payloads.
        pass


class _Handler(BaseHTTPRequestHandler):
    server_version = "WhiteDot"
    sys_version = ""

    def setup(self):
        self.request.settimeout(2)
        super().setup()

    def log_message(self, format, *args):
        pass

    def _header(self, key):
        values = self.headers.get_all(key, [])
        return values[0] if len(values) == 1 else ""

    def _reply(self, status, payload=None, origin=None, preflight=False):
        body = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode() if payload is not None else b""
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        if body:
            self.send_header("Content-Type", "application/json; charset=utf-8")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        if preflight:
            self.send_header("Access-Control-Allow-Methods", "POST")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Access-Control-Max-Age", "300")
            if self._header("Access-Control-Request-Private-Network") == "true":
                self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()
        if body:
            self.wfile.write(body)
        self.close_connection = True

    def _origin(self):
        if self.path != "/v1/sync":
            self._reply(404)
            return None
        expected = f"127.0.0.1:{self.server.server_port}"
        origin = self._header("Origin")
        if self._header("Host") != expected or not _ORIGIN.fullmatch(origin):
            self._reply(403)
            return None
        return origin

    def do_OPTIONS(self):
        origin = self._origin()
        if not origin:
            return
        requested = self._header("Access-Control-Request-Headers").lower().split(",")
        if self._header("Access-Control-Request-Method") != "POST" or any(
            key.strip() not in ("authorization", "content-type", "") for key in requested
        ):
            self._reply(403)
            return
        self._reply(204, origin=origin, preflight=True)

    def do_POST(self):
        origin = self._origin()
        if not origin:
            return
        bridge = self.server.bridge
        auth = self._header("Authorization")
        if not auth.isascii() or not hmac.compare_digest(auth, bridge._authorization):
            self._reply(401, origin=origin)
            return
        if self._header("Content-Type").split(";", 1)[0].strip().lower() != "application/json":
            self._reply(415, origin=origin)
            return
        raw_length = self._header("Content-Length")
        if self.headers.get_all("Transfer-Encoding") or not re.fullmatch(r"[0-9]{1,9}", raw_length):
            self._reply(400, origin=origin)
            return
        size = int(raw_length)
        if not 0 < size <= MAX_BODY:
            self._reply(413, origin=origin)
            return
        if bridge.paused:
            self._reply(200, {"active": False, "issues": [], "paused": True}, origin)
            return
        try:
            body = self.rfile.read(size)
            if len(body) != size:
                raise _InvalidRequest
            payload = json.loads(body.decode("utf-8"))
            response = bridge._sync(payload)
        except (ValueError, RecursionError, UnicodeError):
            self._reply(400, origin=origin)
            return
        self._reply(200, response, origin)


class BrowserBridge:
    """Only a focused snapshot approved by the desktop can receive suggestions."""

    def __init__(self, token, *, port=PORT, clock=time.monotonic):
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token):
            raise ValueError("浏览器连接码无效，请重新配对。")
        self._authorization = "Bearer " + token
        self._port = port
        self._clock = clock
        self._lock = threading.RLock()
        self._lifecycle = threading.Lock()
        self._live = {}
        self._published = None
        self._paused = False
        self._server = self._thread = None

    def start(self):
        """Bind loopback only. OSError signals that the configured port is unavailable."""
        with self._lifecycle:
            if self._server is None:
                server = _LoopbackServer(self, self._port)
                thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.25},
                                          name="WhiteDot browser companion", daemon=True)
                thread.start()
                self._server, self._thread = server, thread

    def stop(self):
        with self._lifecycle:
            if self._server is not None:
                self._server.shutdown()
                self._server.server_close()
                self._thread.join()
                self._server = self._thread = None
            self.pause(True)

    @property
    def paused(self):
        with self._lock:
            return self._paused

    def pause(self, paused):
        with self._lock:
            self._paused = bool(paused)
            if self._paused:
                self._live.clear()
                self._published = None

    def _expire(self):
        with self._lock:
            now = self._clock()
            for browser, (target, seen) in list(self._live.items()):
                if now - seen >= TTL_SECONDS:
                    self._forget(browser, target.token)

    def _forget(self, browser, token):
        live = self._live.get(browser)
        if live and live[0].token == token:
            del self._live[browser]
        if self._published and self._published[0].token == token:
            self._published = None

    def _sync(self, data):
        if not isinstance(data, dict):
            raise _InvalidRequest
        browser, field = data.get("browser"), data.get("field")
        if not isinstance(browser, str) or browser not in _BROWSERS:
            raise _InvalidRequest
        if not isinstance(field, str) or not _FIELD.fullmatch(field):
            raise _InvalidRequest
        token = f"web:{browser}:{field}"
        empty = {"active": False, "issues": []}
        with self._lock:
            if self._paused:
                return {**empty, "paused": True}
            self._expire()
            if set(data) == {"browser", "field", "clear"} and data["clear"] is True:
                self._forget(browser, token)
                return empty
            text = data.get("text")
            if set(data) != {"browser", "field", "text"} or not isinstance(text, str) or len(text) > MAX_CHARS:
                raise _InvalidRequest
            text.encode("utf-8")  # reject unpaired surrogates at the transport boundary
            target = Target(token, text, _BROWSERS[browser], Rect(0, 0, 0, 0))
            previous = self._live.get(browser)
            if previous and previous[0] != target:
                self._forget(browser, previous[0].token)
            self._live[browser] = target, self._clock()
            if self._published and self._published[0] == target:
                return {"active": True, "issues": self._published[1]}
            return empty

    def snapshot(self, browser: str) -> Target | None:
        with self._lock:
            self._expire()
            entry = self._live.get(browser)
            return entry[0] if entry else None

    def publish(self, target, issues):
        with self._lock:
            self._expire()
            self._published = None
            if self._paused or target is None or not any(target == entry[0] for entry in self._live.values()):
                return
            results = []
            for issue in issues:
                if len(results) == 32:
                    break
                if 0 <= issue.start < issue.end <= len(target.text) and target.text[issue.start:issue.end] == issue.original:
                    results.append({"start": issue.start, "end": issue.end, "original": issue.original,
                                    "suggestions": list(issue.suggestions), "explanation": issue.explanation})
            self._published = target, results
