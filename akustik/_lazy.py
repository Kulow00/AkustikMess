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


def signal_ready() -> bool:
    """True, sobald scipy.signal geladen ist (Aufrufe blockieren dann nicht mehr)."""
    import sys  # noqa: PLC0415
    if signal.__dict__["_mod"] is not None:
        return True
    # schon anderweitig vollständig importiert? (Während des Imports steht das Modul bereits halb geladen
    # in sys.modules – dann wäre ein Zugriff blockierend.)
    m = sys.modules.get("scipy.signal")
    return m is not None and not getattr(getattr(m, "__spec__", None), "_initializing", False)


_preload_thread = None


def preload_async() -> None:
    """Vorladen in einem Hintergrund-Thread starten (höchstens einmal)."""
    import threading  # noqa: PLC0415
    global _preload_thread
    if _preload_thread is None and not signal_ready():
        _preload_thread = threading.Thread(target=preload, name="Vorladen", daemon=True)
        _preload_thread.start()
