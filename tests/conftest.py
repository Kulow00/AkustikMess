"""Gemeinsame Test-Hilfen: isolierte Einstellungen, damit Tests nie die echten
Programmeinstellungen oder die automatische Sicherung des Nutzers berühren."""

import os
import sys
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# scipy vorab laden: im Programm geschieht das im Hintergrund; Tests sollen nicht davon abhängen,
# wann das Laden fertig ist (z. B. Beginn der SPL-Messung)
import scipy.signal  # noqa: E402,F401

from PySide6 import QtCore, QtWidgets  # noqa: E402

from akustik.audio.engine import SIMULATION, AudioConfig  # noqa: E402


def wait(app, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def make_window(tmp_dir, start=True):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from akustik.gui.main_window import MainWindow
    settings = QtCore.QSettings(os.path.join(str(tmp_dir), "settings.ini"), QtCore.QSettings.IniFormat)
    win = MainWindow(settings=settings, autosave_path=os.path.join(str(tmp_dir), "autosave.akmess"),
                     recovery=False, check_updates=False)
    win.state.save_config(AudioConfig(input_device=SIMULATION))
    win.resize(1500, 950)
    win.show()
    if start:
        win.a_run.setChecked(True)
        win.a_gen.setChecked(True)
    return app, win


@pytest.fixture(scope="module")
def window(tmp_path_factory):
    app, win = make_window(tmp_path_factory.mktemp("gui"))
    yield app, win
    win.close()


def pytest_runtest_logreport(report):
    """Auf GitHub fehlgeschlagene Tests als Annotation melden (öffentlich sichtbar, auch ohne Anmeldung)."""
    if not (report.failed and os.environ.get("GITHUB_ACTIONS")):
        return
    text = str(report.longrepr)[-3000:]
    esc = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    sys.__stdout__.write(f"\n::error title={report.nodeid}::{esc}\n")
    sys.__stdout__.flush()
