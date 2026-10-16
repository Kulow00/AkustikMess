"""HTTP-Server der Fernbedienung (nur Standardbibliothek).

Thread-Modell: Der Server läuft in eigenen Threads und fasst nie Qt-Objekte an.
* Der GUI-Thread legt regelmäßig einen fertigen JSON-Schnappschuss ab
  (``set_snapshot``), den ``GET /api/state`` unverändert ausliefert.
* ``POST /api/cmd`` legt Befehle in eine Warteschlange; der GUI-Thread arbeitet
  sie ab (``drain``) und meldet das Ergebnis zurück.

Zugriff nur mit dem geheimen Schlüssel (Parameter ``t`` bzw. Kopfzeile
``X-Token``), Vergleich zeitkonstant.
"""

from __future__ import annotations

import hmac
import json
import queue
import secrets
import socket
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .page import PAGE

COMMAND_TIMEOUT_S = 5.0
MAX_BODY = 16 * 1024


@dataclass
class Command:
    action: str
    args: dict
    done: threading.Event = field(default_factory=threading.Event)
    result: dict = field(default_factory=lambda: {"ok": False, "message": "Zeitüberschreitung"})


class RemoteServer:
    def __init__(self, port: int = 8765, token: str | None = None, host: str = "0.0.0.0"):
        self.token = token or secrets.token_urlsafe(12)
        self.host, self.requested_port = host, port
        self.commands: "queue.Queue[Command]" = queue.Queue()
        self._snapshot = b"{}"
        self._lock = threading.Lock()
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.last_request = 0.0
        self.clients: dict[str, float] = {}

    # --- Lebenszyklus ------------------------------------------------------------
    def start(self) -> None:
        server = self

        class Handler(_Handler):
            remote = server

        self._httpd = ThreadingHTTPServer((self.host, self.requested_port), Handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="RemoteHTTP", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        # wartende Befehle freigeben
        while not self.commands.empty():
            cmd = self.commands.get_nowait()
            cmd.result = {"ok": False, "message": "Fernbedienung beendet"}
            cmd.done.set()

    @property
    def running(self) -> bool:
        return self._httpd is not None

    @property
    def port(self) -> int:
        return self._httpd.server_address[1] if self._httpd else self.requested_port

    def urls(self) -> list[str]:
        return [f"http://{ip}:{self.port}/?t={self.token}" for ip in local_ipv4_addresses()]

    def active_clients(self, within_s: float = 5.0) -> int:
        now = time.monotonic()
        return sum(1 for t in self.clients.values() if now - t < within_s)

    # --- Daten zwischen GUI und Server ------------------------------------------------
    def set_snapshot(self, data: dict) -> None:
        raw = json.dumps(data, separators=(",", ":"), allow_nan=False).encode()
        with self._lock:
            self._snapshot = raw

    def snapshot(self) -> bytes:
        with self._lock:
            return self._snapshot

    def submit(self, action: str, args: dict, timeout: float = COMMAND_TIMEOUT_S) -> dict:
        cmd = Command(action, args)
        self.commands.put(cmd)
        cmd.done.wait(timeout)
        return cmd.result

    def drain(self, executor) -> int:
        """Im GUI-Thread aufrufen: führt wartende Befehle aus. ``executor(action, args) -> dict``."""
        n = 0
        while True:
            try:
                cmd = self.commands.get_nowait()
            except queue.Empty:
                return n
            try:
                cmd.result = executor(cmd.action, cmd.args) or {"ok": True}
            except Exception as exc:  # noqa: BLE001 – Fehler an das Handy melden
                cmd.result = {"ok": False, "message": str(exc)}
            cmd.done.set()
            n += 1

    def check_token(self, value: str | None) -> bool:
        return bool(value) and hmac.compare_digest(value.encode(), self.token.encode())


class _Handler(BaseHTTPRequestHandler):
    remote: RemoteServer
    server_version = "AkustikMess"

    def log_message(self, *args) -> None:  # keine Konsolenausgabe
        pass

    def _token_ok(self) -> bool:
        q = parse_qs(urlparse(self.path).query)
        return self.remote.check_token(self.headers.get("X-Token") or (q.get("t") or [None])[0])

    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, data: dict) -> None:
        self._send(code, json.dumps(data, ensure_ascii=False).encode())

    def _seen(self) -> None:
        now = time.monotonic()
        self.remote.last_request = now
        self.remote.clients[self.client_address[0]] = now

    def do_GET(self) -> None:  # noqa: N802
        if not self._token_ok():
            self._send(403, "Zugriff verweigert – bitte den QR-Code aus AkustikMess verwenden.".encode(),
                       "text/plain; charset=utf-8")
            return
        path = urlparse(self.path).path
        self._seen()
        if path in ("/", "/index.html"):
            self._send(200, PAGE.encode(), "text/html; charset=utf-8")
        elif path == "/api/state":
            self._send(200, self.remote.snapshot())
        else:
            self._json(404, {"ok": False})

    def do_POST(self) -> None:  # noqa: N802
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        # Anfrage immer erst vollständig lesen: wer vorher antwortet und schließt, löst beim Absender
        # (vor allem unter Windows) einen Verbindungsabbruch statt der Fehlermeldung aus
        raw = self.rfile.read(length) if 0 < length <= MAX_BODY else b""
        if not self._token_ok():
            self._json(403, {"ok": False, "message": "Zugriff verweigert"})
            return
        if urlparse(self.path).path != "/api/cmd":
            self._json(404, {"ok": False})
            return
        if length <= 0 or length > MAX_BODY:
            self.close_connection = True
            self._json(400, {"ok": False, "message": "Ungültige Anfrage"})
            return
        try:
            body = json.loads(raw)
            action = str(body["action"])
            args = body.get("args") or {}
            if not isinstance(args, dict):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            self._json(400, {"ok": False, "message": "Ungültige Anfrage"})
            return
        self._seen()
        self._json(200, self.remote.submit(action, args))


def local_ipv4_addresses() -> list[str]:
    """IPv4-Adressen dieses Rechners im lokalen Netz (ohne Loopback)."""
    ips: list[str] = []
    try:  # bevorzugte Adresse: die der Standardroute (es wird nichts gesendet)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            ips.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except OSError:
        pass
    ips = [ip for ip in ips if not ip.startswith("169.254.")]
    # typische Heim-/Veranstaltungs-WLANs (192.168.x) zuerst; 10.x ist oft ein VPN-Tunnel
    rank = lambda ip: 0 if ip.startswith("192.168.") else 1 if ip.startswith("172.") else 2  # noqa: E731
    return sorted(ips, key=rank) or ["127.0.0.1"]
