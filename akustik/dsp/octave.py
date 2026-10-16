"""Bruchteil-Oktavbänder nach IEC 61260-1 (Basis 10)."""

from __future__ import annotations

import numpy as np
from scipy import signal

G = 10 ** (3 / 10)  # Oktavverhältnis Basis 10

NOMINAL = [
    20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160, 200, 250, 315, 400, 500, 630,
    800, 1000, 1250, 1600, 2000, 2500, 3150, 4000, 5000, 6300, 8000, 10000,
    12500, 16000, 20000,
]


def band_centers(fraction: int, fmin: float = 20.0, fmax: float = 20000.0) -> np.ndarray:
    """Exakte Bandmittenfrequenzen für 1/``fraction``-Oktavbänder."""
    b = int(fraction)
    lo = int(np.floor(b * np.log(fmin / 1000) / np.log(G))) - 2
    hi = int(np.ceil(b * np.log(fmax / 1000) / np.log(G))) + 2
    x = np.arange(lo, hi + 1)
    if b % 2:
        fm = 1000 * G ** (x / b)
    else:
        fm = 1000 * G ** ((2 * x + 1) / (2 * b))
    return fm[(fm >= fmin * 0.99) & (fm <= fmax * 1.01)]


def band_edges(fm: np.ndarray | float, fraction: int) -> tuple[np.ndarray, np.ndarray]:
    fm = np.asarray(fm, dtype=float)
    k = G ** (1 / (2 * fraction))
    return fm / k, fm * k


def band_label(fm: float, fraction: int = 3) -> str:
    if fraction in (1, 3):
        nom = min(NOMINAL, key=lambda n: abs(np.log(n / fm)))
        if abs(np.log(nom / fm)) < 0.05:
            fm = nom
    if fm >= 1000:
        v = fm / 1000
        return f"{v:g}k" if v == round(v, 2) else f"{v:.2g}k"
    return f"{fm:g}" if fm == round(fm, 1) else f"{fm:.3g}"


def band_filter_sos(fm: float, fraction: int, fs: float, order: int = 3) -> np.ndarray:
    """Butterworth-Bandpass (IEC 61260 Klasse 1 ähnlich bei order>=3)."""
    lo, hi = band_edges(fm, fraction)
    nyq = fs / 2
    if hi >= nyq * 0.95:
        return signal.butter(order, float(lo), btype="highpass", fs=fs, output="sos")
    return signal.butter(order, [float(lo), float(hi)], btype="bandpass", fs=fs, output="sos")


def band_power_from_spectrum(
    freqs: np.ndarray, power: np.ndarray, centers: np.ndarray, fraction: int
) -> np.ndarray:
    """Summiert ein Leistungsspektrum (Leistung pro Bin) in Bänder.

    Jeder Bin deckt [f − df/2, f + df/2] ab; ein Band erhält genau den Anteil
    jedes Bins, der innerhalb seiner Grenzen liegt (stückweise konstante
    Leistungsdichte). Dadurch bleiben auch Bänder, die schmaler als ein Bin
    sind, stetig – ohne Spitzen bei Bändern, die zufällig einen Bin enthalten.
    """
    df = freqs[1] - freqs[0]
    lo, hi = band_edges(centers, fraction)
    upper = np.concatenate([[freqs[0] - df / 2], freqs + df / 2])
    cum = np.concatenate([[0.0], np.cumsum(power)])
    return np.interp(hi, upper, cum) - np.interp(lo, upper, cum)
