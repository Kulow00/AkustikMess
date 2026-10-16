"""Messsignal-Generatoren (blockweise, zustandsbehaftet)."""

from __future__ import annotations

import numpy as np
from scipy import signal

# Paul-Kellet-ähnliches rosa Filter (−3 dB/Oktave, ±0.5 dB von 10 Hz bis 20 kHz @ 48 kHz)
_PINK_B = [0.049922035, -0.095993537, 0.050612699, -0.004408786]
_PINK_A = [1.0, -2.494956002, 2.017265875, -0.522189400]


def db_to_lin(db: float) -> float:
    return 10 ** (db / 20)


class Generator:
    """Basisklasse. ``level_db`` ist der RMS-Pegel in dBFS."""

    name = "Aus"

    def __init__(self, fs: float, level_db: float = -12.0):
        self.fs = fs
        self.level_db = level_db
        self.rng = np.random.default_rng()

    def render(self, n: int) -> np.ndarray:
        return np.zeros(n)


class WhiteNoise(Generator):
    name = "Weißes Rauschen"

    def render(self, n):
        return self.rng.standard_normal(n) * db_to_lin(self.level_db)


class PinkNoise(Generator):
    name = "Rosa Rauschen"

    def __init__(self, fs, level_db=-12.0):
        super().__init__(fs, level_db)
        self._zi = signal.lfilter_zi(_PINK_B, _PINK_A) * 0
        # Normierung auf RMS 1: Energie der Filter-Impulsantwort
        imp = np.zeros(1 << 18)
        imp[0] = 1
        self._RMS_GAIN = 1 / np.sqrt(np.sum(signal.lfilter(_PINK_B, _PINK_A, imp) ** 2))

    def render(self, n):
        w = self.rng.standard_normal(n)
        y, self._zi = signal.lfilter(_PINK_B, _PINK_A, w, zi=self._zi)
        return y * self._RMS_GAIN * db_to_lin(self.level_db)


class PeriodicPinkNoise(Generator):
    """Rosa Rauschen, das sich exakt nach ``length`` Samples wiederholt.

    Stimmt die Periode mit der FFT-Größe überein, enthält jedes Analysefenster
    dasselbe, exakt rosa Spektrum – die Übertragungsfunktion ist schon nach
    wenigen Mittelungen ruhig.
    """

    name = "Rosa Rauschen (periodisch)"

    def __init__(self, fs, level_db=-12.0, length: int = 32768):
        super().__init__(fs, level_db)
        self.length = int(length)
        f = np.fft.rfftfreq(self.length, 1 / fs)
        band = (f >= 20) & (f <= min(20000, fs / 2 * 0.95))
        mag = np.where(band, 1 / np.sqrt(np.maximum(f, 1)), 0.0)
        phase = self.rng.uniform(0, 2 * np.pi, len(f))
        x = np.fft.irfft(mag * np.exp(1j * phase), self.length)
        self.table = x / np.sqrt(np.mean(x**2))
        self._pos = 0

    def render(self, n):
        idx = (self._pos + np.arange(n)) % self.length
        self._pos = int((self._pos + n) % self.length)
        return self.table[idx] * db_to_lin(self.level_db)


class Sine(Generator):
    name = "Sinus"

    def __init__(self, fs, level_db=-12.0, freq=1000.0):
        super().__init__(fs, level_db)
        self.freq = freq
        self._phase = 0.0

    def render(self, n):
        ph = self._phase + 2 * np.pi * self.freq / self.fs * np.arange(1, n + 1)
        self._phase = float(ph[-1] % (2 * np.pi))
        return np.sqrt(2) * db_to_lin(self.level_db) * np.sin(ph)


GENERATORS = {cls.name: cls for cls in (Generator, PinkNoise, PeriodicPinkNoise, WhiteNoise, Sine)}
