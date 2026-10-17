"""Updates und Releases: Versionen, Kanäle, Signatur, Veröffentlichung, Download."""

import base64
import functools
import http.server
import json
import threading
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from akustik import update
from tools import release

KEY = Ed25519PrivateKey.generate()
PUB = release.public_key_b64(KEY)


# --- Versionen -------------------------------------------------------------------------

def test_version_order():
    order = ["0.4.0", "0.4.1", "0.5.0-alpha.1", "0.5.0-beta.1", "0.5.0-beta.2", "0.5.0-rc.1", "0.5.0", "1.0.0"]
    keys = [update.parse_version(v) for v in order]
    assert keys == sorted(keys)
    with pytest.raises(ValueError):
        update.parse_version("1.2")


@pytest.mark.parametrize("v,kind,expected", [
    ("0.4.0", "patch", "0.4.1"), ("0.4.0", "minor", "0.5.0"), ("0.4.0", "major", "1.0.0"),
    ("0.4.0", "beta", "0.5.0-beta.1"), ("0.5.0-beta.1", "beta", "0.5.0-beta.2"),
    ("0.5.0-beta.3", "stable", "0.5.0"),
])
def test_bump(v, kind, expected):
    assert update.bump(v, kind) == expected


def test_channel_rules_for_next_version():
    assert release.next_version("0.4.0", "beta", None) == "0.5.0-beta.1"
    assert release.next_version("0.5.0-beta.2", "stable", None) == "0.5.0"
    assert release.next_version("0.5.0", "stable", None) == "0.5.1"
    with pytest.raises(release.ReleaseError):
        release.next_version("0.4.0", "beta", "patch")
    with pytest.raises(release.ReleaseError):
        release.next_version("0.4.0", "stable", "beta")


# --- Adressen ---------------------------------------------------------------------------

def test_dropbox_links_become_direct_downloads():
    url = "https://www.dropbox.com/scl/fi/abc123/releases.json?rlkey=xyz&dl=0"
    out = update.direct_url(url)
    assert "dl=1" in out and "rlkey=xyz" in out and "dl=0" not in out
    assert update.direct_url("https://example.de/a.json") == "https://example.de/a.json"


def test_only_https_or_localhost():
    update.check_url_allowed("https://example.de/releases.json")
    update.check_url_allowed("http://127.0.0.1:8000/releases.json")
    with pytest.raises(update.UpdateError):
        update.check_url_allowed("http://example.de/releases.json")
    with pytest.raises(update.UpdateError):
        update.check_url_allowed("file:///C:/releases.json")


# --- Signatur ---------------------------------------------------------------------------

def manifest_with(*releases):
    m = {"schema": 1, "app": "AkustikMess", "channels": {}, "releases": list(releases)}
    return m


def rel(version, channel, platforms=("windows",), notes="- Änderung"):
    return {"version": version, "channel": channel, "date": "2026-10-16", "notes": notes,
            "assets": {p: {"file": f"x-{version}", "url": f"https://h/{version}-{p}", "sha256": "ab" * 32,
                           "size": 10} for p in platforms}}


def test_signed_manifest_roundtrip_and_tampering():
    raw = release.sign_manifest(manifest_with(rel("0.5.0", "stable")), KEY)
    assert update.parse_manifest(raw, PUB)["releases"][0]["version"] == "0.5.0"
    outer = json.loads(raw)
    outer["signed"] = outer["signed"].replace("0.5.0", "9.9.9")   # Angreifer ändert Version/Link
    with pytest.raises(update.UpdateError, match="Signatur"):
        update.parse_manifest(json.dumps(outer).encode(), PUB)
    other = release.public_key_b64(Ed25519PrivateKey.generate())
    with pytest.raises(update.UpdateError, match="Signatur"):
        update.parse_manifest(raw, other)                          # fremder Schlüssel
    with pytest.raises(update.UpdateError):
        update.parse_manifest(b"<html>Dropbox Vorschau</html>", PUB)


# --- Kanäle ------------------------------------------------------------------------------

def test_select_update_by_channel():
    m = manifest_with(rel("0.4.0", "stable"), rel("0.4.1", "stable", notes="- Fehler behoben"),
                      rel("0.5.0-beta.1", "beta", notes="- Neue Funktion"),
                      rel("0.5.0-beta.2", "beta", platforms=("macos",)))
    u = update.select_update(m, "0.4.0", "stable", "windows")
    assert u.version == "0.4.1" and [n[0] for n in u.notes] == ["0.4.1"]
    u = update.select_update(m, "0.4.0", "beta", "windows")
    assert u.version == "0.5.0-beta.1"                 # beta.2 hat keinen Windows-Installer
    assert [n[0] for n in u.notes] == ["0.5.0-beta.1", "0.4.1"]
    assert update.select_update(m, "0.4.1", "stable", "windows") is None
    assert update.select_update(m, "0.5.0-beta.2", "beta", "macos") is None
    m["releases"].append(rel("0.5.0", "stable"))
    assert update.select_update(m, "0.5.0-beta.1", "beta", "windows").version == "0.5.0"
    assert update.select_update(m, "0.5.0-beta.1", "stable", "windows").version == "0.5.0"


