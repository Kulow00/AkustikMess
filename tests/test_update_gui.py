"""Update-Funktion in der Oberfläche (lokaler Test-Server, Test-Schlüssel)."""

import hashlib

import pytest
from PySide6 import QtWidgets
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from akustik import update
from conftest import make_window, wait
from test_update import local_server  # noqa: F401 – Fixture
from tools import release

KEY = Ed25519PrivateKey.generate()


@pytest.fixture
def served_release(local_server, monkeypatch):  # noqa: F811
    root, base = local_server
    payload = b"SETUP" * 1000
    (root / "setup.exe").write_bytes(payload)
    asset = {"file": "AkustikMess-9.0.0-beta.1-Windows-Setup.exe", "url": f"{base}/setup.exe",
             "sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload)}
    m = {"schema": 1, "app": "AkustikMess", "channels": {"stable": "8.0.0", "beta": "9.0.0-beta.1"},
         "releases": [
             {"version": "9.0.0-beta.1", "channel": "beta", "date": "2026-10-20", "notes": "- Beta-Funktion",
              "assets": {update.current_platform(): asset}},
             {"version": "8.0.0", "channel": "stable", "date": "2026-10-18", "notes": "- Stabile Neuerung",
              "assets": {update.current_platform(): dict(asset, file="AkustikMess-8.0.0-Windows-Setup.exe")}},
         ]}
    (root / "releases.json").write_bytes(release.sign_manifest(m, KEY))
    monkeypatch.setattr(update, "PUBLIC_KEY", release.public_key_b64(KEY))
    return f"{base}/releases.json"


def test_background_check_shows_hint_and_dialog_notes(tmp_path, served_release, monkeypatch):
    app, w = make_window(tmp_path, start=False)
    try:
        w.updates.url = served_release
        w.updates.channel = "stable"
        w.updates.check()
        for _ in range(100):
            wait(app, 0.05)
            if w.btn_update.isVisible():
                break
        assert w.btn_update.isVisible() and "8.0.0" in w.btn_update.text()
        from akustik.gui.update_dialog import UpdateDialog
        dlg = UpdateDialog(w.updates, w)
        assert "Stabile Neuerung" in dlg.notes.toPlainText()
        # Beta-Kanal: neueste Beta inkl. Patch Notes aller übersprungenen Versionen
        dlg.cb_channel.setCurrentIndex(dlg.cb_channel.findData("beta"))
        assert dlg.lbl_beta.isVisible() or not dlg.isVisible()
        dlg.check()
        for _ in range(100):
            wait(app, 0.05)
            if "9.0.0-beta.1" in dlg.lbl_status.text():
                break
        text = dlg.notes.toPlainText()
        assert "Beta-Funktion" in text and "Stabile Neuerung" in text
        # Quelltext-Fassung: kein Überschreiben, nur Download im Browser
        opened = []
        monkeypatch.setattr("PySide6.QtGui.QDesktopServices.openUrl", lambda u: opened.append(u.toString()))
        dlg.install()
        assert opened and opened[0].endswith("/setup.exe")
        # überspringen → Hinweis verschwindet, und eine erneute Prüfung zeigt ihn nicht mehr
        dlg._skip()
        assert not w.btn_update.isVisible() and w.updates.skipped == "9.0.0-beta.1"
        w.updates.check()
        wait(app, 1.0)
        assert not w.btn_update.isVisible()
    finally:
        w.close()


def test_installed_build_downloads_verifies_and_launches(tmp_path, served_release, monkeypatch):
    app, w = make_window(tmp_path, start=False)
    try:
        w.updates.url = served_release
        w.updates.channel = "stable"  # Standard hängt sonst von der eigenen Version ab (Beta → Beta-Kanal)
        monkeypatch.setattr(update, "is_installed_build", lambda: True)
        launched = []
        monkeypatch.setattr(update, "launch_installer", lambda p, platform=None: launched.append(p))
        from akustik.gui.update_dialog import UpdateDialog
        dlg = UpdateDialog(w.updates, w)
        dlg.check()
        for _ in range(100):
            wait(app, 0.05)
            if dlg.upd is not None:
                break
        closed = []
        monkeypatch.setattr(w, "close", lambda: closed.append(True))
        dlg.install()
        for _ in range(100):
            wait(app, 0.05)
            if launched and closed:
                break
        assert launched and launched[0].endswith("AkustikMess-8.0.0-Windows-Setup.exe")
        assert closed  # Programm beendet sich für die Installation
    finally:
        QtWidgets.QMainWindow.close(w)


def test_bad_signature_is_rejected_in_dialog(tmp_path, served_release, monkeypatch):
    app, w = make_window(tmp_path, start=False)
    try:
        monkeypatch.setattr(update, "PUBLIC_KEY", release.public_key_b64(Ed25519PrivateKey.generate()))
        w.updates.url = served_release
        from akustik.gui.update_dialog import UpdateDialog
        dlg = UpdateDialog(w.updates, w)
        dlg.check()
        for _ in range(100):
            wait(app, 0.05)
            if "Signatur" in dlg.lbl_status.text():
                break
        assert "Signatur" in dlg.lbl_status.text() and not dlg.btn_install.isVisible()
    finally:
        w.close()


def test_no_update_check_without_consent(tmp_path, monkeypatch):
    """Datenschutz: erst fragen, ohne Zustimmung keine Netzwerkverbindung."""
    app, w = make_window(tmp_path, start=False)
    try:
        assert not w.updates.consent_asked and not w.updates.auto
        checks, asked = [], []
        monkeypatch.setattr(w.updates, "check", lambda: checks.append(True))
        from akustik.gui import main_window
        monkeypatch.setattr(main_window, "ask_consent",
                            lambda mgr, parent=None: asked.append(True) or setattr(mgr, "auto", False))
        w._startup_update_check()
        assert asked == [True] and checks == [] and w.updates.consent_asked
        w._startup_update_check()                      # nur einmal fragen
        assert asked == [True] and checks == []
        w.updates.auto = True                          # später im Update-Dialog eingeschaltet
        w._startup_update_check()
        assert asked == [True] and checks == [True]
    finally:
        w.close()
