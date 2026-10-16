"""Frequenzbewertungen A, C, Z nach IEC 61672-1."""

from __future__ import annotations

import numpy as np
from scipy import signal

F1, F2, F3, F4 = 20.598997, 107.65265, 737.86223, 12194.217
A1000 = 1.9997
C1000 = 0.0619

CURVES = ("A", "C", "Z")


def weighting_db(f: np.ndarray | float, curve: str) -> np.ndarray:
    """Analytische Bewertungskurve in dB."""
    f = np.asarray(f, dtype=float)
    if curve == "Z":
        return np.zeros_like(f)
    f2 = f * f
    with np.errstate(divide="ignore"):
        if curve == "A":
            r = (F4**2 * f2**2) / (
                (f2 + F1**2) * np.sqrt((f2 + F2**2) * (f2 + F3**2)) * (f2 + F4**2)
            )
            return 20 * np.log10(r) + A1000
        if curve == "C":
            r = (F4**2 * f2) / ((f2 + F1**2) * (f2 + F4**2))
            return 20 * np.log10(r) + C1000
    raise ValueError(f"Unbekannte Bewertung: {curve}")


def weighting_sos(curve: str, fs: float) -> np.ndarray | None:
    """Digitales Bewertungsfilter (bilineare Transformation), 0 dB bei 1 kHz.

    Gibt ``None`` für Z (keine Bewertung) zurück.
    """
    if curve == "Z":
        return None
    w = lambda f: 2 * np.pi * f  # noqa: E731
    if curve == "A":
        zeros = [0, 0, 0, 0]
        poles = [-w(F1), -w(F1), -w(F2), -w(F3), -w(F4), -w(F4)]
    elif curve == "C":
        zeros = [0, 0]
        poles = [-w(F1), -w(F1), -w(F4), -w(F4)]
    else:
        raise ValueError(f"Unbekannte Bewertung: {curve}")
    z, p, k = signal.bilinear_zpk(zeros, poles, 1.0, fs)
    _, h = signal.freqz_zpk(z, p, k, worN=[1000.0], fs=fs)
    k = k / abs(h[0])
    return signal.zpk2sos(z, p, k)
