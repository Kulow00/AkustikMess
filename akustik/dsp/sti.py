"""Sprachübertragungsindex STI / STIPA aus der Impulsantwort (IEC 60268-16, indirekte Methode).

Grenzen dieser Implementierung: ohne Hörmaskierung und Hörschwelle (dafür wären
kalibrierte absolute Bandpegel nötig). Störgeräusch kann über einen
Signal-Rausch-Abstand pro Oktavband berücksichtigt werden.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from .._lazy import signal

from .octave import band_filter_sos
from .room import lundeby

STI_BANDS = [125, 250, 500, 1000, 2000, 4000, 8000]
MOD_FREQS = [0.63, 0.8, 1.0, 1.25, 1.6, 2.0, 2.5, 3.15, 4.0, 5.0, 6.3, 8.0, 10.0, 12.5]
STIPA_MOD = {
    125: (1.6, 8.0), 250: (1.0, 5.0), 500: (0.63, 3.15), 1000: (2.0, 10.0),
    2000: (1.25, 6.25), 4000: (0.8, 4.0), 8000: (2.5, 12.5),
}
ALPHA_MALE = [0.085, 0.127, 0.230, 0.233, 0.309, 0.224, 0.173]
BETA_MALE = [0.085, 0.078, 0.065, 0.011, 0.047, 0.095]

RATINGS = [
    (0.76, "A+"), (0.72, "A"), (0.68, "B"), (0.64, "C"), (0.60, "D"), (0.56, "E"),
    (0.52, "F"), (0.48, "G"), (0.44, "H"), (0.40, "I"), (0.36, "J"), (0.0, "U"),
]


def rating(sti: float) -> str:
    for limit, name in RATINGS:
        if sti >= limit:
            return name
    return "U"


def mtf_from_energy(e: np.ndarray, fs: float, mod_freqs) -> np.ndarray:
    """m(F) = |Σ e(t)·exp(−j2πFt)| / Σ e(t) (Schroeder 1981)."""
    t = np.arange(len(e)) / fs
    total = e.sum()
    if total <= 0:
        return np.zeros(len(mod_freqs))
    return np.array([abs(np.sum(e * np.exp(-2j * np.pi * F * t))) / total for F in mod_freqs])


def sti_from_mtf(m: list[np.ndarray]) -> tuple[float, np.ndarray]:
    """STI aus Modulationsübertragungswerten je Band (Liste von Arrays)."""
    mti = []
    for mk in m:
        mk = np.clip(mk, 1e-6, 1 - 1e-6)
        snr = np.clip(10 * np.log10(mk / (1 - mk)), -15, 15)
        mti.append(np.mean((snr + 15) / 30))
    mti = np.array(mti)
    sti = np.dot(ALPHA_MALE, mti) - np.dot(BETA_MALE, np.sqrt(mti[:-1] * mti[1:]))
    return float(np.clip(sti, 0, 1)), mti


@dataclass
class STIResult:
    method: str
    sti: float
    rating: str
    mti: np.ndarray            # je Oktavband 125 Hz … 8 kHz
    mtf: list[np.ndarray]      # m(F) je Band


def sti_from_ir(h: np.ndarray, fs: float, method: str = "STI",
                snr_db: list[float] | None = None) -> STIResult:
    h = np.asarray(h, float)
    cross, _ = lundeby(h, fs)  # Messrauschen am Ende der IR abschneiden
    h = h[:cross]
    mtf = []
    for i, fc in enumerate(STI_BANDS):
        if fc * 2 ** 0.5 >= fs / 2:
            raise ValueError("Abtastrate zu niedrig für das 8-kHz-Band")
        hb = signal.sosfilt(band_filter_sos(fc, 1, fs, order=4), h)
        freqs = STIPA_MOD[fc] if method == "STIPA" else MOD_FREQS
        m = mtf_from_energy(hb**2, fs, freqs)
        if snr_db is not None:
            m = m / (1 + 10 ** (-snr_db[i] / 10))
        mtf.append(m)
    sti, mti = sti_from_mtf(mtf)
    return STIResult(method, sti, rating(sti), mti, mtf)
