"""Selbsttest des fertig gebauten Programms (für Build-Prüfung und GitHub Actions).

Start mit gesetzter Umgebungsvariable ``AKUSTIKMESS_SELFTEST=<Ergebnisdatei>``: Das Programm öffnet sich mit
eigenen, temporären Einstellungen (berührt keine Nutzerdaten), prüft alle Bereiche einschließlich
Simulation, scipy-Filtern, Raum-Berechnung und 3D-Ansicht, schreibt das Ergebnis in die Datei und beendet sich
mit Code 0 (alles in Ordnung) bzw. 1.
"""

from __future__ import annotations

import os
import tempfile
import time
import traceback


def run(app) -> int:
    from PySide6 import QtCore

    from . import __version__
    from ._lazy import preload
    from .audio.engine import SIMULATION, AudioConfig
    from .gui.main_window import MainWindow

    out = os.environ.get("AKUSTIKMESS_SELFTEST", "")
    tmp = tempfile.mkdtemp(prefix="akm-selftest-")
    log = [f"AkustikMess {__version__} Selbsttest"]
    result = {"code": 1}

    def step(name, fn):
        t0 = time.perf_counter()
        fn()
        log.append(f"ok  {name} ({1000 * (time.perf_counter() - t0):.0f} ms)")

    def wait(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)

    settings = QtCore.QSettings(os.path.join(tmp, "settings.ini"), QtCore.QSettings.IniFormat)
    win = MainWindow(settings=settings, autosave_path=os.path.join(tmp, "autosave.akmess"), recovery=False,
                     check_updates=False)
    win.show()

    def checks():
        try:
            step("Fenster", lambda: wait(0.2))
            step("scipy laden", preload)
            win.state.save_config(AudioConfig(input_device=SIMULATION))

            def audio():
                win.a_run.setChecked(True)
                win.a_gen.setChecked(True)
                wait(1.5)
                assert win.state.engine is not None and win.state.engine.generator_active
            step("Simulation + Generator", audio)

            def realtime():
                win.realtime.find_delay()
                wait(1.0)
                assert win.realtime.last_tf is not None and win.realtime.last_spec is not None
            step("Echtzeit (MTW, Spektrum)", realtime)
            step("SPL", lambda: (win.tabs.setCurrentWidget(win.spl), wait(1.2)))
            step("Raum: Pegelkarte", lambda: (win.tabs.setCurrentWidget(win.room), win.room.compute_now()))

            def view3d():
                win.room.view_tabs.setCurrentWidget(win.room.view3d)
                wait(0.3)
                log.append(f"    OpenGL verfügbar: {win.room.view3d.available}")
            step("Raum: 3D", view3d)
            win.a_run.setChecked(False)
            result["code"] = 0
            log.append("ERGEBNIS: OK")
        except Exception:  # noqa: BLE001
            log.append("FEHLER:\n" + traceback.format_exc())
        finally:
            if out:
                with open(out, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(log) + "\n")
            win.close()
            app.exit(result["code"])

    QtCore.QTimer.singleShot(100, checks)
    return app.exec()
