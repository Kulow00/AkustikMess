"""Upload des Veröffentlichungsordners per SFTP (nur für den Release-Rechner).

Sicherheit
----------
* Anmeldung nur per SSH-Schlüssel (eigener Upload-Schlüssel unter ~/.akustikmess/),
  nie per Passwort.
* Der Server wird an seinem Host-Schlüssel erkannt. Der Fingerabdruck wird beim
  Einrichten einmal bestätigt und gespeichert; ändert er sich später, bricht der
  Upload ab (Schutz gegen Abfangen der Verbindung).

Reihenfolge
-----------
Zuerst alle Installer und Seiten, ganz zuletzt ``releases.json``. Jede Datei wird
erst unter einem temporären Namen hochgeladen, geprüft und dann umbenannt – ein
Programm, das gerade nach Updates sucht, sieht also nie eine halbe Datei oder
einen Verweis auf einen noch fehlenden Installer.
"""

from __future__ import annotations

import base64
import hashlib
import json
import posixpath
import socket
import time
from pathlib import Path

STATE_DIR = Path.home() / ".akustikmess"
DEPLOY_KEY = STATE_DIR / "deploy_key"
KNOWN_HOSTS = STATE_DIR / "known_hosts"
UPLOAD_STATE = STATE_DIR / "upload_state.json"
LAST_FILES = ("index.html", "releases.json")  # in dieser Reihenfolge ganz am Ende
CHUNK = 256 * 1024
RESUME_CHECK = 64 * 1024     # so viele Bytes vor der Abbruchstelle werden beim Fortsetzen verglichen
RETRIES = 4                  # Versuche pro Datei bei Verbindungsabbruch


class DeployError(Exception):
    pass


# --- Upload-Schlüssel ------------------------------------------------------------------

def generate_deploy_key(path: Path = DEPLOY_KEY, force: bool = False, comment: str | None = None) -> str:
    """Erzeugt einen Ed25519-SSH-Schlüssel und liefert die öffentliche Zeile für authorized_keys."""
    from cryptography.hazmat.primitives import serialization  # noqa: PLC0415
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: PLC0415

    if path.exists() and not force:
        return public_key_line(path, comment)
    key = Ed25519PrivateKey.generate()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                                       serialization.NoEncryption()))
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return public_key_line(path, comment)


def public_key_line(path: Path = DEPLOY_KEY, comment: str | None = None) -> str:
    from cryptography.hazmat.primitives import serialization  # noqa: PLC0415
    if not path.exists():
        raise DeployError(f"Upload-Schlüssel fehlt: {path} (mit `release.py deploy-key` erzeugen)")
    key = serialization.load_ssh_private_key(path.read_bytes(), password=None)
    pub = key.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
    return f"{pub.decode()} {comment or 'akmess-deploy@' + socket.gethostname()}"


# --- Server-Erkennung ---------------------------------------------------------------------

def fingerprint(key) -> str:
    """OpenSSH-Darstellung, z. B. SHA256:abc… (wie `ssh-keygen -lf`)."""
    return "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")


def _host_id(host: str, port: int) -> str:
    return host if port == 22 else f"[{host}]:{port}"


def fetch_host_key(host: str, port: int = 22, timeout: float = 10):
    import paramiko  # noqa: PLC0415
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
    except OSError as exc:
        raise DeployError(f"Server {host}:{port} nicht erreichbar: {exc}") from exc
    t = paramiko.Transport(sock)
    try:
        t.start_client(timeout=timeout)
        return t.get_remote_server_key()
    finally:
        t.close()


def trust_host(host: str, port: int, expected_fingerprint: str, known_hosts: Path = KNOWN_HOSTS) -> str:
    """Speichert den Host-Schlüssel, wenn sein Fingerabdruck dem bestätigten entspricht."""
    import paramiko  # noqa: PLC0415
    key = fetch_host_key(host, port)
    fp = fingerprint(key)
    if fp != expected_fingerprint.strip():
        raise DeployError(f"Fingerabdruck stimmt nicht überein!\n  Server meldet: {fp}\n  erwartet:      "
                          f"{expected_fingerprint}\nNicht fortfahren, solange das nicht geklärt ist.")
    hk = paramiko.HostKeys()
    if known_hosts.exists():
        hk.load(str(known_hosts))
    hk.add(_host_id(host, port), key.get_name(), key)
    known_hosts.parent.mkdir(parents=True, exist_ok=True)
    hk.save(str(known_hosts))
    return fp


