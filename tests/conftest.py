"""Gemeinsame Test-Hilfen: isolierte Einstellungen, damit Tests nie die echten
Programmeinstellungen oder die automatische Sicherung des Nutzers berühren."""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
