"""Release über GitHub: Tag pushen, signierte Installer vom GitHub-Release übernehmen."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from akustik import update
from test_update import local_server  # noqa: F401 – Fixture
from tools import release

KEY = Ed25519PrivateKey.generate()
ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.0.0-beta.1"
SETUP = f"AkustikMess-{VERSION}-Windows-Setup.exe"


@pytest.fixture
def gh(local_server, tmp_path, monkeypatch):  # noqa: F811
    """Lokaler „GitHub“-Server mit Release-Dateien und ein isolierter Veröffentlichungsordner."""
    root, base = local_server
    payload = b"SIGNED-SETUP" * 5000
    (root / SETUP).write_bytes(payload)
    rel = {"tag_name": f"v{VERSION}", "assets": [
        {"name": SETUP, "state": "uploaded", "browser_download_url": f"{base}/{SETUP}",
         "digest": "sha256:" + hashlib.sha256(payload).hexdigest()}]}
    calls = []
    monkeypatch.setattr(release, "github_release", lambda repo, v: calls.append((repo, v)) or rel)
    monkeypatch.setattr(release, "authenticode", lambda p: ("Valid", "CN=SignPath Foundation"))
    monkeypatch.setattr(release, "load_private_key", lambda *a: KEY)
    monkeypatch.setattr(update, "PUBLIC_KEY", release.public_key_b64(KEY))
    cfg_file = tmp_path / "release_config.json"
    pub = tmp_path / "web"
    cfg_file.write_text(json.dumps({"mode": "selfhosted", "publish_dir": str(pub), "github": "alex/akustikmess",
                                    "base_url": "https://akmess.example.de/"}), encoding="utf-8")
    monkeypatch.setattr(release, "CONFIG_FILE", cfg_file)
    log = tmp_path / "CHANGELOG.md"
    log.write_text(f"# Log\n\n## [Unreleased]\n\n## [{VERSION}] - 2026-10-20\n\n- Signiert\n", encoding="utf-8")
    monkeypatch.setattr(release, "CHANGELOG", log)
    monkeypatch.setattr(release, "BUILD_DIR", tmp_path / "build")
    return {"rel": rel, "pub": pub, "payload": payload, "calls": calls, "root": root}


def test_publish_takes_signed_installer_from_github(gh):
    assert release.main(["publish", "--version", VERSION, "--no-upload"]) == 0
    assert gh["calls"] == [("alex/akustikmess", VERSION)]
    m = update.parse_manifest((gh["pub"] / "releases.json").read_bytes())
    r = m["releases"][0]
    assert r["version"] == VERSION and r["channel"] == "beta" and r["notes"] == "- Signiert"
    a = r["assets"]["windows"]
    assert a["url"] == f"https://akmess.example.de/files/{SETUP}"
    assert (gh["pub"] / "files" / SETUP).read_bytes() == gh["payload"]
    page = (gh["pub"] / "index.html").read_text(encoding="utf-8")
    assert 'data-repo="alex/akustikmess"' in page and "__GITHUB_REPO__" not in page


def test_unsigned_installer_is_rejected(gh, monkeypatch, capsys):
    monkeypatch.setattr(release, "authenticode", lambda p: ("NotSigned", ""))
    assert release.main(["publish", "--version", VERSION, "--no-upload"]) == 1
    assert "nicht gültig signiert" in capsys.readouterr().out
    assert not (gh["pub"] / "releases.json").exists()          # nichts veröffentlicht
    assert release.main(["publish", "--version", VERSION, "--no-upload", "--allow-unsigned"]) == 0


def test_checksum_mismatch_and_missing_platform(gh, capsys):
    (gh["root"] / SETUP).write_bytes(b"manipuliert")
    assert release.main(["publish", "--version", VERSION, "--no-upload"]) == 1
    assert "Prüfsumme" in capsys.readouterr().out
    assert release.main(["publish", "--version", VERSION, "--no-upload", "--platform", "macos"]) == 1
    assert "fehlt: macos" in capsys.readouterr().out


def test_release_assets_ignores_unfinished_uploads():
    rel = {"assets": [{"name": SETUP, "state": "starter"}, {"name": "AkustikMess-1.0.0-macOS.pkg"},
                      {"name": "notes.txt"}]}
    assert set(release.release_assets(rel)) == {"macos"}
    assert release.release_assets(None) == {}


@pytest.mark.skipif(os.name != "nt", reason="Authenticode nur unter Windows")
def test_authenticode_detects_unsigned_and_signed(tmp_path):
    f = tmp_path / "x.exe"
    f.write_bytes(b"MZ" + b"\0" * 200)
    assert release.authenticode(f)[0] != "Valid"
    status, signer = release.authenticode(Path(os.environ["WINDIR"]) / "explorer.exe")
    assert status == "Valid" and "Microsoft" in signer


def test_release_pushes_tag(tmp_path):
    """release --channel beta: Version + CHANGELOG committen, Tag v… an GitHub (hier: lokales Repo) pushen."""
    work, remote = tmp_path / "work", tmp_path / "remote.git"
    for d in ("akustik", "tools"):
        shutil.copytree(ROOT / d, work / d, ignore=shutil.ignore_patterns("__pycache__"))
    (work / "akustik" / "__init__.py").write_text('__version__ = "0.9.0"\nAPP_NAME = "AkustikMess"\n',
                                                  encoding="utf-8")
    (work / "CHANGELOG.md").write_text("# Log\n\n## [Unreleased]\n\n- Neue Funktion\n", encoding="utf-8")
    (work / "release_config.json").write_text(json.dumps(
        {"mode": "selfhosted", "publish_dir": str(tmp_path / "web"), "base_url": "https://x.example/",
         "github": "alex/akustikmess"}), encoding="utf-8")
    (work / ".gitignore").write_text("release_config.json\n__pycache__/\n", encoding="utf-8")
    env = {**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "t@example.invalid", "PYTHONUTF8": "1"}

    def sh(*cmd, cwd=work):
        return subprocess.run(cmd, cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout

    sh("git", "init", "-q", "--bare", str(remote), cwd=tmp_path)
    sh("git", "init", "-q", "-b", "main")
    sh("git", "add", "-A")
    sh("git", "commit", "-q", "-m", "start")
    sh("git", "remote", "add", "origin", str(remote))
    (work / "dirty.txt").write_text("x")
    r = subprocess.run([sys.executable, "tools/release.py", "release", "--channel", "beta", "--skip-tests"],
                       cwd=work, env=env, capture_output=True, text=True)
    assert r.returncode == 1 and "nicht committete" in r.stdout
    (work / "dirty.txt").unlink()
    r = subprocess.run([sys.executable, "tools/release.py", "release", "--channel", "beta", "--skip-tests"],
                       cwd=work, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "0.10.0-beta.1" in (work / "akustik" / "__init__.py").read_text(encoding="utf-8")
    assert "## [0.10.0-beta.1]" in (work / "CHANGELOG.md").read_text(encoding="utf-8")
    assert sh("git", "tag", "--list", cwd=remote).split() == ["v0.10.0-beta.1"]
    assert sh("git", "log", "-1", "--format=%s", "main", cwd=remote).strip() == "Release 0.10.0-beta.1"
    assert sh("git", "status", "--porcelain") == ""
