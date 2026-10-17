"""Lizenzserver: Lizenzanfragen, Freigabe per E-Mail, geschützte Downloads (Docker-Container hinter Caddy).

Ablauf
------
1. Nutzer füllt auf der Website „Lizenz anfragen“ aus → ``POST /api/request``. Der Server speichert die Anfrage,
   schickt eine E-Mail mit Prüf-Link an die Lizenz-Adresse (AKM_ADMIN_EMAIL) und eine Eingangsbestätigung an
   den Nutzer.
2. Der Prüf-Link öffnet eine Seite mit Name und E-Mail; **erst ein Klick auf „Lizenz erteilen“** (POST) gibt
   frei. So kann ein Virenscanner, der Links in Mails automatisch öffnet, nichts versehentlich freigeben.
3. Nach der Freigabe erhält der Nutzer Lizenzschlüssel und einen **einmaligen Download-Link** (7 Tage gültig).
4. Mit gültiger Lizenz kann jederzeit erneut heruntergeladen werden: Website → Lizenzschlüssel oder
   E-Mail + Lizenz-ID → ``POST /api/redownload`` → neuer einmaliger Link. Das Programm lädt Updates mit dem
   Lizenzschlüssel im Header ``X-AKM-License``.

HTTP (nur über Caddy erreichbar)::

    POST /api/request          {"name","email","message","consent":true,"website":""}
    GET  /api/review?t=…       Prüfseite für die Freigabe   ·   POST /api/review (t, action=approve|reject)
    GET  /api/download?t=…     Download-Seite (einmaliger Link)
    GET  /api/file/<Datei>     Programmdatei – mit ?t=<Link-Token> (einmalig) oder Header X-AKM-License
    HEAD /api/file/<Datei>     Größe (ohne Lizenz, für die Online-Prüfung)
    POST /api/redownload       {"license": "AKM1…"} oder {"email","id"} → {"url": "/api/download?t=…"}
    GET  /api/revocations      signierte Sperrliste   ·   GET /api/health

Verwaltung auf dem Server::

    docker exec akmess-license python license_server.py requests            # offene Anfragen
    docker exec akmess-license python license_server.py approve L-XXXX      # freigeben (falls ohne E-Mail)
    docker exec akmess-license python license_server.py reject L-XXXX
    docker exec akmess-license python license_server.py link L-XXXX         # neuer Download-Link
    docker exec akmess-license python license_server.py list [--search TEXT]
    docker exec akmess-license python license_server.py revoke|unrevoke L-XXXX
    docker exec akmess-license python license_server.py delete --email a@b.de   # DSGVO-Löschung
    docker exec akmess-license python license_server.py stats | keygen

Umgebung: AKM_DATA (/data), AKM_WWW (/www – Veröffentlichungsordner, nur lesend), AKM_SITE, AKM_ADMIN_EMAIL,
SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM, AKM_PORT (8080).
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import html
import json
import os
import re
import secrets
import smtplib
import sqlite3
import sys
import threading
import time
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from akustik import licensing  # noqa: E402

ID_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
EMAIL_RE = re.compile(r"^[^@\s<>\"']{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}$")
FILE_RE = re.compile(r"^AkustikMess-[A-Za-z0-9.\-]+\.(zip|exe|pkg)$")
MAX_BODY = 8192
REVIEW_DAYS = 14                          # Prüf-Link für die Freigabe
LINK_DAYS = 7                             # einmaliger Download-Link nach Freigabe
REDOWNLOAD_MINUTES = 30                   # Link nach Eingabe des Lizenzschlüssels auf der Website
RATE_WINDOW_S, RATE_MAX = 600, 5          # je IP: 5 Anfragen in 10 Minuten
EMAIL_MAX_PER_DAY = 3                     # je E-Mail-Adresse

SCHEMA = """
CREATE TABLE IF NOT EXISTS licenses (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    plan TEXT NOT NULL,
    status TEXT NOT NULL,              -- requested | active | rejected | revoked | deleted
    token TEXT,
    verify_hash TEXT,
    created TEXT NOT NULL,
    verified TEXT,
    consent TEXT NOT NULL,
    revoked_reason TEXT
);
CREATE INDEX IF NOT EXISTS licenses_email ON licenses(email);
CREATE TABLE IF NOT EXISTS tokens (
    hash TEXT PRIMARY KEY,
    kind TEXT NOT NULL,                -- review | download
    license_id TEXT NOT NULL,
    created TEXT NOT NULL,
    expires TEXT NOT NULL,
    used TEXT
);
"""


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def now_iso() -> str:
    return now().isoformat(timespec="seconds")


def _hash(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


class Config:
    def __init__(self, env=os.environ):
        self.data = Path(env.get("AKM_DATA", "/data"))
        self.www = Path(env.get("AKM_WWW", "/www"))
        self.site = env.get("AKM_SITE", "https://akmess.alex-kulow.de").rstrip("/")
        self.admin = env.get("AKM_ADMIN_EMAIL", "").strip()
        self.port = int(env.get("AKM_PORT", "8080"))
        self.smtp = {k: env.get(f"SMTP_{k.upper()}", "") for k in ("host", "port", "user", "password", "from")}

    @property
    def db_path(self) -> Path:
        return self.data / "licenses.db"

    @property
    def key_path(self) -> Path:
        return self.data / "server_key.pem"

    @property
    def mail_enabled(self) -> bool:
        return bool(self.smtp["host"] and self.smtp["from"])


class Store:
    """Datenbank + Signaturschlüssel. Thread-sicher über eine Sperre (geringe Last)."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        cfg.data.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(cfg.db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        for col in ("message TEXT", "approved TEXT"):           # ältere Datenbanken erweitern
            try:
                self.db.execute(f"ALTER TABLE licenses ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass
        self.db.commit()
        self.lock = threading.Lock()
        self._key = None
        self._revocations: bytes | None = None

    # Schlüssel
    def key(self):
        from cryptography.hazmat.primitives import serialization  # noqa: PLC0415
        if self._key is None:
            if not self.cfg.key_path.exists():
                raise RuntimeError("Serverschlüssel fehlt – zuerst `license_server.py keygen` ausführen")
            self._key = serialization.load_pem_private_key(self.cfg.key_path.read_bytes(), password=None)
        return self._key

    def keygen(self) -> str:
        from cryptography.hazmat.primitives import serialization  # noqa: PLC0415
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: PLC0415
        if self.cfg.key_path.exists():
            raise RuntimeError(f"Schlüssel existiert bereits: {self.cfg.key_path}")
        key = Ed25519PrivateKey.generate()
        self.cfg.key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                                        serialization.PrivateFormat.PKCS8,
                                                        serialization.NoEncryption()))
        os.chmod(self.cfg.key_path, 0o600)
        return base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw,
                                                              serialization.PublicFormat.Raw)).decode()

    # Einmal-Token (nur Hash gespeichert)
    def new_token(self, kind: str, license_id: str, lifetime: dt.timedelta) -> str:
        tok = secrets.token_urlsafe(32)
        with self.lock:
            self.db.execute("INSERT INTO tokens (hash,kind,license_id,created,expires) VALUES (?,?,?,?,?)",
                            (_hash(tok), kind, license_id, now_iso(), (now() + lifetime).isoformat(timespec="seconds")))
            self.db.commit()
        return tok

    def check_token(self, tok: str, kind: str):
        """Gültiges, unbenutztes Token → Zeile mit license_id; sonst None."""
        row = self.db.execute("SELECT * FROM tokens WHERE hash=? AND kind=?", (_hash(tok), kind)).fetchone()
        if row is None or row["used"] or dt.datetime.fromisoformat(row["expires"]) < now():
            return None
        return row

    def use_token(self, tok: str) -> None:
        with self.lock:
            self.db.execute("UPDATE tokens SET used=? WHERE hash=?", (now_iso(), _hash(tok)))
            self.db.commit()

    # Lizenzen
    def _new_id(self) -> str:
        return "L-" + "".join(secrets.choice(ID_ALPHABET) for _ in range(12))

    def get(self, lic_id: str):
        return self.db.execute("SELECT * FROM licenses WHERE id=?", (lic_id,)).fetchone()

    def count_recent(self, email: str) -> int:
        since = (now() - dt.timedelta(days=1)).isoformat(timespec="seconds")
        return self.db.execute("SELECT COUNT(*) FROM licenses WHERE email=? AND created>=?",
                               (email, since)).fetchone()[0]

    def active_for(self, email: str):
        return self.db.execute("SELECT * FROM licenses WHERE email=? AND status='active' "
                               "ORDER BY created DESC LIMIT 1", (email,)).fetchone()

    def open_request_for(self, email: str):
        return self.db.execute("SELECT * FROM licenses WHERE email=? AND status='requested' "
                               "ORDER BY created DESC LIMIT 1", (email,)).fetchone()

    def request(self, name: str, email: str, message: str) -> str:
        with self.lock:
            lic_id = self._new_id()
            self.db.execute("INSERT INTO licenses (id,name,email,plan,status,created,consent,message) "
                            "VALUES (?,?,?,?,?,?,?,?)",
                            (lic_id, name, email, "community", "requested", now_iso(), now_iso(), message))
            self.db.commit()
        return lic_id

    def approve(self, lic_id: str) -> str | None:
        """Anfrage freigeben: Lizenz signieren und aktivieren. Liefert den Lizenzschlüssel."""
        with self.lock:
            row = self.get(lic_id)
            if row is None or row["status"] != "requested":
                return None
            payload = {"id": row["id"], "name": row["name"], "email": row["email"], "plan": "community",
                       "issued": dt.date.today().isoformat(), "expires": None, "updates_until": None,
                       "features": []}
            token = licensing.sign(payload, self.key(), "server")
            self.db.execute("UPDATE licenses SET status='active', token=?, approved=?, verified=? WHERE id=?",
                            (token, now_iso(), now_iso(), lic_id))
            self.db.commit()
            return token

    def reject(self, lic_id: str) -> bool:
        with self.lock:
            cur = self.db.execute("UPDATE licenses SET status='rejected' WHERE id=? AND status='requested'", (lic_id,))
            self.db.commit()
            return cur.rowcount > 0

    def revoke(self, lic_id: str, reason: str = "", undo: bool = False) -> bool:
        with self.lock:
            if undo:
                cur = self.db.execute("UPDATE licenses SET status='active', revoked_reason=NULL "
                                      "WHERE id=? AND status='revoked'", (lic_id,))
            else:
                cur = self.db.execute("UPDATE licenses SET status='revoked', revoked_reason=? WHERE id=?",
                                      (reason, lic_id))
            changed = cur.rowcount != 0
            if not changed and not undo and re.match(r"^L-[A-Z0-9]{4,32}$", lic_id):
                # offline (Root) ausgestellte Lizenz: nur für die Sperrliste eintragen
                self.db.execute("INSERT INTO licenses (id,name,email,plan,status,created,consent,revoked_reason) "
                                "VALUES (?,'(offline ausgestellt)','','offline','revoked',?,'',?)",
                                (lic_id, now_iso(), reason))
                changed = True
            self.db.commit()
            self._revocations = None
            return changed

    def license_ok(self, lic: licensing.License) -> bool:
        """Signatur ist schon geprüft; hier: nicht gesperrt/gelöscht (Root-Lizenzen stehen meist nicht in der DB)."""
        row = self.get(lic.id)
        return row is None or row["status"] == "active"

    def delete_person(self, email: str) -> int:
        """DSGVO: personenbezogene Daten löschen, Lizenz sperren (ID bleibt für die Sperrliste)."""
        with self.lock:
            cur = self.db.execute("UPDATE licenses SET name='', email='', token=NULL, verify_hash=NULL, message=NULL, "
                                  "status=CASE WHEN status IN ('active','revoked') THEN 'revoked' ELSE 'deleted' END, "
                                  "revoked_reason='gelöscht auf Wunsch' WHERE email=?", (email.lower(),))
            self.db.commit()
            self._revocations = None
            return cur.rowcount

    def cleanup(self) -> None:
        """Abgelaufene Token und nicht bearbeitete Anfragen (> 60 Tage) entfernen."""
        old = (now() - dt.timedelta(days=60)).isoformat(timespec="seconds")
        with self.lock:
            self.db.execute("DELETE FROM tokens WHERE expires<?", (now_iso(),))
            self.db.execute("DELETE FROM licenses WHERE status IN ('requested','rejected','pending') AND created<?",
                            (old,))
            self.db.commit()

    def revocations(self) -> bytes:
        with self.lock:
            if self._revocations is None:
                ids = [r[0] for r in self.db.execute("SELECT id FROM licenses WHERE status='revoked'")]
                self._revocations = licensing.sign_revocations(ids, self.key(), "server")
            return self._revocations

    # veröffentlichte Dateien
    def releases(self) -> list[dict]:
        """Neueste Datei je Kanal und System aus dem Release-Verzeichnis (Anzeige auf der Download-Seite)."""
        try:
            outer = json.loads((self.cfg.www / "releases.json").read_text(encoding="utf-8"))
            data = json.loads(outer["signed"])
        except Exception:  # noqa: BLE001
            return []
        out = []
        for ch in ("stable", "beta"):
            ver = data.get("channels", {}).get(ch)
            rel = next((r for r in data.get("releases", []) if r.get("version") == ver), None)
            for plat, asset in (rel or {}).get("assets", {}).items():
                if FILE_RE.match(asset.get("file", "")) and self.file_path(asset["file"]):
                    out.append({"channel": ch, "version": ver, "platform": plat, "file": asset["file"],
                                "size": asset.get("size", 0), "sha256": asset.get("sha256", "")})
        return out

    def file_path(self, name: str) -> Path | None:
        if not FILE_RE.match(name or ""):
            return None
        p = self.cfg.www / "files" / name
        return p if p.is_file() else None


