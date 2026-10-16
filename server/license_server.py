"""Lizenzserver für die kostenlose Registrierung (läuft als Docker-Container hinter Caddy).

HTTP (nur über Caddy erreichbar, Pfad /api/…):

    POST /api/register      {"name", "email", "consent": true, "website": ""}  → Bestätigungs-E-Mail
                            (ohne SMTP-Konfiguration: Schlüssel direkt in der Antwort)
    GET  /api/verify?t=…    E-Mail bestätigt → Lizenz ausstellen, anzeigen und zusenden
    GET  /api/revocations   signierte Sperrliste für die Programme
    GET  /api/health

Verwaltung nur auf dem Server (keine Admin-Schnittstelle im Netz)::

    docker exec akmess-license python license_server.py list [--search TEXT]
    docker exec akmess-license python license_server.py revoke L-XXXX   [--reason TEXT]
    docker exec akmess-license python license_server.py unrevoke L-XXXX
    docker exec akmess-license python license_server.py delete --email a@b.de   # DSGVO-Löschung
    docker exec akmess-license python license_server.py stats
    docker exec akmess-license python license_server.py keygen   # einmalig, gibt öffentlichen Schlüssel aus

Umgebungsvariablen: AKM_DATA (Ordner für Datenbank + Schlüssel, Standard /data), AKM_SITE (öffentliche
Adresse), SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM (optional), AKM_PORT (Standard 8080).
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
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from akustik import licensing  # noqa: E402

ID_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
EMAIL_RE = re.compile(r"^[^@\s<>\"']{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}$")
MAX_BODY = 4096
VERIFY_HOURS = 48
RATE_WINDOW_S, RATE_MAX = 600, 5          # je IP: 5 Registrierungen in 10 Minuten
EMAIL_MAX_PER_DAY = 3                     # je E-Mail-Adresse

SCHEMA = """
CREATE TABLE IF NOT EXISTS licenses (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    plan TEXT NOT NULL,
    status TEXT NOT NULL,              -- pending | active | revoked | deleted
    token TEXT,
    verify_hash TEXT,
    created TEXT NOT NULL,
    verified TEXT,
    consent TEXT NOT NULL,
    revoked_reason TEXT
);
CREATE INDEX IF NOT EXISTS licenses_email ON licenses(email);
"""


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


class Config:
    def __init__(self, env=os.environ):
        self.data = Path(env.get("AKM_DATA", "/data"))
        self.site = env.get("AKM_SITE", "https://akmess.alex-kulow.de").rstrip("/")
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

    # Lizenzen
    def _new_id(self) -> str:
        return "L-" + "".join(secrets.choice(ID_ALPHABET) for _ in range(12))

    def count_recent(self, email: str) -> int:
        since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).isoformat(timespec="seconds")
        return self.db.execute("SELECT COUNT(*) FROM licenses WHERE email=? AND created>=?",
                               (email, since)).fetchone()[0]

    def active_for(self, email: str):
        return self.db.execute("SELECT * FROM licenses WHERE email=? AND status='active' AND plan='community' "
                               "ORDER BY created DESC LIMIT 1", (email,)).fetchone()

    def create(self, name: str, email: str, pending: bool) -> tuple[str, str | None]:
        """Neue Lizenz. pending=True: Bestätigungscode zurück; sonst sofort ausgestellt (Schlüssel zurück)."""
        with self.lock:
            lic_id, code = self._new_id(), secrets.token_urlsafe(32)
            self.db.execute(
                "INSERT INTO licenses (id,name,email,plan,status,verify_hash,created,consent) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (lic_id, name, email, "community", "pending", hashlib.sha256(code.encode()).hexdigest(),
                 now_iso(), now_iso()))
            self.db.commit()
        if pending:
            return lic_id, code
        return lic_id, self.activate(code)

    def activate(self, code: str) -> str | None:
        h = hashlib.sha256((code or "").encode()).hexdigest()
        with self.lock:
            row = self.db.execute("SELECT * FROM licenses WHERE verify_hash=? AND status='pending'", (h,)).fetchone()
            if row is None:
                return None
            created = dt.datetime.fromisoformat(row["created"])
            if dt.datetime.now(dt.timezone.utc) - created > dt.timedelta(hours=VERIFY_HOURS):
                return None
            payload = {"id": row["id"], "name": row["name"], "email": row["email"], "plan": "community",
                       "issued": dt.date.today().isoformat(), "expires": None, "updates_until": None,
                       "features": []}
            token = licensing.sign(payload, self.key(), "server")
            self.db.execute("UPDATE licenses SET status='active', token=?, verify_hash=NULL, verified=? WHERE id=?",
                            (token, now_iso(), row["id"]))
            self.db.commit()
            return token

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

    def delete_person(self, email: str) -> int:
        """DSGVO: personenbezogene Daten löschen, Lizenz sperren (ID bleibt für die Sperrliste)."""
        with self.lock:
            cur = self.db.execute("UPDATE licenses SET name='', email='', token=NULL, verify_hash=NULL, "
                                  "status=CASE WHEN status IN ('active','revoked') THEN 'revoked' ELSE 'deleted' END, "
                                  "revoked_reason='gelöscht auf Wunsch' WHERE email=?", (email.lower(),))
            self.db.commit()
            self._revocations = None
            return cur.rowcount

    def cleanup_pending(self) -> None:
        cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=VERIFY_HOURS)).isoformat(timespec="seconds")
        with self.lock:
            self.db.execute("DELETE FROM licenses WHERE status='pending' AND created<?", (cutoff,))
            self.db.commit()

    def revocations(self) -> bytes:
        with self.lock:
            if self._revocations is None:
                ids = [r[0] for r in self.db.execute("SELECT id FROM licenses WHERE status='revoked'")]
                self._revocations = licensing.sign_revocations(ids, self.key(), "server")
            return self._revocations


# --- E-Mail -------------------------------------------------------------------------------

def send_mail(cfg: Config, to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = cfg.smtp["from"], to, subject
    msg.set_content(body)
    port = int(cfg.smtp["port"] or 587)
    cls = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
    with cls(cfg.smtp["host"], port, timeout=20) as s:
        if port != 465:
            s.starttls()
        if cfg.smtp["user"]:
            s.login(cfg.smtp["user"], cfg.smtp["password"])
        s.send_message(msg)


def mail_verify(cfg, to, name, code):
    send_mail(cfg, to, "AkustikMess: E-Mail-Adresse bestätigen",
              f"Hallo {name},\n\nbitte bestätige deine Registrierung für AkustikMess:\n\n"
              f"{cfg.site}/api/verify?t={code}\n\nDer Link ist {VERIFY_HOURS} Stunden gültig. Wenn du dich nicht "
              "registriert hast, ignoriere diese E-Mail einfach – es wird dann nichts gespeichert.\n")


def mail_license(cfg, to, name, token):
    send_mail(cfg, to, "Dein AkustikMess-Lizenzschlüssel",
              f"Hallo {name},\n\ndanke für deine Registrierung. Dein kostenloser Lizenzschlüssel:\n\n{token}\n\n"
              "So trägst du ihn ein: AkustikMess → Hilfe → Lizenz… → Schlüssel einfügen.\n\n"
              f"Datenschutz und Löschung: {cfg.site}/datenschutz.html\n")


# --- HTTP ---------------------------------------------------------------------------------

class RateLimiter:
    def __init__(self, window=RATE_WINDOW_S, limit=RATE_MAX):
        self.window, self.limit, self.hits, self.lock = window, limit, {}, threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self.lock:
            hits = [t for t in self.hits.get(key, []) if now - t < self.window]
            ok = len(hits) < self.limit
            if ok:
                hits.append(now)
            self.hits[key] = hits
            if len(self.hits) > 10000:  # Speicher begrenzen
                self.hits = {k: v for k, v in self.hits.items() if v and now - v[-1] < self.window}
            return ok


def make_handler(store: Store, cfg: Config, limiter: RateLimiter, mailer=None):
    mailer = mailer or {"verify": mail_verify, "license": mail_license}

    class Handler(BaseHTTPRequestHandler):
        server_version = "AkustikMess-Lizenz"
        sys_version = ""

        def log_message(self, fmt, *args):  # keine IP-Adressen protokollieren
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
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj: dict):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            if url.path == "/api/health":
                return self._json(200, {"ok": True})
            if url.path == "/api/revocations":
                return self._send(200, store.revocations(), cache="public, max-age=300")
            if url.path == "/api/verify":
                code = (parse_qs(url.query).get("t") or [""])[0]
                if not limiter.allow("verify:" + self._client()):
                    return self._page(429, "Zu viele Versuche", "<p>Bitte später erneut versuchen.</p>")
                token = store.activate(code)
                if token is None:
                    return self._page(400, "Link ungültig",
                                      "<p>Der Link ist abgelaufen oder wurde schon benutzt. Bitte "
                                      f'<a href="{html.escape(cfg.site)}/registrieren.html">erneut registrieren</a>.</p>')
                row = store.db.execute("SELECT id, name, email FROM licenses WHERE token=?", (token,)).fetchone()
                try:
                    mailer["license"](cfg, row["email"], row["name"], token)
                except Exception as exc:  # noqa: BLE001 – Lizenz trotzdem anzeigen
                    sys.stderr.write(f"E-Mail fehlgeschlagen: {exc}\n")
                return self._page(200, "Registrierung abgeschlossen",
                                  "<p>Danke! Dein kostenloser Lizenzschlüssel (auch per E-Mail unterwegs):</p>"
                                  f'<textarea class="key" readonly rows="6">{html.escape(token)}</textarea>'
                                  "<p>In AkustikMess: <b>Hilfe → Lizenz…</b> → Schlüssel einfügen.</p>"
                                  + f"<p>Lizenz-ID: {html.escape(row['id'])}</p>")
            return self._json(404, {"error": "nicht gefunden"})

        def _page(self, code, title, body):
            page = (f'<!doctype html><html lang="de"><meta charset="utf-8"><meta name="viewport" '
                    f'content="width=device-width,initial-scale=1"><title>{html.escape(title)} – AkustikMess</title>'
                    f'<link rel="stylesheet" href="/assets/style.css"><main class="narrow"><h1>{html.escape(title)}</h1>'
                    f'{body}<p><a href="/">Zur Startseite</a></p></main></html>')
            self._send(code, page.encode("utf-8"), "text/html; charset=utf-8")

        def do_POST(self):  # noqa: N802
            if urlparse(self.path).path != "/api/register":
                return self._json(404, {"error": "nicht gefunden"})
            if "application/json" not in self.headers.get("Content-Type", ""):
                return self._json(415, {"error": "JSON erwartet"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = -1
            if not 0 < length <= MAX_BODY:
                return self._json(413, {"error": "Anfrage zu groß"})
            if not limiter.allow("reg:" + self._client()):
                return self._json(429, {"error": "Zu viele Anfragen – bitte in einigen Minuten erneut versuchen."})
            try:
                data = json.loads(self.rfile.read(length))
                assert isinstance(data, dict)
            except Exception:  # noqa: BLE001
                return self._json(400, {"error": "Ungültige Anfrage"})
            if data.get("website"):           # Honigtopf-Feld: nur Bots füllen es aus
                return self._json(200, {"status": "verify_sent"})
            name = " ".join(str(data.get("name", "")).split())[:100]
            email = str(data.get("email", "")).strip().lower()[:254]
            if len(name) < 2:
                return self._json(400, {"error": "Bitte einen Namen angeben."})
            if not EMAIL_RE.match(email):
                return self._json(400, {"error": "Bitte eine gültige E-Mail-Adresse angeben."})
            if data.get("consent") is not True:
                return self._json(400, {"error": "Bitte der Datenschutzerklärung zustimmen."})
            if store.count_recent(email) >= EMAIL_MAX_PER_DAY:
                return self._json(429, {"error": "Für diese Adresse wurden heute schon mehrere Anfragen gestellt."})
            store.cleanup_pending()
            if cfg.mail_enabled:
                existing = store.active_for(email)
                try:
                    if existing:              # Schlüssel erneut zusenden statt neu ausstellen
                        mailer["license"](cfg, email, existing["name"], existing["token"])
                    else:
                        _, code = store.create(name, email, pending=True)
                        mailer["verify"](cfg, email, name, code)
                except Exception as exc:  # noqa: BLE001
                    sys.stderr.write(f"E-Mail fehlgeschlagen: {exc}\n")
                    return self._json(503, {"error": "E-Mail konnte nicht gesendet werden. Bitte später erneut."})
                # gleiche Antwort in beiden Fällen: verrät nicht, ob die Adresse schon registriert ist
                return self._json(200, {"status": "verify_sent"})
            lic_id, token = store.create(name, email, pending=False)
            return self._json(200, {"status": "issued", "id": lic_id, "license": token})

    return Handler


def serve(cfg: Config) -> None:
    store = Store(cfg)
    store.key()  # früh scheitern, wenn der Schlüssel fehlt
    srv = ThreadingHTTPServer(("0.0.0.0", cfg.port), make_handler(store, cfg, RateLimiter()))  # noqa: S104
    print(f"Lizenzserver auf Port {cfg.port} (E-Mail: {'an' if cfg.mail_enabled else 'aus'})", flush=True)
    srv.serve_forever()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="AkustikMess-Lizenzserver", epilog=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve")
    sub.add_parser("keygen")
    p = sub.add_parser("list")
    p.add_argument("--search", default="")
    p = sub.add_parser("revoke")
    p.add_argument("id")
    p.add_argument("--reason", default="")
    p = sub.add_parser("unrevoke")
    p.add_argument("id")
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
    elif args.cmd == "list":
        q = f"%{args.search.lower()}%"
        for r in store.db.execute("SELECT * FROM licenses WHERE lower(id||name||email) LIKE ? ORDER BY created", (q,)):
            print(f"{r['id']}  {r['created'][:10]}  {r['plan']:<10} {r['status']:<8} {r['name']} <{r['email']}>")
    elif args.cmd in ("revoke", "unrevoke"):
        ok = store.revoke(args.id, getattr(args, "reason", ""), undo=args.cmd == "unrevoke")
        print(("Erledigt: " if ok else "Nicht gefunden: ") + args.id)
    elif args.cmd == "delete":
        print(f"{store.delete_person(args.email)} Eintrag/Einträge gelöscht und gesperrt.")
    elif args.cmd == "stats":
        for r in store.db.execute("SELECT plan, status, COUNT(*) n FROM licenses GROUP BY plan, status"):
            print(f"{r['plan']:<10} {r['status']:<8} {r['n']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
