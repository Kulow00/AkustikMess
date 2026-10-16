"""FFT-Spektrum (Einkanal) mit Mittelung und Glättung."""

from __future__ import annotations

import numpy as np
from .._lazy import signal

from .octave import G

WINDOWS = {
    "Hann": "hann",
    "Blackman": "blackman",
    "Blackman-Harris": "blackmanharris",
    "Flat Top": "flattop",
    "Rechteck": "boxcar",
}


def make_window(name: str, n: int) -> np.ndarray:
    return signal.get_window(WINDOWS.get(name, "hann"), n, fftbins=True)


def power_spectrum(x: np.ndarray, window: np.ndarray) -> np.ndarray:
    """Einseitiges Leistungsspektrum: Summe aller Bins = mittleres Quadrat von x."""
    n = len(x)
    X = np.fft.rfft(x * window)
    p = (np.abs(X) ** 2) / (n * np.sum(window**2))
    if n % 2 == 0:
        p[1:-1] *= 2  # letzter Bin ist Nyquist
    else:
        p[1:] *= 2
    return p


class Averager:
    """Mittelung über feste Anzahl Blöcke (FIFO) oder exponentiell."""

    def __init__(self, count: int = 1, exponential: bool = False):
        self.count = max(1, int(count))
        self.exponential = exponential
        self.reset()

    def reset(self) -> None:
        self._items: list = []
        self._state = None

    def update(self, *arrays: np.ndarray):
        if self.exponential:
            if self._state is None or any(
                s.shape != a.shape for s, a in zip(self._state, arrays)
            ):
                self._state = [a.copy() for a in arrays]
            else:
                alpha = 1.0 / self.count
                self._state = [s + alpha * (a - s) for s, a in zip(self._state, arrays)]
            return self._state
        if self._items and self._items[-1][0].shape != arrays[0].shape:
            self._items = []
        self._items.append(arrays)
        if len(self._items) > self.count:
            self._items.pop(0)
        return [np.mean([it[i] for it in self._items], axis=0) for i in range(len(arrays))]


_SMOOTH_CACHE: dict = {}


def _smooth_indices(freqs: np.ndarray, fraction: int) -> tuple[np.ndarray, np.ndarray]:
    key = (len(freqs), float(freqs[-1]), fraction)
    if key not in _SMOOTH_CACHE:
        k = G ** (1 / (2 * fraction))
        lo = np.searchsorted(freqs, freqs / k)
        hi = np.maximum(np.searchsorted(freqs, freqs * k, side="right"), lo + 1)
        if len(_SMOOTH_CACHE) > 32:
            _SMOOTH_CACHE.clear()
        _SMOOTH_CACHE[key] = (lo, hi)
    return _SMOOTH_CACHE[key]


def fractional_smooth(freqs: np.ndarray, values: np.ndarray, fraction: int | None) -> np.ndarray:
    """Gleitender Mittelwert über 1/``fraction`` Oktave je Bin (auch komplex)."""
    if not fraction:
        return values
    lo, hi = _smooth_indices(freqs, fraction)
    cs = np.concatenate([[0], np.cumsum(values)])
    return (cs[hi] - cs[lo]) / (hi - lo)


def peak_frequency(freqs: np.ndarray, power: np.ndarray,
                   fmin: float = 20.0, fmax: float = 20000.0) -> tuple[float, float]:
    """Frequenz und Leistung der stärksten Spektrallinie, genauer als ein FFT-Bin.

    Parabel-Interpolation auf den logarithmierten Betrag (für Hann-Fenster
    Fehler < 1 % eines Bins, bei 64k-FFT/48 kHz also < 0.01 Hz).
    """
    sel = np.nonzero((freqs >= fmin) & (freqs <= fmax))[0]
    if len(sel) < 3:
        return float("nan"), float("nan")
    k = sel[np.argmax(power[sel])]
    if k <= 0 or k >= len(power) - 1:
        return float(freqs[k]), float(power[k])
    a, b, c = np.log(power[k - 1: k + 2] + 1e-300)
    denom = a - 2 * b + c
    delta = 0.5 * (a - c) / denom if denom != 0 else 0.0
    delta = float(np.clip(delta, -0.5, 0.5))
    df = freqs[1] - freqs[0]
    peak = np.exp(b - 0.25 * (a - c) * delta)
    return float(freqs[k] + delta * df), float(peak)


class SpectrumAnalyzer:
    def __init__(self, fs: float, fft_size: int = 16384, window: str = "Hann",
                 averages: int = 4, exponential: bool = False):
        self.fs = fs
        self.configure(fft_size, window, averages, exponential)

    def configure(self, fft_size: int, window: str, averages: int, exponential: bool) -> None:
        self.fft_size = int(fft_size)
        self.window_name = window
        self.window = make_window(window, self.fft_size)
        self.freqs = np.fft.rfftfreq(self.fft_size, 1 / self.fs)
        self.avg = Averager(averages, exponential)

    def update(self, x: np.ndarray) -> np.ndarray:
        p = power_spectrum(np.asarray(x, dtype=float), self.window)
        (avg,) = self.avg.update(p)
        return avg
