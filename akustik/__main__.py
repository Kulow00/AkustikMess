"""Programmstart: ``python -m akustik``"""

import os
import sys


def apply_dark_theme(app) -> None:
    from PySide6 import QtGui

    p = QtGui.QPalette()
    c = QtGui.QColor
    roles = QtGui.QPalette.ColorRole
    p.setColor(roles.Window, c(38, 40, 45))
    p.setColor(roles.WindowText, c(220, 220, 220))
    p.setColor(roles.Base, c(27, 29, 33))
    p.setColor(roles.AlternateBase, c(45, 47, 53))
    p.setColor(roles.Text, c(220, 220, 220))
    p.setColor(roles.Button, c(50, 53, 59))
    p.setColor(roles.ButtonText, c(220, 220, 220))
    p.setColor(roles.Highlight, c(42, 130, 218))
    p.setColor(roles.HighlightedText, c(255, 255, 255))
    p.setColor(roles.ToolTipBase, c(50, 53, 59))
    p.setColor(roles.ToolTipText, c(220, 220, 220))
    p.setColor(roles.PlaceholderText, c(130, 130, 130))
    for role in (roles.Text, roles.ButtonText, roles.WindowText):
        p.setColor(QtGui.QPalette.ColorGroup.Disabled, role, c(110, 110, 110))
    app.setPalette(p)


def main() -> int:
    import pyqtgraph as pg
    from PySide6 import QtWidgets

    from . import APP_NAME
    from .gui.main_window import MainWindow

    # Kantenglättung aus: bei tausenden Punkten pro Kurve der größte Zeichen-Kostenfaktor
    pg.setConfigOptions(antialias=False, background="#1b1d21", foreground="#d0d0d0")
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    apply_dark_theme(app)
    if os.environ.get("AKUSTIKMESS_SELFTEST"):          # Prüfung des gebauten Programms (siehe selftest.py)
        from .selftest import run
        return run(app)
    win = MainWindow()
    win.show()
    # große Module (scipy.signal) kurz nach dem Öffnen im Hintergrund vorladen – das Fenster ist sofort da,
    # und bis zum ersten Messen ist alles geladen
    from PySide6 import QtCore

    from ._lazy import preload_async
    QtCore.QTimer.singleShot(0, preload_async)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
