"""Module erst beim ersten Gebrauch laden (schnellerer Programmstart).

``scipy.signal`` allein kostet beim Import rund 2 s. Es wird erst gebraucht, wenn tatsächlich gefiltert
wird; ``main`` lädt es kurz nach dem Öffnen des Fensters im Hintergrund vor.
"""

from __future__ import annotations

import importlib


class LazyModule:
    def __init__(self, name: str):
        self.__dict__["_name"] = name
        self.__dict__["_mod"] = None

    def _load(self):
        mod = self.__dict__["_mod"]
        if mod is None:
            mod = importlib.import_module(self.__dict__["_name"])
            self.__dict__["_mod"] = mod
        return mod

    def __getattr__(self, attr):
        return getattr(self._load(), attr)


signal = LazyModule("scipy.signal")
wavfile = LazyModule("scipy.io.wavfile")


def preload() -> None:
    """Im Hintergrund aufrufen: lädt die großen Module, bevor sie gebraucht werden."""
    for m in (signal, wavfile):
        try:
            m._load()  # noqa: SLF001
        except Exception:  # noqa: BLE001 – wird beim echten Gebrauch erneut versucht und gemeldet
            pass