# --- Verbindung ---------------------------------------------------------------------------------

class SFTP:
    def __init__(self, cfg: dict, key_file: Path = DEPLOY_KEY, known_hosts: Path = KNOWN_HOSTS,
                 timeout: float = 20):
        import paramiko  # noqa: PLC0415
        if not known_hosts.exists():
            raise DeployError("Server noch nicht bestätigt: zuerst `release.py sftp-setup` ausführen.")
        self.cfg = cfg
        self.client = paramiko.SSHClient()
        self.client.load_host_keys(str(known_hosts))
        self.client.set_missing_host_key_policy(paramiko.RejectPolicy())  # unbekannter Server → Abbruch
        try:
            self.client.connect(cfg["host"], port=int(cfg.get("port", 22)), username=cfg["user"],
                                key_filename=str(key_file), look_for_keys=False, allow_agent=False,
                                timeout=timeout, banner_timeout=timeout, auth_timeout=timeout)
        except paramiko.BadHostKeyException as exc:
            raise DeployError("ACHTUNG: Der Server meldet einen ANDEREN Host-Schlüssel als bestätigt. "
                              "Upload abgebrochen (mögliches Abfangen der Verbindung oder Server neu "
                              "installiert – vor einem erneuten `sftp-setup` beim Server prüfen).") from exc
        except paramiko.SSHException as exc:
            raise DeployError(f"Anmeldung am Server fehlgeschlagen: {exc}\n(Ist der öffentliche Upload-"
                              "Schlüssel eingetragen? Server: /etc/ssh/authorized_keys/<benutzer>, "
                              "siehe docs/server-einrichtung.md; sonst ~/.ssh/authorized_keys)") from exc
        except OSError as exc:
            raise DeployError(f"Server nicht erreichbar: {exc}") from exc
        self.client.get_transport().set_keepalive(15)  # Verbindung bei langen Uploads wachhalten
        self.sftp = self.client.open_sftp()
        self.root = cfg["remote_dir"].rstrip("/") or "/"

    def close(self) -> None:
        self.sftp.close()
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _mkdirs(self, remote_dir: str) -> None:
        parts = [p for p in remote_dir.split("/") if p]
        cur = "/" if remote_dir.startswith("/") else ""
        for p in parts:
            cur = posixpath.join(cur, p)
            try:
                self.sftp.stat(cur)
            except OSError:
                self.sftp.mkdir(cur)

    def _resume_offset(self, local: Path, tmp: str, size: int) -> int:
        """Wie viel von ``tmp`` schon passend auf dem Server liegt (0 = neu beginnen)."""
        try:
            offset = self.sftp.stat(tmp).st_size
        except OSError:
            return 0
        if not 0 < offset <= size:
            return 0
        # Sicherheitsprüfung: das Ende des bereits Hochgeladenen muss exakt zur lokalen Datei passen
        n = min(RESUME_CHECK, offset)
        with open(local, "rb") as fh, self.sftp.open(tmp, "rb") as rf:
            fh.seek(offset - n)
            rf.seek(offset - n)
            if fh.read(n) != rf.read(n):
                return 0
        return offset

    def put_atomic(self, local: Path, remote_rel: str, progress=None) -> None:
        remote = posixpath.join(self.root, remote_rel)
        self._mkdirs(posixpath.dirname(remote))
        tmp = remote + ".part"
        size = local.stat().st_size
        offset = self._resume_offset(local, tmp, size)
        with open(local, "rb") as src, self.sftp.open(tmp, "r+b" if offset else "wb") as dst:
            dst.set_pipelined(True)
            src.seek(offset)
            dst.seek(offset)
            done = offset
            if progress:
                progress(done, size, offset)
            while True:
                chunk = src.read(CHUNK)
                if not chunk:
                    break
                dst.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, size, offset)
        if self.sftp.stat(tmp).st_size != size:
            raise DeployError(f"Upload von {remote_rel} unvollständig")
        try:
            self.sftp.posix_rename(tmp, remote)  # atomar ersetzen (OpenSSH)
        except OSError:
            try:
                self.sftp.remove(remote)
            except OSError:
                pass
            self.sftp.rename(tmp, remote)

    def check_writable(self) -> None:
        self._mkdirs(self.root)
        probe = posixpath.join(self.root, ".akmess-schreibtest")
        with self.sftp.open(probe, "w") as fh:
            fh.write("ok")
        self.sftp.remove(probe)