# --- E-Mail -------------------------------------------------------------------------------

def send_mail(cfg: Config, to: str, subject: str, body: str, reply_to: str = "") -> None:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = cfg.smtp["from"], to, subject
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)
    port = int(cfg.smtp["port"] or 587)
    cls = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
    with cls(cfg.smtp["host"], port, timeout=20) as s:
        if port != 465:
            s.starttls()
        if cfg.smtp["user"]:
            s.login(cfg.smtp["user"], cfg.smtp["password"])
        s.send_message(msg)


def mail_admin(cfg, row, review_token):
    send_mail(cfg, cfg.admin, f"AkustikMess-Lizenzanfrage: {row['name']} <{row['email']}>",
              f"Neue Lizenzanfrage ({row['created'][:16].replace('T', ' ')} UTC)\n\n"
              f"Name:    {row['name']}\nE-Mail:  {row['email']}\nID:      {row['id']}\n"
              f"Angaben: {row['message'] or '–'}\n\n"
              f"Prüfen und freigeben (Link {REVIEW_DAYS} Tage gültig):\n{cfg.site}/api/review?t={review_token}\n\n"
              "Erst auf der Seite „Lizenz erteilen“ klicken – das Öffnen des Links allein gibt nichts frei.\n",
              reply_to=row["email"])