# --- Änderungsprotokoll --------------------------------------------------------------------

def test_finalize_changelog():
    text = "# Log\n\n## [Unreleased]\n\n### Neu\n- Etwas\n\n## [0.4.0] - 2026-10-01\n\n- Alt\n"
    new, notes = release.finalize_changelog(text, "0.5.0-beta.1", "2026-10-16")
    assert notes == "### Neu\n- Etwas"
    sec = release.changelog_sections(new)
    assert sec["Unreleased"] == "" and sec["0.5.0-beta.1"] == "### Neu\n- Etwas" and sec["0.4.0"] == "- Alt"
    with pytest.raises(release.ReleaseError, match="Patch Notes"):
        release.finalize_changelog(new, "0.5.0-beta.2", "2026-10-17")


# --- Veröffentlichen ---------------------------------------------------------------------------

def fake_installer(tmp_path, name, content):
    p = tmp_path / name
    p.write_bytes(content)
    return p


def test_publish_selfhosted(tmp_path, monkeypatch):
    pub = tmp_path / "web"
    cfg = {"mode": "selfhosted", "publish_dir": str(pub), "base_url": "https://dl.example.de/am/",
           "dropbox_links": {}}
    monkeypatch.setattr(release, "CHANGELOG", fake_installer(tmp_path, "CHANGELOG.md", b"# Log"))
    f1 = fake_installer(tmp_path, "a.exe", b"windows-0.5.0-beta.1")
    release.publish(cfg, f1, version="0.5.0-beta.1", channel="beta", platform="windows", notes="- A",
                    private_key=KEY)
    f2 = fake_installer(tmp_path, "b.pkg", b"mac-0.5.0-beta.1")
    release.publish(cfg, f2, version="0.5.0-beta.1", channel="beta", platform="macos", notes="",
                    private_key=KEY)
    m = update.parse_manifest((pub / "releases.json").read_bytes(), PUB)
    r = m["releases"][0]
    assert set(r["assets"]) == {"windows", "macos"} and r["notes"] == "- A"
    assert r["assets"]["windows"]["url"] == "https://dl.example.de/am/files/AkustikMess-0.5.0-beta.1-Windows.zip"
    assert (pub / "files" / "AkustikMess-0.5.0-beta.1-macOS.zip").read_bytes() == b"mac-0.5.0-beta.1"
    assert (pub / "index.html").exists() and m["channels"] == {"beta": "0.5.0-beta.1"}


def test_publish_dropbox_keeps_stable_names(tmp_path, monkeypatch):
    pub = tmp_path / "Dropbox"
    cfg = {"mode": "dropbox", "publish_dir": str(pub),
           "dropbox_links": {"stable/windows": "https://www.dropbox.com/scl/fi/x/AkustikMess-stable-Windows-Setup.exe?rlkey=k&dl=0"}}
    monkeypatch.setattr(release, "CHANGELOG", fake_installer(tmp_path, "CHANGELOG.md", b"# Log"))
    for v in ("0.5.0", "0.5.1"):
        release.publish(cfg, fake_installer(tmp_path, f"{v}.exe", v.encode()), version=v, channel="stable",
                        platform="windows", notes=f"- {v}", private_key=KEY)
    m = update.parse_manifest((pub / "releases.json").read_bytes(), PUB)
    newest, older = m["releases"]
    assert newest["version"] == "0.5.1" and "dl=1" in newest["assets"]["windows"]["url"]
    assert older["assets"] == {}            # Datei wurde überschrieben → kein Download mehr, Notizen bleiben
    assert older["notes"] == "- 0.5.0"
    assert (pub / "stable" / "AkustikMess-stable-Windows.zip").read_bytes() == b"0.5.1"
    assert (pub / "archiv" / "AkustikMess-0.5.0-Windows.zip").exists()


# --- Download über einen lokalen Server --------------------------------------------------------

