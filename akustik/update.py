"""Updates: Versionsnummern, Kanäle, signiertes Release-Verzeichnis, Download, Installation.

Release-Verzeichnis (``releases.json``) – eine Datei, damit sie auch per
Dropbox-Freigabelink funktioniert::

    {"signed": "<JSON-Text>", "signature": "<Ed25519, Base64>"}

Der JSON-Text enthält::

    {"schema": 1, "app": "AkustikMess", "updated": "…",
     "channels": {"stable": "0.4.0", "beta": "0.5.0-beta.1"},
     "releases": [{"version": "0.5.0-beta.1", "channel": "beta", "date": "2026-10-16",
                   "notes": "Markdown …",
                   "assets": {"windows": {"file": "…", "url": "…", "sha256": "…", "size": 123},
                              "macos": {…}}}, …]}

Sicherheitsmodell: Nur ein mit dem privaten Release-Schlüssel signiertes
Verzeichnis wird akzeptiert; jede heruntergeladene Datei muss den dort
eingetragenen SHA-256-Wert haben. Ein übernommener Server/Dropbox-Ordner kann
also keine fremden Programme als Update ausliefern.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass

from . import APP_NAME, __version__
from .update_config import MANIFEST_URL, PUBLIC_KEY

CHANNELS = ("stable", "beta")
CHANNEL_LABELS = {"stable": "Stabil", "beta": "Beta"}
PLATFORMS = ("windows", "macos", "linux")
PLATFORM_LABELS = {"windows": "Windows", "macos": "macOS", "linux": "Linux"}
TIMEOUT_S = 15
USER_AGENT = f"{APP_NAME}/{__version__}"

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta|rc)\.(\d+))?$")
_STAGE_RANK = {"alpha": 0, "beta": 1, "rc": 2, None: 3}


class UpdateError(Exception):
    """Fehler beim Prüfen/Laden eines Updates (Meldung ist für Nutzer lesbar)."""


# --- Versionsnummern (Semantic Versioning mit Vorabversionen) -----------------------

def parse_version(v: str) -> tuple:
    m = _VERSION_RE.match(v.strip())
    if not m:
        raise ValueError(f"Ungültige Versionsnummer: {v!r} (erwartet z. B. 1.2.3 oder 1.2.3-beta.1)")
    major, minor, patch, stage, n = m.groups()
    return int(major), int(minor), int(patch), _STAGE_RANK[stage], int(n or 0)


def is_prerelease(v: str) -> bool:
    return "-" in v


def bump(v: str, kind: str) -> str:
    """Nächste Version: ``major``/``minor``/``patch`` (stabil), ``beta`` (nächste
    Beta), ``stable`` (Beta → zugehörige stabile Version)."""
    major, minor, patch, stage, n = parse_version(v)
    pre = stage != 3
    if kind == "major":
        return f"{major + 1}.0.0"
    if kind == "minor":
        return f"{major}.{minor + 1}.0"
    if kind == "patch":
        return f"{major}.{minor}.{patch + 1}" if not pre else f"{major}.{minor}.{patch}"
    if kind == "stable":
        if not pre:
            raise ValueError(f"{v} ist bereits eine stabile Version")
        return f"{major}.{minor}.{patch}"
    if kind == "beta":
        if pre and stage == _STAGE_RANK["beta"]:
            return f"{major}.{minor}.{patch}-beta.{n + 1}"
        return f"{major}.{minor + 1}.0-beta.1"  # neue Beta-Reihe für die nächste Minor-Version
    raise ValueError(f"Unbekannte Art: {kind}")


# --- Plattform ---------------------------------------------------------------------

def current_platform() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def is_installed_build() -> bool:
    """True für die per Installer verteilte Fassung (PyInstaller), nicht beim Start aus dem Quelltext."""
    return bool(getattr(sys, "frozen", False))


# --- Release-Verzeichnis ------------------------------------------------------------

def direct_url(url: str) -> str:
    """Dropbox-Freigabelinks in Direkt-Download-Links umwandeln (dl=0 → dl=1)."""
    parts = urllib.parse.urlsplit(url)
    if parts.netloc.endswith("dropbox.com"):
        q = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
        q.pop("raw", None)
        q["dl"] = "1"
        return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(q)))
    return url


def check_url_allowed(url: str) -> None:
    """Nur https – außer für Tests/Server im eigenen Netz (localhost)."""
    p = urllib.parse.urlsplit(url)
    if p.scheme == "https":
        return
    if p.scheme == "http" and p.hostname in ("localhost", "127.0.0.1", "::1"):
        return
    raise UpdateError(f"Unsichere Update-Adresse (nur https erlaubt): {url}")


def verify_signature(signed: str, signature_b64: str, public_key_b64: str | None = None) -> None:
    from cryptography.exceptions import InvalidSignature  # noqa: PLC0415
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey  # noqa: PLC0415

    public_key_b64 = PUBLIC_KEY if public_key_b64 is None else public_key_b64
    if not public_key_b64:
        raise UpdateError("In dieser Programmversion ist kein Update-Schlüssel hinterlegt.")
    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
        key.verify(base64.b64decode(signature_b64), signed.encode("utf-8"))
    except (InvalidSignature, ValueError) as exc:
        raise UpdateError("Signatur des Update-Verzeichnisses ist ungültig – Update abgelehnt.") from exc


def parse_manifest(raw: bytes, public_key_b64: str | None = None) -> dict:
    try:
        outer = json.loads(raw)
        signed, sig = outer["signed"], outer["signature"]
    except (ValueError, KeyError, TypeError) as exc:
        raise UpdateError("Update-Verzeichnis ist beschädigt oder kein AkustikMess-Verzeichnis.") from exc
    verify_signature(signed, sig, public_key_b64)
    data = json.loads(signed)
    if data.get("schema") != 1 or data.get("app") != APP_NAME:
        raise UpdateError("Update-Verzeichnis gehört nicht zu diesem Programm.")
    return data


def _open(url: str, timeout: float):
    check_url_allowed(url)
    req = urllib.request.Request(direct_url(url), headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 – Schema oben geprüft


def fetch_manifest(url: str | None = None, public_key_b64: str | None = None,
                   timeout: float = TIMEOUT_S) -> dict:
    url = MANIFEST_URL if url is None else url
    if not url:
        raise UpdateError("Keine Update-Adresse eingestellt.")
    try:
        with _open(url, timeout) as r:
            raw = r.read(5 * 1024 * 1024)
    except UpdateError:
        raise
    except Exception as exc:  # noqa: BLE001 – Netzwerkfehler verständlich melden
        raise UpdateError(f"Update-Server nicht erreichbar: {exc}") from exc
    return parse_manifest(raw, public_key_b64)


@dataclass
class Update:
    version: str
    channel: str
    date: str
    asset: dict
    notes: list[tuple[str, str, str]]   # (Version, Datum, Patch Notes) aller neueren Versionen


def visible_channels(channel: str) -> tuple[str, ...]:
    """Beta-Nutzer erhalten auch stabile Versionen (immer die neueste)."""
    return ("stable", "beta") if channel == "beta" else ("stable",)


def select_update(manifest: dict, current: str = __version__, channel: str = "stable",
                  platform: str | None = None) -> Update | None:
    platform = platform or current_platform()
    chans = visible_channels(channel)
    cur = parse_version(current)
    newer = []
    for rel in manifest.get("releases", []):
        try:
            v = parse_version(rel["version"])
        except (ValueError, KeyError):
            continue
        if rel.get("channel") in chans and v > cur:
            newer.append((v, rel))
    newer.sort(key=lambda x: x[0], reverse=True)
    for v, rel in newer:
        asset = (rel.get("assets") or {}).get(platform)
        if asset and asset.get("url") and asset.get("sha256"):
            notes = [(r["version"], r.get("date", ""), r.get("notes", "")) for vv, r in newer if vv <= v]
            return Update(rel["version"], rel["channel"], rel.get("date", ""), asset, notes)
    return None


# --- Download und Installation ---------------------------------------------------------

def download(asset: dict, progress=None, cancel=None, timeout: float = 60) -> str:
    """Lädt die Installationsdatei, prüft Größe und SHA-256. Liefert den Dateipfad."""
    url = asset["url"]
    name = os.path.basename(asset.get("file") or "AkustikMess-Update")
    folder = tempfile.mkdtemp(prefix="akustikmess-update-")
    path = os.path.join(folder, name)
    h = hashlib.sha256()
    total = int(asset.get("size") or 0)
    done = 0
    try:
        with _open(url, timeout) as r, open(path, "wb") as fh:
            while True:
                if cancel is not None and cancel():
                    raise UpdateError("Download abgebrochen.")
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except UpdateError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise UpdateError(f"Download fehlgeschlagen: {exc}") from exc
    if total and done != total:
        raise UpdateError(f"Download unvollständig ({done} von {total} Bytes).")
    if h.hexdigest().lower() != str(asset["sha256"]).lower():
        os.remove(path)
        raise UpdateError("Prüfsumme stimmt nicht – Datei beschädigt oder verändert. Update abgebrochen.")
    return path


def launch_installer(path: str, platform: str | None = None) -> None:
    """Startet die geprüfte Installationsdatei. Das Programm beendet sich danach selbst."""
    platform = platform or current_platform()
    if platform == "windows":
        # still installieren, laufendes Programm schließen, danach neu starten (siehe windows.iss)
        subprocess.Popen([path, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",  # noqa: S603
                          "/CLOSEAPPLICATIONS"], close_fds=True)
    elif platform == "macos":
        subprocess.Popen(["open", path])  # noqa: S603, S607 – macOS-Installationsprogramm
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path)])  # noqa: S603, S607