def mail_received(cfg, row):
    send_mail(cfg, row["email"], "AkustikMess: Lizenzanfrage eingegangen",
              f"Hallo {row['name']},\n\ndanke für deine Anfrage. Sobald die Lizenz freigegeben ist, bekommst du eine "
              "weitere E-Mail mit deinem Lizenzschlüssel und dem Download-Link.\n\n"
              f"Datenschutz: {cfg.site}/datenschutz.html\n")


def mail_license(cfg, row, license_token, download_token, again=False):
    intro = ("hier noch einmal dein Lizenzschlüssel und ein neuer Download-Link." if again
             else "deine Lizenz für AkustikMess ist freigegeben.")
    send_mail(cfg, row["email"], "Deine AkustikMess-Lizenz und Download",
              f"Hallo {row['name']},\n\n{intro}\n\n"
              f"Download (einmalig nutzbar, {LINK_DAYS} Tage gültig):\n{cfg.site}/api/download?t={download_token}\n\n"
              f"Lizenz-ID: {row['id']}\nLizenzschlüssel:\n{license_token}\n\n"
              "So trägst du ihn ein: AkustikMess → Hilfe → Lizenz… → Schlüssel einfügen → Übernehmen.\n"
              f"Später erneut herunterladen: {cfg.site}/#download → „Ich habe eine Lizenz“ (mit Lizenzschlüssel "
              "oder E-Mail-Adresse und Lizenz-ID).\n\n"
              "Bitte gib den Lizenzschlüssel nicht weiter.\n")