@pytest.fixture
def local_server(tmp_path):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path))
    handler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield tmp_path, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def test_check_and_download_end_to_end(local_server, monkeypatch):
    root, base = local_server
    payload = b"INSTALLER" * 50000
    (root / "files").mkdir()
    (root / "files" / "setup.exe").write_bytes(payload)
    import hashlib
    asset = {"file": "AkustikMess-0.9.0-Windows-Setup.exe", "url": f"{base}/files/setup.exe",
             "sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload)}
    m = manifest_with({"version": "0.9.0", "channel": "stable", "date": "2026-10-16", "notes": "- Neu",
                       "assets": {"windows": asset}})
    (root / "releases.json").write_bytes(release.sign_manifest(m, KEY))
    manifest = update.fetch_manifest(f"{base}/releases.json", PUB)
    u = update.select_update(manifest, "0.4.0", "stable", "windows")
    seen = []
    path = update.download(u.asset, progress=lambda d, t: seen.append(d))
    assert Path(path).read_bytes() == payload and seen[-1] == len(payload)
    assert Path(path).name == "AkustikMess-0.9.0-Windows-Setup.exe"
    (root / "files" / "setup.exe").write_bytes(payload[:-1] + b"X")  # Datei auf dem Server manipuliert
    with pytest.raises(update.UpdateError, match="Prüfsumme"):
        update.download(u.asset)
    with pytest.raises(update.UpdateError, match="nicht erreichbar"):
        update.fetch_manifest(f"{base}/gibtsnicht.json", PUB)


def test_keygen_writes_public_key(tmp_path):
    key_path = tmp_path / "k.pem"
    pub = release.keygen(key_path)
    assert len(base64.b64decode(pub)) == 32
    assert release.public_key_b64(release.load_private_key(key_path)) == pub
    with pytest.raises(release.ReleaseError, match="existiert bereits"):
        release.keygen(key_path)
    cfg = tmp_path / "update_config.py"
    cfg.write_text('MANIFEST_URL = ""\nPUBLIC_KEY = ""\n', encoding="utf-8")
    release.write_update_config("https://x/releases.json", pub, cfg)
    assert f'PUBLIC_KEY = "{pub}"' in cfg.read_text() and "https://x/releases.json" in cfg.read_text()


def test_bundle_update_replaces_program_folder(tmp_path):
    """ZIP-Update: Programmteile ersetzen, alte Reste entfernen, eigene Dateien im Ordner behalten."""
    import os
    import subprocess
    import sys
    import zipfile

    if sys.platform != "win32":
        pytest.skip("Windows-Austauschskript")
    z = tmp_path / "AkustikMess-9.9.9-Windows.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("AkustikMess/AkustikMess.exe", "NEU")
        zf.writestr("AkustikMess/_internal/neu.dll", "x")
        zf.writestr("AkustikMess/AkustikMess starten.bat", "@echo off")
    target = tmp_path / "Programm mit Leerzeichen"
    (target / "_internal").mkdir(parents=True)
    (target / "AkustikMess.exe").write_text("ALT")
    (target / "_internal" / "alt.dll").write_text("y")
    (target / "meine Sitzung.akmess").write_text("bleibt")
    done = subprocess.run([sys.executable, "-c", "pass"])               # beendeter Prozess als „altes Programm“
    del done
    script = update.prepare_bundle_update(str(z), target=target, platform="windows", pid=999999, restart=False)
    work = os.path.dirname(script)
    subprocess.run(["cmd", "/c", script], check=False, timeout=60)
    assert (target / "AkustikMess.exe").read_text() == "NEU"
    assert (target / "_internal" / "neu.dll").exists() and not (target / "_internal" / "alt.dll").exists()
    assert (target / "meine Sitzung.akmess").read_text() == "bleibt"
    assert (target / "AkustikMess starten.bat").exists() and not os.path.exists(work)


def test_bundle_update_rejects_bad_zip(tmp_path):
    import zipfile
    z = tmp_path / "x.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../../boese.txt", "x")
    with pytest.raises(update.UpdateError):
        update.prepare_bundle_update(str(z), target=tmp_path / "t", platform="windows", pid=1, restart=False)
    z2 = tmp_path / "leer.zip"
    with zipfile.ZipFile(z2, "w") as zf:
        zf.writestr("anderes/readme.txt", "x")
    with pytest.raises(update.UpdateError, match="kein AkustikMess"):
        update.prepare_bundle_update(str(z2), target=tmp_path / "t", platform="windows", pid=1, restart=False)
    sh = update.bundle_update_script("/tmp/neu/AkustikMess.app", "/Applications/AkustikMess.app", 42, "macos",
                                     "/tmp/neu", restart=True)
    assert "kill -0 42" in sh and 'open "/Applications/AkustikMess.app"' in sh and "quarantine" in sh
