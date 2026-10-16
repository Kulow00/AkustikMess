"""Sitzungen speichern/laden (.akmess) und Hilfen für Bedienelement-Zustände.

Format: komprimiertes NumPy-Archiv. ``__meta__`` enthält JSON (Einstellungen,
Kurvennamen, Notizen), alle Messdaten liegen als eigene Arrays daneben.
"""

from __future__ import annotations

import json
import os
import tempfile

import numpy as np
from PySide6 import QtWidgets

FORMAT_VERSION = 1
EXTENSION = ".akmess"
FILE_FILTER = "AkustikMess-Sitzung (*.akmess)"
CONTROL_TYPES = (QtWidgets.QComboBox, QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox, QtWidgets.QCheckBox)


def name_controls(obj) -> None:
    """Gibt allen Bedienelementen in ``obj`` ihren Attributnamen als objectName."""
    for attr, val in vars(obj).items():
        if isinstance(val, CONTROL_TYPES) and not val.objectName():
            val.setObjectName(attr)


def controls_state(root: QtWidgets.QWidget) -> dict:
    state = {}
    for w in root.findChildren(QtWidgets.QWidget):
        name = w.objectName()
        if not name or name.startswith("qt_") or not isinstance(w, CONTROL_TYPES):
            continue
        if isinstance(w, QtWidgets.QComboBox):
            state[name] = w.currentText()
        elif isinstance(w, QtWidgets.QCheckBox):
            state[name] = w.isChecked()
        else:
            state[name] = w.value()
    return state


def apply_controls_state(root: QtWidgets.QWidget, state: dict) -> None:
    for name, value in state.items():
        w = root.findChild(QtWidgets.QWidget, name)
        if w is None:
            continue
        if isinstance(w, QtWidgets.QComboBox):
            idx = w.findText(str(value))
            if idx >= 0:
                w.setCurrentIndex(idx)
        elif isinstance(w, QtWidgets.QCheckBox):
            w.setChecked(bool(value))
        elif isinstance(w, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
            w.setValue(value)


def save_session(path: str, meta: dict, arrays: dict[str, np.ndarray]) -> None:
    """Atomar speichern (erst temporäre Datei, dann umbenennen)."""
    meta = {"format": FORMAT_VERSION, **meta}
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "wb") as fh:
            np.savez_compressed(fh, __meta__=np.array(json.dumps(meta)), **arrays)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def load_session(path: str) -> tuple[dict, dict[str, np.ndarray]]:
    with np.load(path, allow_pickle=False) as z:
        meta = json.loads(str(z["__meta__"]))
        arrays = {k: z[k] for k in z.files if k != "__meta__"}
    if meta.get("format", 0) > FORMAT_VERSION:
        raise ValueError("Die Sitzung wurde mit einer neueren Programmversion gespeichert.")
    return meta, arrays