DEFAULT_MAILER = {"admin": mail_admin, "received": mail_received, "license": mail_license}


# --- HTTP ---------------------------------------------------------------------------------

class RateLimiter:
    def __init__(self, window=RATE_WINDOW_S, limit=RATE_MAX):
        self.window, self.limit, self.hits, self.lock = window, limit, {}, threading.Lock()

    def allow(self, key: str) -> bool:
        t = time.monotonic()
        with self.lock:
            hits = [h for h in self.hits.get(key, []) if t - h < self.window]
            ok = len(hits) < self.limit
            if ok:
                hits.append(t)
            self.hits[key] = hits
            if len(self.hits) > 10000:  # Speicher begrenzen
                self.hits = {k: v for k, v in self.hits.items() if v and t - v[-1] < self.window}
            return ok


PLATFORM_LABELS = {"windows": "Windows", "macos": "macOS", "linux": "Linux"}


def make_handler(store: Store, cfg: Config, limiter: RateLimiter, mailer=None):
    mailer = mailer or DEFAULT_MAILER

    def issue_download(row, again=False, lifetime=dt.timedelta(days=LINK_DAYS)) -> str:
        tok = store.new_token("download", row["id"], lifetime)
        if cfg.mail_enabled and row["email"]:
            try:
                mailer["license"](cfg, row, row["token"], tok, again)
            except Exception as exc:  # noqa: BLE001
                sys.stderr.write(f"E-Mail fehlgeschlagen: {exc}\n")
        return tok

    class Handler(BaseHTTPRequestHandler):
        server_version = "AkustikMess-Lizenz"
        sys_version = ""

        def log_message(self, fmt, *args):  # keine IP-Adressen und keine Token protokollieren
            sys.stderr.write(f"{self.log_date_time_string()} {self.command} {urlparse(self.path).path} "
                             f"{args[1] if len(args) > 1 else ''}\n")

        def _client(self) -> str:
            # Caddy setzt X-Forwarded-For; der Container ist nur über Caddy erreichbar
            return (self.headers.get("X-Forwarded-For", "").split(",")[-1].strip()
                    or self.client_address[0])

        def _send(self, code: int, body: bytes, ctype="application/json; charset=utf-8", cache="no-store"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")       # Token nicht an andere Seiten weitergeben
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, code: int, obj: dict):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

        def _page(self, code, title, body):
            page = (f'<!doctype html><html lang="de"><meta charset="utf-8"><meta name="viewport" '
                    f'content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">'
                    f'<title>{html.escape(title)} – AkustikMess</title>'
                    f'<link rel="stylesheet" href="/assets/style.css"><main class="wrap narrow"><h1>{html.escape(title)}</h1>'
                    f'{body}<p><a href="/">Zur Startseite</a></p></main></html>')
            self._send(code, page.encode("utf-8"), "text/html; charset=utf-8")

        def _body(self) -> bytes | None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = -1
            if not 0 < length <= MAX_BODY:
                return None
            return self.rfile.read(length)

        # --- GET/HEAD ---
        def do_HEAD(self):  # noqa: N802
            url = urlparse(self.path)
            if url.path.startswith("/api/file/"):
                p = store.file_path(unquote(url.path[len("/api/file/"):]))
                if p is None:
                    return self._send(404, b"")
                self.send_response(200)
                self.send_header("Content-Length", str(p.stat().st_size))
                self.send_header("Content-Type", "application/octet-stream")
                self.end_headers()
                return None
            return self._send(405, b"")

        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            q = parse_qs(url.query)
            t = (q.get("t") or [""])[0]
            if url.path == "/api/health":
                return self._json(200, {"ok": True})
            if url.path == "/api/revocations":
                return self._send(200, store.revocations(), cache="public, max-age=300")
            if url.path == "/api/review":
                return self._review_page(t)
            if url.path == "/api/download":
                return self._download_page(t)
            if url.path.startswith("/api/file/"):
                return self._file(unquote(url.path[len("/api/file/"):]), t)
            return self._json(404, {"error": "nicht gefunden"})

        def _review_page(self, t):
            tok = store.check_token(t, "review")
            row = store.get(tok["license_id"]) if tok else None
            if row is None:
                return self._page(410, "Link ungültig", "<p>Dieser Prüf-Link ist abgelaufen oder wurde bereits "
                                  "verwendet. Offene Anfragen: <code>license_server.py requests</code>.</p>")
            if row["status"] != "requested":
                return self._page(200, "Bereits bearbeitet", f"<p>Status: {html.escape(row['status'])}</p>")
            e = html.escape
            return self._page(200, "Lizenzanfrage prüfen", f"""
<table><tr><th>Name</th><td>{e(row['name'])}</td></tr><tr><th>E-Mail</th><td>{e(row['email'])}</td></tr>
<tr><th>Angaben</th><td>{e(row['message'] or '–')}</td></tr>
<tr><th>Eingang</th><td>{e(row['created'][:16].replace('T', ' '))} UTC</td></tr><tr><th>ID</th><td>{e(row['id'])}</td></tr></table>
<form method="post" action="/api/review"><input type="hidden" name="t" value="{e(t)}">
<p><button class="primary" name="action" value="approve">Lizenz erteilen und Download-Link senden</button></p>
<p><button name="action" value="reject">Ablehnen</button></p></form>""")

        def _download_page(self, t):
            tok = store.check_token(t, "download")
            if tok is None:
                return self._page(410, "Link nicht mehr gültig",
                                  "<p>Dieser Download-Link wurde bereits verwendet oder ist abgelaufen.</p><p>Mit deiner "
                                  'Lizenz kannst du jederzeit erneut herunterladen: <a href="/#download">Startseite → '
                                  "„Ich habe eine Lizenz“</a>.</p>")
            files = store.releases()
            if not files:
                return self._page(503, "Noch keine Version verfügbar", "<p>Bitte später erneut versuchen.</p>")
            e = html.escape
            items = "".join(
                f'<p><a class="primary" href="/api/file/{quote(f["file"])}?t={e(t)}">{e(PLATFORM_LABELS.get(f["platform"], f["platform"]))}'
                f' herunterladen – Version {e(f["version"])}{" (Beta)" if f["channel"] == "beta" else ""}'
                f' · {f["size"] / 1e6:.0f} MB</a></p>' for f in files)
            return self._page(200, "AkustikMess herunterladen",
                              "<p>Bitte die Datei für dein System wählen. <b>Der Link funktioniert nur für einen "
                              "Download</b>; danach kannst du mit deinem Lizenzschlüssel jederzeit erneut über die "
                              "Startseite herunterladen.</p>" + items +
                              '<p class="hint">Anleitung: <a href="/wiki/erste-schritte.html">Erste Schritte</a></p>')

        def _file(self, name, t):
            path = store.file_path(name)
            if path is None:
                return self._json(404, {"error": "Datei nicht gefunden"})
            via_token = False
            header = self.headers.get("X-AKM-License", "")
            if header:
                try:
                    lic = licensing.parse(header)
                except licensing.LicenseError:
                    return self._json(401, {"error": "Lizenz ungültig"})
                if not store.license_ok(lic):
                    return self._json(403, {"error": "Lizenz gesperrt"})
            elif store.check_token(t, "download"):
                via_token = True
            else:
                return self._page(403, "Download nur mit Lizenz",
                                  '<p>Der Link ist ungültig oder wurde bereits verwendet. <a href="/#download">Zur '
                                  "Download-Seite</a></p>")
            size = path.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", "application/zip" if name.endswith(".zip") else "application/octet-stream")
            self.send_header("Content-Length", str(size))
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            sent = 0
            try:
                with open(path, "rb") as fh:
                    while chunk := fh.read(1 << 20):
                        self.wfile.write(chunk)
                        sent += len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                return None
            if via_token and sent == size:
                store.use_token(t)            # erst nach vollständigem Download verbraucht
            return None

        # --- POST ---
        def do_POST(self):  # noqa: N802
            path = urlparse(self.path).path
            if path == "/api/review":
                return self._review_post()
            if path not in ("/api/request", "/api/redownload"):
                return self._json(404, {"error": "nicht gefunden"})
            if "application/json" not in self.headers.get("Content-Type", ""):
                return self._json(415, {"error": "JSON erwartet"})
            raw = self._body()
            if raw is None:
                return self._json(413, {"error": "Anfrage zu groß"})
            if not limiter.allow(path + self._client()):
                return self._json(429, {"error": "Zu viele Anfragen – bitte in einigen Minuten erneut versuchen."})
            try:
                data = json.loads(raw)
                assert isinstance(data, dict)
            except Exception:  # noqa: BLE001
                return self._json(400, {"error": "Ungültige Anfrage"})
            return self._request(data) if path == "/api/request" else self._redownload(data)

        def _request(self, data):
            if data.get("website"):           # Honigtopf-Feld: nur Bots füllen es aus
                return self._json(200, {"status": "requested"})
            name = " ".join(str(data.get("name", "")).split())[:100]
            email = str(data.get("email", "")).strip().lower()[:254]
            message = " ".join(str(data.get("message", "")).split())[:500]
            if len(name) < 2:
                return self._json(400, {"error": "Bitte einen Namen angeben."})
            if not EMAIL_RE.match(email):
                return self._json(400, {"error": "Bitte eine gültige E-Mail-Adresse angeben."})
            if data.get("consent") is not True:
                return self._json(400, {"error": "Bitte der Datenschutzerklärung zustimmen."})
            if store.count_recent(email) >= EMAIL_MAX_PER_DAY:
                return self._json(429, {"error": "Für diese Adresse wurden heute schon mehrere Anfragen gestellt."})
            store.cleanup()
            existing = store.active_for(email)
            if existing:                     # schon lizenziert: Schlüssel + neuen Link an diese Adresse
                issue_download(existing, again=True)
            elif not store.open_request_for(email):
                lic_id = store.request(name, email, message)
                row = store.get(lic_id)
                review = store.new_token("review", lic_id, dt.timedelta(days=REVIEW_DAYS))
                if cfg.mail_enabled:
                    try:
                        if cfg.admin:
                            mailer["admin"](cfg, row, review)
                        mailer["received"](cfg, row)
                    except Exception as exc:  # noqa: BLE001 – Anfrage bleibt gespeichert (CLI: requests)
                        sys.stderr.write(f"E-Mail fehlgeschlagen: {exc}\n")
            # immer gleiche Antwort: verrät nicht, ob die Adresse schon bekannt ist
            return self._json(200, {"status": "requested"})

        def _redownload(self, data):
            row = None
            key = "".join(str(data.get("license", "")).split())
            if key:
                try:
                    lic = licensing.parse(key)
                except licensing.LicenseError:
                    return self._json(400, {"error": "Der Lizenzschlüssel ist ungültig (vollständig kopiert?)."})
                if not store.license_ok(lic):
                    return self._json(403, {"error": "Diese Lizenz ist gesperrt."})
                row = store.get(lic.id) or {"id": lic.id, "email": "", "name": lic.name, "token": key}
            else:
                email = str(data.get("email", "")).strip().lower()
                lic_id = str(data.get("id", "")).strip().upper()
                cand = store.get(lic_id) if re.match(r"^L-[A-Z0-9]{4,32}$", lic_id) else None
                if cand is None or cand["status"] != "active" or cand["email"] != email:
                    return self._json(403, {"error": "Keine aktive Lizenz zu dieser E-Mail-Adresse und Lizenz-ID."})
                row = cand
            tok = store.new_token("download", row["id"], dt.timedelta(minutes=REDOWNLOAD_MINUTES))
            return self._json(200, {"url": f"/api/download?t={tok}"})

        def _review_post(self):
            raw = self._body()
            if raw is None:
                return self._page(400, "Ungültige Anfrage", "")
            form = parse_qs(raw.decode("utf-8", "replace"))
            t, action = (form.get("t") or [""])[0], (form.get("action") or [""])[0]
            tok = store.check_token(t, "review")
            if tok is None:
                return self._page(410, "Link ungültig", "<p>Abgelaufen oder bereits verwendet.</p>")
            lic_id = tok["license_id"]
            store.use_token(t)
            if action == "reject":
                store.reject(lic_id)
                return self._page(200, "Abgelehnt", "<p>Die Anfrage wurde abgelehnt. Der Nutzer wird nicht "
                                  "automatisch benachrichtigt.</p>")
            if action != "approve" or store.approve(lic_id) is None:
                return self._page(409, "Nicht möglich", "<p>Die Anfrage wurde bereits bearbeitet.</p>")
            row = store.get(lic_id)
            issue_download(row)
            mail = "per E-Mail gesendet" if cfg.mail_enabled else "NICHT gesendet (E-Mail nicht eingerichtet)"
            return self._page(200, "Lizenz erteilt", f"<p>Lizenz {html.escape(lic_id)} für "
                              f"{html.escape(row['name'])} &lt;{html.escape(row['email'])}&gt; ist aktiv. "
                              f"Lizenzschlüssel und Download-Link wurden {mail}.</p>")

    return Handler