# --- Synchronisieren ---------------------------------------------------------------------------

def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def plan_upload(publish_dir: Path, state: dict) -> list[str]:
    """Geänderte Dateien (relativ, „/“-getrennt) in sicherer Reihenfolge."""
    files = sorted(p.relative_to(publish_dir).as_posix() for p in publish_dir.rglob("*")
                   if p.is_file() and not p.name.startswith("."))
    changed = [f for f in files if state.get(f) != _sha(publish_dir / f)]
    first = [f for f in changed if f not in LAST_FILES]
    last = [f for f in LAST_FILES if f in changed]
    return first + last


class _Progress:
    """Fortschritt großer Dateien: höchstens alle 2 s eine Zeile mit %, MB/s und Restzeit."""

    def __init__(self, log, min_size: int = 2_000_000):
        self.log, self.min_size = log, min_size
        self.start = self.last = 0.0

    def __call__(self, done: int, total: int, offset: int) -> None:
        if total < self.min_size:
            return
        now = time.monotonic()
        if done == offset:  # Beginn (oder Fortsetzung)
            self.start = self.last = now
            if offset:
                self.log(f"    setze bei {offset / 1e6:.1f} MB fort ({100 * offset / total:.0f} %)")
            return
        if now - self.last < 2 and done < total:
            return
        self.last = now
        rate = (done - offset) / max(now - self.start, 1e-6)
        rest = (total - done) / rate if rate > 0 else 0
        self.log(f"    {100 * done / total:3.0f} %  ·  {done / 1e6:5.1f}/{total / 1e6:.1f} MB  ·  "
                 f"{rate / 1e6:.2f} MB/s  ·  noch {int(rest // 60)}:{int(rest % 60):02d}")


def upload(cfg: dict, publish_dir: Path, log=print, state_file: Path = UPLOAD_STATE,
           connect=None, force: bool = False, retry_wait: float = 3.0) -> list[str]:
    """Lädt alle neuen/geänderten Dateien hoch. Liefert die Liste der hochgeladenen Dateien.

    Bricht die Verbindung ab, wird neu verbunden und die Datei ab der Abbruchstelle
    fortgesetzt (bis zu ``RETRIES`` Versuche je Datei).
    """
    import paramiko  # noqa: PLC0415
    connect = connect or (lambda: SFTP(cfg))
    key = f"{cfg['user']}@{cfg['host']}:{cfg.get('port', 22)}{cfg['remote_dir']}"
    all_state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
    state = {} if force else all_state.get(key, {})
    todo = plan_upload(publish_dir, state)
    if not todo:
        log("Server ist aktuell – nichts hochzuladen.")
        return []
    conn = connect()
    try:
        for rel in todo:
            size = (publish_dir / rel).stat().st_size
            log(f"  ↑ {rel} ({size / 1e6:.1f} MB)" if size > 1e6 else f"  ↑ {rel}")
            for attempt in range(1, RETRIES + 1):
                try:
                    conn.put_atomic(publish_dir / rel, rel, progress=_Progress(log))
                    break
                except (EOFError, OSError, paramiko.SSHException) as exc:
                    if attempt == RETRIES:
                        raise DeployError(f"Upload von {rel} nach {RETRIES} Versuchen abgebrochen: "
                                          f"{exc or type(exc).__name__}. Erneut mit `release.py upload` "
                                          "– bereits Hochgeladenes wird fortgesetzt.") from exc
                    log(f"    Verbindung unterbrochen ({exc or type(exc).__name__}) – "
                        f"neuer Versuch {attempt + 1}/{RETRIES} in {retry_wait * attempt:.0f} s …")
                    try:
                        conn.close()
                    except Exception:  # noqa: BLE001 – Verbindung ist ohnehin tot
                        pass
                    time.sleep(retry_wait * attempt)
                    conn = connect()
            state[rel] = _sha(publish_dir / rel)
            all_state[key] = state  # nach jeder Datei sichern: ein Abbruch lädt nur den Rest erneut
            state_file.parent.mkdir(parents=True, exist_ok=True)
            state_file.write_text(json.dumps(all_state, indent=1), encoding="utf-8")
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
    log(f"{len(todo)} Datei(en) hochgeladen.")
    return todo
