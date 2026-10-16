"""Release-Werkzeug für AkustikMess: Version, Patch Notes, Build, Installer, Signatur, Veröffentlichung.

Typischer Ablauf
----------------
Einmalig::

    python tools/release.py keygen                     # Signaturschlüssel erzeugen (gut sichern!)
    python tools/release.py configure --mode selfhosted --publish-dir D:/web/akustikmess \
        --base-url https://downloads.example.de/akustikmess/
    # oder für Dropbox:
    python tools/release.py configure --mode dropbox --publish-dir "C:/Users/…/Dropbox/AkustikMess"

Pro Veröffentlichung (Patch Notes vorher in CHANGELOG.md unter [Unreleased] eintragen)::

    python tools/release.py release --channel beta     # z. B. 0.5.0-beta.1, 0.5.0-beta.2, …
    python tools/release.py release --channel stable   # Beta → 0.5.0 bzw. 0.5.0 → 0.5.1

Mit GitHub (``configure-github``) erhöht ``release`` nur Version und CHANGELOG, testet,
committet und pusht das Tag ``v<version>``. GitHub Actions baut dann Windows und macOS,
SignPath signiert (nach Freigabe in SignPath) und hängt die Installer an das GitHub-Release.
Danach::

    python tools/release.py publish --wait             # signierte Installer holen, prüfen, hochladen

Ohne GitHub (oder mit ``--local``) wird wie bisher lokal gebaut, unsigniert.

macOS-Installer (auf einem Mac gebaut) nachträglich hinzufügen::

    python tools/release.py add-asset --platform macos --file AkustikMess-0.5.0-macOS.pkg

Der private Schlüssel liegt außerhalb des Projekts unter ~/.akustikmess/ und darf
nicht weitergegeben werden. Geht er verloren, können bestehende Installationen
keine Updates mehr annehmen (dann einmalig manuell neu installieren).
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    # Mit dem System-Python gestartet? Dann mit dem Projekt-Python (.venv) neu starten,
    # dort sind pytest, PyInstaller, paramiko usw. installiert.
    _venv = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if _venv.exists() and Path(sys.prefix).resolve() != (ROOT / ".venv").resolve():
        sys.exit(subprocess.call([str(_venv), str(Path(__file__).resolve()), *sys.argv[1:]]))

from akustik.update import (  # noqa: E402
    PLATFORM_LABELS, bump, current_platform, direct_url, is_prerelease, parse_manifest, parse_version,
)

APP = "AkustikMess"
INIT_FILE = ROOT / "akustik" / "__init__.py"
UPDATE_CONFIG = ROOT / "akustik" / "update_config.py"
CHANGELOG = ROOT / "CHANGELOG.md"
CONFIG_FILE = ROOT / "release_config.json"
BUILD_DIR = ROOT / "release_build"
KEY_FILE = Path.home() / ".akustikmess" / "release_signing_key.pem"
EXT = {"windows": "-Windows-Setup.exe", "macos": "-macOS.pkg", "linux": "-Linux.AppImage"}


class ReleaseError(Exception):
    pass


def log(msg: str) -> None:
    print(msg, flush=True)


# --- Version -------------------------------------------------------------------------

def read_version(init_file: Path = INIT_FILE) -> str:
    m = re.search(r'__version__\s*=\s*"([^"]+)"', init_file.read_text(encoding="utf-8"))
    if not m:
        raise ReleaseError("__version__ nicht gefunden")
    return m.group(1)


def write_version(version: str, init_file: Path = INIT_FILE, release_date: str | None = None) -> None:
    """Version (und Erscheinungsdatum, das Kauflizenzen mit Update-Zeitraum prüfen) eintragen."""
    parse_version(version)
    text = init_file.read_text(encoding="utf-8")
    text = re.sub(r'__version__\s*=\s*"[^"]+"', f'__version__ = "{version}"', text)
    if release_date is not None:
        text = re.sub(r'^RELEASE_DATE = "[^"]*"', f'RELEASE_DATE = "{release_date}"', text, flags=re.M)
    init_file.write_text(text, encoding="utf-8")


def read_release_date(init_file: Path = INIT_FILE) -> str:
    m = re.search(r'^RELEASE_DATE = "([^"]*)"', init_file.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else ""


def next_version(current: str, channel: str, kind: str | None) -> str:
    if kind is None:
        kind = "beta" if channel == "beta" else ("stable" if is_prerelease(current) else "patch")
    new = bump(current, kind)
    if channel == "beta" and not is_prerelease(new):
        raise ReleaseError(f"Beta-Kanal braucht eine Vorabversion (z. B. {bump(current, 'beta')}), nicht {new}")
    if channel == "stable" and is_prerelease(new):
        raise ReleaseError(f"Stabiler Kanal braucht eine finale Version, nicht {new}")
    return new


# --- Änderungsprotokoll ------------------------------------------------------------------

_SECTION = re.compile(r"^## \[([^\]]+)\][^\n]*\n", re.M)


def changelog_sections(text: str) -> dict[str, str]:
    marks = list(_SECTION.finditer(text))
    out = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out[m.group(1)] = text[m.end():end].strip()
    return out


def finalize_changelog(text: str, version: str, date: str) -> tuple[str, str]:
    """[Unreleased] → [version] - date; liefert (neuer Text, Patch Notes)."""
    notes = changelog_sections(text).get("Unreleased", "").strip()
    if not notes:
        raise ReleaseError("Keine Patch Notes: bitte Änderungen in CHANGELOG.md unter "
                           "„## [Unreleased]“ eintragen.")
    if version in changelog_sections(text):
        raise ReleaseError(f"Version {version} steht bereits im CHANGELOG.")
    new = re.sub(r"^## \[Unreleased\][^\n]*\n.*?(?=^## \[|\Z)",
                 f"## [Unreleased]\n\n## [{version}] - {date}\n\n{notes}\n\n", text, count=1, flags=re.M | re.S)
    return new, notes


# --- Konfiguration und Schlüssel -------------------------------------------------------------

def load_config(path: Path | None = None) -> dict:
    path = path or CONFIG_FILE
    if not path.exists():
        raise ReleaseError("Noch nicht eingerichtet: zuerst `python tools/release.py configure …` ausführen.")
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg.setdefault("dropbox_links", {})
    return cfg


def manifest_url(cfg: dict) -> str:
    if cfg["mode"] == "dropbox":
        link = cfg["dropbox_links"].get("releases.json", "")
        return direct_url(link) if link else ""
    return cfg["base_url"].rstrip("/") + "/releases.json"


def write_update_config(url: str | None = None, public_key: str | None = None,
                        path: Path = UPDATE_CONFIG) -> None:
    text = path.read_text(encoding="utf-8")
    if url is not None:
        text = re.sub(r'^MANIFEST_URL = ".*"$', f'MANIFEST_URL = "{url}"', text, flags=re.M)
    if public_key is not None:
        text = re.sub(r'^PUBLIC_KEY = ".*"$', f'PUBLIC_KEY = "{public_key}"', text, flags=re.M)
    path.write_text(text, encoding="utf-8")


def load_private_key(path: Path = KEY_FILE):
    from cryptography.hazmat.primitives import serialization  # noqa: PLC0415
    if not path.exists():
        raise ReleaseError(f"Signaturschlüssel fehlt ({path}). Mit `release.py keygen` erzeugen "
                           "oder die Sicherung zurückkopieren.")
    return serialization.load_pem_private_key(path.read_bytes(), password=None)


def public_key_b64(private_key) -> str:
    from cryptography.hazmat.primitives import serialization  # noqa: PLC0415
    raw = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def keygen(path: Path = KEY_FILE, force: bool = False) -> str:
    from cryptography.hazmat.primitives import serialization  # noqa: PLC0415
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: PLC0415
    if path.exists() and not force:
        raise ReleaseError(f"Schlüssel existiert bereits: {path}. Ein neuer Schlüssel würde alle "
                           "bestehenden Installationen von Updates abschneiden (--force nur, wenn gewollt).")
    key = Ed25519PrivateKey.generate()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return public_key_b64(key)


# --- Release-Verzeichnis ---------------------------------------------------------------------

def sign_manifest(data: dict, private_key) -> bytes:
    signed = json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True)
    sig = base64.b64encode(private_key.sign(signed.encode("utf-8"))).decode()
    return json.dumps({"signed": signed, "signature": sig}, ensure_ascii=False).encode("utf-8")


def load_manifest(publish_dir: Path, private_key) -> dict:
    path = publish_dir / "releases.json"
    if not path.exists():
        return {"schema": 1, "app": APP, "channels": {}, "releases": []}
    return parse_manifest(path.read_bytes(), public_key_b64(private_key))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def asset_target(cfg: dict, version: str, channel: str, platform: str) -> tuple[str, str | None]:
    """(relativer Zielpfad im Veröffentlichungsordner, Download-URL oder None)."""
    if cfg["mode"] == "dropbox":
        # feste Dateinamen je Kanal: Freigabelinks bleiben beim Überschreiben gleich
        rel = f"{channel}/{APP}-{channel}{EXT[platform]}"
        link = cfg["dropbox_links"].get(f"{channel}/{platform}")
        return rel, direct_url(link) if link else None
    rel = f"files/{APP}-{version}{EXT[platform]}"
    return rel, cfg["base_url"].rstrip("/") + "/" + rel


def add_to_manifest(manifest: dict, *, version: str, channel: str, date: str, notes: str,
                    platform: str, asset: dict, mode: str) -> dict:
    rels = manifest.setdefault("releases", [])
    entry = next((r for r in rels if r["version"] == version), None)
    if entry is None:
        entry = {"version": version, "channel": channel, "date": date, "notes": notes, "assets": {}}
        rels.append(entry)
    elif entry["channel"] != channel:
        raise ReleaseError(f"{version} ist bereits im Kanal {entry['channel']} veröffentlicht.")
    entry["assets"][platform] = asset
    if notes:
        entry["notes"] = notes
    if mode == "dropbox":
        # gleicher Dateiname wurde überschrieben → ältere Einträge dieses Kanals haben keine Datei mehr
        for r in rels:
            if r is not entry and r["channel"] == channel and platform in r.get("assets", {}):
                del r["assets"][platform]
    rels.sort(key=lambda r: parse_version(r["version"]), reverse=True)
    chans = manifest.setdefault("channels", {})
    if channel not in chans or parse_version(version) >= parse_version(chans[channel]):
        chans[channel] = version
    manifest["updated"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    manifest["schema"], manifest["app"] = 1, APP
    return manifest


def publish(cfg: dict, file: Path, *, version: str, channel: str, platform: str, notes: str,
            private_key, date: str | None = None) -> dict:
    publish_dir = Path(cfg["publish_dir"])
    publish_dir.mkdir(parents=True, exist_ok=True)
    rel, url = asset_target(cfg, version, channel, platform)
    target = publish_dir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(file, target)
    if cfg["mode"] == "dropbox":  # versionierte Sicherungskopie (Archiv)
        arch = publish_dir / "archiv" / f"{APP}-{version}{EXT[platform]}"
        arch.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, arch)
    asset = {"file": f"{APP}-{version}{EXT[platform]}", "url": url, "sha256": sha256_file(target),
             "size": target.stat().st_size}
    manifest = load_manifest(publish_dir, private_key)
    add_to_manifest(manifest, version=version, channel=channel, date=date or dt.date.today().isoformat(),
                    notes=notes, platform=platform, asset=asset, mode=cfg["mode"])
    (publish_dir / "releases.json").write_bytes(sign_manifest(manifest, private_key))
    build_site(cfg, publish_dir)
    shutil.copy2(CHANGELOG, publish_dir / "CHANGELOG.md")
    if url is None:
        log(f"\n!  Für {rel} fehlt noch der Dropbox-Freigabelink. Link in Dropbox erstellen, in "
            f"release_config.json unter dropbox_links[\"{channel}/{platform}\"] eintragen und "
            "`python tools/release.py relink` ausführen.")
    return asset


def build_site(cfg: dict, publish_dir: Path | None = None) -> None:
    """Homepage (Download, Wiki, Lizenz, Datenschutz, Impressum) in den Veröffentlichungsordner bauen."""
    from tools import site  # noqa: PLC0415
    for w in site.build(publish_dir or Path(cfg["publish_dir"]), cfg):
        log(f"!  {w}")


def relink(cfg: dict, private_key) -> None:
    """Dropbox: Freigabelinks aus der Konfiguration ins Release-Verzeichnis übernehmen."""
    publish_dir = Path(cfg["publish_dir"])
    manifest = load_manifest(publish_dir, private_key)
    for r in manifest["releases"]:
        for platform, asset in r.get("assets", {}).items():
            _, url = asset_target(cfg, r["version"], r["channel"], platform)
            asset["url"] = url
    (publish_dir / "releases.json").write_bytes(sign_manifest(manifest, private_key))


# --- Build -----------------------------------------------------------------------------------

def find_iscc() -> Path:
    for p in (Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
              Path("C:/Program Files (x86)/Inno Setup 6/ISCC.exe"),
              Path("C:/Program Files/Inno Setup 6/ISCC.exe")):
        if p.exists():
            return p
    found = shutil.which("ISCC")
    if found:
        return Path(found)
    raise ReleaseError("Inno Setup nicht gefunden. Installieren mit:  winget install JRSoftware.InnoSetup")


def run(cmd: list, **kw) -> None:
    log("> " + " ".join(str(c) for c in cmd))
    subprocess.run([str(c) for c in cmd], check=True, cwd=ROOT, **kw)


def build(version: str, platform: str | None = None, skip_tests: bool = False, stage: str = "all") -> Path:
    """stage: "all", "app" (nur PyInstaller) oder "installer" (vorhandenes dist/ verpacken).

    Getrennte Stufen braucht der GitHub-Build: dazwischen wird die Programmdatei signiert,
    bevor sie in den Installer kommt.
    """
    platform = platform or current_platform()
    if platform != current_platform():
        raise ReleaseError(f"Ein {PLATFORM_LABELS[platform]}-Installer kann nur auf {PLATFORM_LABELS[platform]} "
                           "gebaut werden (oder per GitHub Actions, siehe .github/workflows/release.yml).")
    py = sys.executable
    if stage in ("all", "app"):
        if not skip_tests:
            run([py, "-m", "pytest", "-q", "tests"])
        run([py, "-m", "PyInstaller", "akustikmess.spec", "--noconfirm", "--log-level", "WARN"])
        if stage == "app":
            out = ROOT / "dist" / (f"{APP}.app" if platform == "macos" else APP)
            log(f"Programm: {out}")
            return out
    BUILD_DIR.mkdir(exist_ok=True)
    if platform == "windows":
        major, minor, patch, _, n = parse_version(version)
        num = f"{major}.{minor}.{patch}.{n}"  # Windows-Dateiversion muss rein numerisch sein
        run([find_iscc(), f"/DAppVersion={version}", f"/DNumVersion={num}", f"/DSourceDir={ROOT / 'dist' / APP}",
             f"/DOutputDir={BUILD_DIR}", "/Q", ROOT / "installer" / "windows.iss"])
        out = BUILD_DIR / f"{APP}-{version}{EXT['windows']}"
    elif platform == "macos":
        out = BUILD_DIR / f"{APP}-{version}{EXT['macos']}"
        run(["pkgbuild", "--component", ROOT / "dist" / f"{APP}.app", "--install-location", "/Applications",
             "--identifier", "de.akustikmess.app", "--version", version.split("-")[0], out])
    else:
        raise ReleaseError("Linux-Pakete sind noch nicht eingerichtet.")
    if not out.exists():
        raise ReleaseError(f"Installer wurde nicht erzeugt: {out}")
    log(f"Installer: {out} ({out.stat().st_size / 1e6:.0f} MB)")
    return out


# --- GitHub und Code-Signatur ----------------------------------------------------------------

def platform_of(filename: str) -> str | None:
    return next((p for p, ext in EXT.items() if filename.endswith(ext)), None)


def channel_of(version: str) -> str:
    return "beta" if is_prerelease(version) else "stable"


def github_release(repo: str, version: str) -> dict | None:
    """Öffentliches GitHub-Release zum Tag v<version> (None, solange es nicht existiert)."""
    import urllib.error  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415
    from akustik import update  # noqa: PLC0415
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases/tags/v{version}",
                                 headers={"Accept": "application/vnd.github+json",
                                          "User-Agent": update.USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 – feste https-Adresse
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise ReleaseError(f"GitHub antwortet mit {exc.code} für Release v{version}") from exc


def release_assets(release: dict | None) -> dict[str, dict]:
    """Fertig hochgeladene Installer im GitHub-Release, je Plattform."""
    out = {}
    for a in (release or {}).get("assets", []):
        plat = platform_of(a["name"])
        if plat and a.get("state", "uploaded") == "uploaded":
            out[plat] = a
    return out


def download_file(url: str, target: Path) -> Path:
    import urllib.request  # noqa: PLC0415
    from akustik import update  # noqa: PLC0415
    target.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": update.USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r, open(target, "wb") as fh:  # noqa: S310
        shutil.copyfileobj(r, fh, 1 << 20)
    return target


def authenticode(path: Path) -> tuple[str, str]:
    """(Status, Unterzeichner) der Windows-Signatur, z. B. ("Valid", "CN=SignPath Foundation, …")."""
    if os.name != "nt":
        return "Unknown", ""
    ps = ("$s = Get-AuthenticodeSignature -LiteralPath $env:AKM_FILE; "
          "Write-Output $s.Status; Write-Output $s.SignerCertificate.Subject")
    # PSModulePath von PowerShell 7 (z. B. auf GitHub-Rechnern) verhindert, dass Windows PowerShell
    # sein eigenes Sicherheitsmodul lädt → ohne diese Variable starten.
    env = {k: v for k, v in os.environ.items() if k.upper() != "PSMODULEPATH"}
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True,
                       text=True, env={**env, "AKM_FILE": str(path)}, timeout=60)
    lines = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
    if not lines:
        return "Unknown", (r.stderr or "").strip()[:300]
    return lines[0], (lines[1] if len(lines) > 1 else "")


def check_windows_signature(path: Path, allow_unsigned: bool = False) -> str:
    status, signer = authenticode(path)
    if status == "Valid":
        return signer
    if allow_unsigned:
        log(f"!  {path.name} ist NICHT gültig signiert ({status}) – Smart App Control wird ihn blockieren.")
        return ""
    raise ReleaseError(f"{path.name} ist nicht gültig signiert ({status}). Wurde die Signatur in SignPath "
                       "freigegeben? (Nur zum Testen: --allow-unsigned)")


def git(*args: str, capture: bool = False) -> str:
    r = subprocess.run(["git", *args], cwd=ROOT, check=True, text=True, capture_output=capture)
    return (r.stdout or "").strip()


# --- Befehle --------------------------------------------------------------------------------

def auto_upload(cfg: dict, args) -> None:
    """Nach jeder Veröffentlichung hochladen, wenn SFTP eingerichtet ist."""
    if not cfg.get("sftp") or getattr(args, "no_upload", False):
        return
    from tools import deploy  # noqa: PLC0415
    log(f"\nUpload nach {cfg['sftp']['host']}:{cfg['sftp']['remote_dir']} …")
    deploy.upload(cfg["sftp"], Path(cfg["publish_dir"]), log=log)
    check_online(cfg)


def check_online(cfg: dict) -> bool:
    """Prüft aus Sicht eines Nutzers: Verzeichnis per https abrufbar, Signatur gültig, Installer erreichbar."""
    import urllib.request  # noqa: PLC0415
    from akustik import update  # noqa: PLC0415
    url = manifest_url(cfg)
    try:
        m = update.fetch_manifest(url, public_key_b64(load_private_key()))
    except update.UpdateError as exc:
        log(f"✗ {url}: {exc}")
        return False
    log(f"✓ {url} erreichbar, Signatur gültig, Kanäle {m.get('channels')}")
    ok = True
    for ch, version in m.get("channels", {}).items():
        rel = next(r for r in m["releases"] if r["version"] == version)
        for platform, asset in rel["assets"].items():
            req = urllib.request.Request(update.direct_url(asset["url"]), method="HEAD",
                                         headers={"User-Agent": update.USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310 – https aus eigener Konfiguration
                    size = int(r.headers.get("Content-Length") or -1)
                good = size == asset["size"]
                log(f"{'✓' if good else '✗'} {ch} {version} {PLATFORM_LABELS[platform]}: "
                    f"{size / 1e6:.1f} MB{'' if good else ' – Größe passt nicht!'}")
                ok &= good
            except Exception as exc:  # noqa: BLE001
                log(f"✗ {ch} {version} {PLATFORM_LABELS[platform]}: nicht abrufbar ({exc})")
                ok = False
    return ok


def cmd_deploy_key(args) -> None:
    from tools import deploy  # noqa: PLC0415
    line = deploy.generate_deploy_key(force=args.force)
    log(f"Upload-Schlüssel: {deploy.DEPLOY_KEY}\n\nDiese EINE Zeile auf dem Server für den Upload-Benutzer "
        f"eintragen (öffentlicher Teil, nicht geheim; siehe docs/server-einrichtung.md):\n\n{line}\n")


def cmd_sftp_setup(args) -> None:
    from tools import deploy  # noqa: PLC0415
    cfg = load_config()
    sftp = {"host": args.host, "port": args.port, "user": args.user, "remote_dir": args.remote_dir}
    if not args.accept_fingerprint:
        fp = deploy.fingerprint(deploy.fetch_host_key(args.host, args.port))
        log(f"Der Server {args.host}:{args.port} meldet den Host-Schlüssel\n\n    {fp}\n\n"
            "Bitte auf dem Server vergleichen (dort ausführen):\n"
            "    for f in /etc/ssh/ssh_host_*_key.pub; do ssh-keygen -lf \"$f\"; done\n\n"
            "Stimmt er überein, denselben Befehl mit  --accept-fingerprint " + fp + "  wiederholen.")
        return
    fp = deploy.trust_host(args.host, args.port, args.accept_fingerprint)
    cfg["sftp"] = sftp
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"Server bestätigt ({fp}) und gespeichert. Teste Anmeldung und Schreibrechte …")
    with deploy.SFTP(sftp) as conn:
        conn.check_writable()
    log(f"✓ Anmeldung und Schreiben in {args.remote_dir} funktionieren.")


def cmd_upload(args) -> None:
    from tools import deploy  # noqa: PLC0415
    cfg = load_config()
    if not cfg.get("sftp"):
        raise ReleaseError("SFTP ist nicht eingerichtet (`release.py sftp-setup …`).")
    deploy.upload(cfg["sftp"], Path(cfg["publish_dir"]), log=log, force=args.force)
    check_online(cfg)


def cmd_site(args) -> None:
    """Nur die Homepage neu bauen (z. B. nach Änderungen am Wiki) und hochladen."""
    cfg = load_config()
    build_site(cfg)
    log(f"Homepage gebaut: {cfg['publish_dir']}")
    if cfg.get("sftp") and not args.no_upload:
        from tools import deploy  # noqa: PLC0415
        deploy.upload(cfg["sftp"], Path(cfg["publish_dir"]), log=log)


def cmd_check_online(args) -> None:
    if not check_online(load_config()):
        raise ReleaseError("Online-Prüfung fehlgeschlagen (siehe oben).")


def cmd_keygen(args) -> None:
    pub = keygen(force=args.force)
    write_update_config(public_key=pub)
    log(f"Schlüssel erzeugt: {KEY_FILE}\nÖffentlicher Schlüssel in akustik/update_config.py eingetragen.\n"
        "WICHTIG: Die Schlüsseldatei sicher aufbewahren (z. B. Passwort-Manager/USB-Stick), "
        "aber nie in Dropbox/Server/Projektordner legen.")


def cmd_configure(args) -> None:
    cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8")) if CONFIG_FILE.exists() else {}
    cfg.update({"mode": args.mode, "publish_dir": str(Path(args.publish_dir).resolve())})
    if args.mode == "selfhosted":
        if not args.base_url:
            raise ReleaseError("--base-url fehlt (Adresse, unter der der Veröffentlichungsordner erreichbar ist)")
        cfg["base_url"] = args.base_url
    cfg.setdefault("dropbox_links", {})
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    url = manifest_url(cfg)
    write_update_config(url=url)
    log(f"Konfiguration gespeichert: {CONFIG_FILE}\nUpdate-Adresse im Programm: {url or '(folgt nach Dropbox-Link)'}")
    if args.mode == "dropbox":
        log("Dropbox: Nach der ersten Veröffentlichung für releases.json und die Installer je einen "
            "Freigabelink erstellen und in release_config.json → dropbox_links eintragen "
            '(Schlüssel: "releases.json", "stable/windows", "beta/windows", "stable/macos", "beta/macos"), '
            "dann `configure` erneut und `relink` ausführen.")


def cmd_release(args) -> None:
    cfg = load_config()
    if cfg.get("github") and not args.local:
        return release_via_github(cfg, args)
    key = load_private_key()
    current = read_version()
    version = args.version or next_version(current, args.channel, args.bump)
    if parse_version(version) <= parse_version(current) and not args.version:
        raise ReleaseError(f"Neue Version {version} muss größer als {current} sein")
    today = dt.date.today().isoformat()
    text = CHANGELOG.read_text(encoding="utf-8")
    new_text, notes = finalize_changelog(text, version, today)
    log(f"Release {current} → {version} (Kanal: {args.channel})")
    old_date = read_release_date()
    write_version(version, release_date=dt.date.today().isoformat())
    CHANGELOG.write_text(new_text, encoding="utf-8")
    write_update_config(url=manifest_url(cfg))
    try:
        installer = build(version, skip_tests=args.skip_tests)
    except Exception:
        write_version(current, release_date=old_date)  # fehlgeschlagener Build: Version und CHANGELOG zurücksetzen
        CHANGELOG.write_text(text, encoding="utf-8")
        raise
    asset = publish(cfg, installer, version=version, channel=args.channel, platform=current_platform(),
                    notes=notes, private_key=key, date=today)
    log(f"\nVeröffentlicht: {version} ({args.channel}) → {cfg['publish_dir']}\n"
        f"SHA-256: {asset['sha256']}\nDownload-Seite: index.html im Veröffentlichungsordner")
    auto_upload(cfg, args)


def release_via_github(cfg: dict, args) -> None:
    """Version + CHANGELOG festschreiben, testen, Tag pushen. Bauen und signieren macht GitHub."""
    if git("status", "--porcelain", capture=True):
        raise ReleaseError("Es gibt nicht committete Änderungen. Bitte zuerst committen (oder verwerfen), "
                           "damit genau der geprüfte Stand veröffentlicht wird.")
    current = read_version()
    version = args.version or next_version(current, args.channel, args.bump)
    if parse_version(version) <= parse_version(current) and not args.version:
        raise ReleaseError(f"Neue Version {version} muss größer als {current} sein")
    if channel_of(version) != args.channel:
        raise ReleaseError(f"{version} passt nicht zum Kanal {args.channel}")
    text = CHANGELOG.read_text(encoding="utf-8")
    new_text, _ = finalize_changelog(text, version, dt.date.today().isoformat())
    log(f"Release {current} → {version} (Kanal: {args.channel}) über GitHub {cfg['github']}")
    old_date = read_release_date()
    write_version(version, release_date=dt.date.today().isoformat())
    CHANGELOG.write_text(new_text, encoding="utf-8")
    write_update_config(url=manifest_url(cfg))
    try:
        if not args.skip_tests:
            run([sys.executable, "-m", "pytest", "-q", "tests"])
        git("add", "-A")
        git("commit", "-m", f"Release {version}")
    except Exception:
        write_version(current, release_date=old_date)  # Tests rot: Version und CHANGELOG zurücksetzen
        CHANGELOG.write_text(text, encoding="utf-8")
        raise
    git("tag", "-a", f"v{version}", "-m", f"{APP} {version}")
    if args.no_push:
        log(f"\nCommit und Tag v{version} lokal erstellt. Zum Bauen lassen:  git push --follow-tags origin HEAD")
        return
    git("push", "--follow-tags", "origin", "HEAD")
    log(f"\n✓ Tag v{version} gepusht. GitHub baut jetzt: https://github.com/{cfg['github']}/actions\n"
        "  Danach in SignPath die Signatur-Anfragen freigeben und dann:\n"
        f"    python tools/release.py publish --version {version} --wait")


def cmd_publish(args) -> None:
    """Signierte Installer vom GitHub-Release holen, prüfen und auf der eigenen Seite veröffentlichen."""
    import time  # noqa: PLC0415
    cfg = load_config()
    if not cfg.get("github"):
        raise ReleaseError("GitHub ist nicht eingerichtet (`release.py configure-github --repo NAME/REPO`).")
    key = load_private_key()
    version = args.version or read_version()
    wanted = set(args.platform or ["windows"])
    deadline = time.monotonic() + args.timeout * 60
    while True:
        assets = release_assets(github_release(cfg["github"], version))
        if wanted <= set(assets) or not args.wait:
            break
        if time.monotonic() > deadline:
            raise ReleaseError(f"Zeitüberschreitung: Release v{version} hat nach {args.timeout} min noch keine "
                               f"Installer für {', '.join(sorted(wanted - set(assets)))}.")
        log(f"… warte auf GitHub-Release v{version} ({', '.join(sorted(wanted - set(assets)))} fehlt noch)")
        time.sleep(30)
    missing = wanted - set(assets)
    if missing:
        raise ReleaseError(f"Im GitHub-Release v{version} fehlt: {', '.join(sorted(missing))} "
                           "(Build noch nicht fertig oder Signatur nicht freigegeben? Sonst --wait).")
    notes = changelog_sections(CHANGELOG.read_text(encoding="utf-8")).get(version, "")
    today = dt.date.today().isoformat()
    dl_dir = BUILD_DIR / "github" / version
    for plat in sorted(wanted):  # nur die angeforderten Plattformen übernehmen
        a = assets[plat]
        path = download_file(a["browser_download_url"], dl_dir / a["name"])
        digest = (a.get("digest") or "").removeprefix("sha256:")
        if digest and digest != sha256_file(path):
            raise ReleaseError(f"{a['name']}: Prüfsumme stimmt nicht mit GitHub überein")
        if plat == "windows":
            signer = check_windows_signature(path, args.allow_unsigned)
            if signer:
                log(f"✓ {a['name']} signiert von {signer}")
        asset = publish(cfg, path, version=version, channel=channel_of(version), platform=plat,
                        notes=notes, private_key=key, date=today)
        log(f"✓ {PLATFORM_LABELS[plat]}: {a['name']} ({asset['size'] / 1e6:.1f} MB) übernommen")
    auto_upload(cfg, args)


def cmd_configure_github(args) -> None:
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", args.repo):
        raise ReleaseError("--repo im Format NAME/REPOSITORY angeben, z. B. alexkulow/akustikmess")
    cfg = load_config()
    cfg["github"] = args.repo
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"GitHub-Repository gespeichert: https://github.com/{args.repo}")


def cmd_notes(args) -> None:
    """Patch Notes einer Version ausgeben (Text des GitHub-Release)."""
    version = args.version or read_version()
    notes = changelog_sections(CHANGELOG.read_text(encoding="utf-8")).get(version)
    if notes is None:
        raise ReleaseError(f"Version {version} steht nicht im CHANGELOG")
    sys.stdout.buffer.write((notes + "\n").encode("utf-8"))


def cmd_build(args) -> None:
    """Nur bauen (z. B. auf dem Mac oder in GitHub Actions) – ohne Versionsänderung und ohne Veröffentlichung."""
    out = build(read_version(), skip_tests=args.skip_tests, stage=args.stage)
    if args.stage == "app" or os.environ.get("GITHUB_ACTIONS"):
        return
    log(f"Fertig: {out}\nVeröffentlichen auf dem Rechner mit dem Signaturschlüssel:\n"
        f"  python tools/release.py add-asset --platform {current_platform()} --file \"{out.name}\"")


def cmd_add_asset(args) -> None:
    cfg = load_config()
    key = load_private_key()
    manifest = load_manifest(Path(cfg["publish_dir"]), key)
    version = args.version or read_version()
    entry = next((r for r in manifest["releases"] if r["version"] == version), None)
    if entry is None:
        raise ReleaseError(f"Version {version} ist noch nicht veröffentlicht (zuerst `release` auf Windows).")
    asset = publish(cfg, Path(args.file), version=version, channel=entry["channel"], platform=args.platform,
                    notes="", private_key=key, date=entry["date"])
    log(f"{PLATFORM_LABELS[args.platform]}-Installer zu {version} hinzugefügt (SHA-256 {asset['sha256']}).")
    auto_upload(cfg, args)


def cmd_relink(args) -> None:
    cfg = load_config()
    write_update_config(url=manifest_url(cfg))
    relink(cfg, load_private_key())
    log("Links aktualisiert und Release-Verzeichnis neu signiert.")
    auto_upload(cfg, args)


def cmd_status(args) -> None:
    cfg = load_config()
    m = load_manifest(Path(cfg["publish_dir"]), load_private_key())
    log(f"Programmversion im Quelltext: {read_version()}\nUpdate-Adresse: {manifest_url(cfg)}")
    log(f"Kanäle: {m.get('channels')}")
    for r in m["releases"][:10]:
        plats = ", ".join(f"{PLATFORM_LABELS[p]}{'' if a.get('url') else ' (Link fehlt)'}"
                          for p, a in r["assets"].items()) or "keine Dateien"
        log(f"  {r['version']:<16} {r['channel']:<7} {r['date']}  {plats}")


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):  # ✓/→ auch bei umgeleiteter Ausgabe (CI, Pipe)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="AkustikMess veröffentlichen", formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("keygen", help="Signaturschlüssel erzeugen (einmalig)")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_keygen)
    p = sub.add_parser("configure", help="Veröffentlichungsort festlegen")
    p.add_argument("--mode", choices=["selfhosted", "dropbox"], required=True)
    p.add_argument("--publish-dir", required=True, help="Ordner, der veröffentlicht wird (Webserver- oder Dropbox-Ordner)")
    p.add_argument("--base-url", help="nur selfhosted: öffentliche Adresse dieses Ordners (https://…)")
    p.set_defaults(fn=cmd_configure)
    p = sub.add_parser("release", help="Version erhöhen, bauen, signieren, veröffentlichen")
    p.add_argument("--channel", choices=["stable", "beta"], required=True)
    p.add_argument("--bump", choices=["beta", "stable", "patch", "minor", "major"])
    p.add_argument("--version", help="Version explizit setzen, z. B. 1.0.0")
    p.add_argument("--skip-tests", action="store_true")
    p.add_argument("--no-upload", action="store_true", help="nur lokal veröffentlichen, nicht hochladen")
    p.add_argument("--local", action="store_true", help="lokal bauen statt über GitHub (unsigniert)")
    p.add_argument("--no-push", action="store_true", help="GitHub: Commit und Tag nur lokal anlegen")
    p.set_defaults(fn=cmd_release)
    p = sub.add_parser("publish", help="Signierte Installer vom GitHub-Release veröffentlichen")
    p.add_argument("--version", help="Standard: Version im Quelltext")
    p.add_argument("--platform", action="append", choices=["windows", "macos"],
                   help="zu übernehmende Plattformen (Standard: windows; mehrfach möglich)")
    p.add_argument("--wait", action="store_true", help="warten, bis GitHub fertig gebaut und signiert hat")
    p.add_argument("--timeout", type=int, default=180, help="Minuten für --wait (Standard 180)")
    p.add_argument("--allow-unsigned", action="store_true", help="nur zum Testen: unsignierten Installer zulassen")
    p.add_argument("--no-upload", action="store_true")
    p.set_defaults(fn=cmd_publish)
    p = sub.add_parser("configure-github", help="GitHub-Repository für Build und Signatur festlegen")
    p.add_argument("--repo", required=True, help="NAME/REPOSITORY")
    p.set_defaults(fn=cmd_configure_github)
    p = sub.add_parser("notes", help="Patch Notes einer Version ausgeben")
    p.add_argument("--version")
    p.set_defaults(fn=cmd_notes)
    p = sub.add_parser("build", help="Installer für dieses System bauen, ohne zu veröffentlichen")
    p.add_argument("--skip-tests", action="store_true")
    p.add_argument("--stage", choices=["all", "app", "installer"], default="all",
                   help="nur Programm (app) oder nur Installer aus vorhandenem dist/ (installer)")
    p.set_defaults(fn=cmd_build)
    p = sub.add_parser("add-asset", help="Installer einer anderen Plattform (z. B. macOS) hinzufügen")
    p.add_argument("--platform", choices=["windows", "macos", "linux"], required=True)
    p.add_argument("--file", required=True)
    p.add_argument("--version")
    p.add_argument("--no-upload", action="store_true")
    p.set_defaults(fn=cmd_add_asset)
    p = sub.add_parser("relink", help="Dropbox-Links übernehmen und neu signieren")
    p.add_argument("--no-upload", action="store_true")
    p.set_defaults(fn=cmd_relink)
    p = sub.add_parser("deploy-key", help="SSH-Schlüssel für den Upload erzeugen/anzeigen")
    p.add_argument("--force", action="store_true", help="neuen Schlüssel erzeugen (alten ersetzen)")
    p.set_defaults(fn=cmd_deploy_key)
    p = sub.add_parser("sftp-setup", help="Upload-Server einrichten und Fingerabdruck bestätigen")
    p.add_argument("--host", required=True)
    p.add_argument("--port", type=int, default=22)
    p.add_argument("--user", required=True)
    p.add_argument("--remote-dir", required=True, help="Zielordner auf dem Server (Web-Wurzel der Domain)")
    p.add_argument("--accept-fingerprint", help="vom Server bestätigter Fingerabdruck SHA256:…")
    p.set_defaults(fn=cmd_sftp_setup)
    p = sub.add_parser("upload", help="Veröffentlichungsordner hochladen (nur Änderungen)")
    p.add_argument("--force", action="store_true", help="alle Dateien neu hochladen")
    p.set_defaults(fn=cmd_upload)
    p = sub.add_parser("site", help="Homepage (Download, Wiki, Lizenz) neu bauen und hochladen")
    p.add_argument("--no-upload", action="store_true")
    p.set_defaults(fn=cmd_site)
    p = sub.add_parser("check-online", help="Prüfen, ob Updates für Nutzer erreichbar und gültig sind")
    p.set_defaults(fn=cmd_check_online)
    p = sub.add_parser("status", help="Veröffentlichte Versionen anzeigen")
    p.set_defaults(fn=cmd_status)
    args = ap.parse_args(argv)
    try:
        args.fn(args)
    except (ReleaseError, ValueError) as exc:
        log(f"FEHLER: {exc}")
        return 1
    except subprocess.CalledProcessError as exc:
        log(f"FEHLER: Schritt fehlgeschlagen ({exc.cmd[0]}), Code {exc.returncode}")
        return 1
    except Exception as exc:  # noqa: BLE001
        from tools.deploy import DeployError  # noqa: PLC0415
        if isinstance(exc, DeployError):
            log(f"FEHLER beim Upload: {exc}\n(Die lokale Veröffentlichung ist fertig; nach dem Beheben "
                "`python tools/release.py upload` ausführen.)")
            return 1
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