def serve(cfg: Config) -> None:
    store = Store(cfg)
    store.key()  # früh scheitern, wenn der Schlüssel fehlt
    srv = ThreadingHTTPServer(("0.0.0.0", cfg.port), make_handler(store, cfg, RateLimiter()))  # noqa: S104
    print(f"Lizenzserver auf Port {cfg.port} (E-Mail: {'an' if cfg.mail_enabled else 'aus'}, "
          f"Anfragen an: {cfg.admin or '– (AKM_ADMIN_EMAIL fehlt)'})", flush=True)
    srv.serve_forever()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="AkustikMess-Lizenzserver", epilog=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve")
    sub.add_parser("keygen")
    sub.add_parser("requests")
    for name in ("approve", "reject", "link", "unrevoke"):
        sub.add_parser(name).add_argument("id")
    p = sub.add_parser("list")
    p.add_argument("--search", default="")
    p = sub.add_parser("revoke")
    p.add_argument("id")
    p.add_argument("--reason", default="")
    p = sub.add_parser("delete")
    p.add_argument("--email", required=True)
    sub.add_parser("stats")
    args = ap.parse_args(argv)
    cfg = Config()
    if args.cmd == "serve":
        serve(cfg)
        return 0
    store = Store(cfg)
    if args.cmd == "keygen":
        print("Öffentlicher Schlüssel (auf dem Entwicklungsrechner eintragen mit\n"
              "  python tools/licenses.py set-server-key --public <SCHLÜSSEL>):\n\n" + store.keygen())
    elif args.cmd == "requests":
        for r in store.db.execute("SELECT * FROM licenses WHERE status='requested' ORDER BY created"):
            print(f"{r['id']}  {r['created'][:16]}  {r['name']} <{r['email']}>  {r['message'] or ''}")
    elif args.cmd in ("approve", "link"):
        if args.cmd == "approve" and store.approve(args.id) is None:
            print("Keine offene Anfrage mit dieser ID.")
            return 1
        row = store.get(args.id)
        if row is None or row["status"] != "active":
            print("Keine aktive Lizenz mit dieser ID.")
            return 1
        tok = store.new_token("download", row["id"], dt.timedelta(days=LINK_DAYS))
        sent = False
        if cfg.mail_enabled:
            try:
                mail_license(cfg, row, row["token"], tok, again=args.cmd == "link")
                sent = True
            except Exception as exc:  # noqa: BLE001
                print(f"E-Mail fehlgeschlagen: {exc}")
        print(f"{row['name']} <{row['email']}> – {'E-Mail gesendet' if sent else 'bitte selbst zusenden'}:\n"
              f"Download: {cfg.site}/api/download?t={tok}\nLizenzschlüssel:\n{row['token']}")
    elif args.cmd == "reject":
        print("Abgelehnt." if store.reject(args.id) else "Keine offene Anfrage mit dieser ID.")
    elif args.cmd == "list":
        q = f"%{args.search.lower()}%"
        for r in store.db.execute("SELECT * FROM licenses WHERE lower(id||name||email) LIKE ? ORDER BY created", (q,)):
            print(f"{r['id']}  {r['created'][:10]}  {r['plan']:<10} {r['status']:<9} {r['name']} <{r['email']}>")
    elif args.cmd in ("revoke", "unrevoke"):
        ok = store.revoke(args.id, getattr(args, "reason", ""), undo=args.cmd == "unrevoke")
        print(("Erledigt: " if ok else "Nicht gefunden: ") + args.id)
    elif args.cmd == "delete":
        print(f"{store.delete_person(args.email)} Eintrag/Einträge gelöscht und gesperrt.")
    elif args.cmd == "stats":
        for r in store.db.execute("SELECT plan, status, COUNT(*) n FROM licenses GROUP BY plan, status"):
            print(f"{r['plan']:<10} {r['status']:<9} {r['n']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
