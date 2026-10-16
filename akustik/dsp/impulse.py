"""Impulsantwort-Messung: Sweep-Erzeugung, Entfaltung, Darstellungsgrößen."""

from __future__ import annotations

import numpy as np
from .._lazy import signal


def exp_sweep(f1: float, f2: float, duration: float, fs: float, fade: float = 0.02) -> np.ndarray:
    """Exponentieller Sinus-Sweep (Farina), Amplitude 1, mit Ein-/Ausblendung."""
    n = int(round(duration * fs))
    t = np.arange(n) / fs
    r = np.log(f2 / f1)
    x = np.sin(2 * np.pi * f1 * duration / r * (np.exp(t * r / duration) - 1))
    nf = max(1, int(fade * fs))
    ramp = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, nf))
    x[:nf] *= ramp
    x[-nf:] *= ramp[::-1]
    return x


def deconvolve(recorded: np.ndarray, reference: np.ndarray, fs: float,
               f_lo: float = 20.0, f_hi: float | None = None,
               regularization_db: float = -60.0) -> np.ndarray:
    """Impulsantwort = IFFT(Y / X) mit frequenzabhängiger Regularisierung.

    ``reference`` ist entweder das abgespielte Signal oder – besser – die per
    Loopback mitaufgenommene Referenz (kompensiert Interface-Latenz und -Frequenzgang).
    """
    n = len(recorded) + len(reference)
    nfft = 1 << (n - 1).bit_length()
    X = np.fft.rfft(reference, nfft)
    Y = np.fft.rfft(recorded, nfft)
    f = np.fft.rfftfreq(nfft, 1 / fs)
    f_hi = f_hi or fs / 2 * 0.95
    px = np.abs(X) ** 2
    eps_in = px.max() * 10 ** (regularization_db / 10)
    eps = np.where((f >= f_lo) & (f <= f_hi), eps_in, px.max())
    H = Y * np.conj(X) / (px + eps)
    h = np.fft.irfft(H, nfft)
    return h[: len(recorded)]


def ir_start(h: np.ndarray, threshold_db: float = -20.0) -> int:
    """Beginn der IR nach ISO 3382-1: erstes Überschreiten von Max − 20 dB."""
    e = h**2
    idx = np.nonzero(e >= e.max() * 10 ** (threshold_db / 10))[0]
    return int(idx[0]) if len(idx) else 0


def trim(h: np.ndarray, fs: float, pre_ms: float = 2.0, length_s: float | None = None) -> tuple[np.ndarray, int]:
    """Schneidet die IR ab ``pre_ms`` vor ihrem Beginn. Liefert (IR, Startindex)."""
    s = max(0, ir_start(h) - int(pre_ms * 1e-3 * fs))
    e = len(h) if length_s is None else min(len(h), s + int(length_s * fs))
    return h[s:e], s


def to_db(x: np.ndarray, floor: float = -200.0) -> np.ndarray:
    with np.errstate(divide="ignore"):
        return np.maximum(20 * np.log10(np.abs(x)), floor)


def log_view(h: np.ndarray) -> np.ndarray:
    """|h| in dB, normiert auf Maximum."""
    return to_db(h / (np.abs(h).max() + 1e-30))


def etc(h: np.ndarray) -> np.ndarray:
    """Energy Time Curve: Hüllkurve (Hilbert) in dB, normiert."""
    env = np.abs(signal.hilbert(h))
    return to_db(env / (env.max() + 1e-30))


def frequency_response(h: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    nfft = 1 << max(14, (len(h) - 1).bit_length())
    H = np.fft.rfft(h, nfft)
    f = np.fft.rfftfreq(nfft, 1 / fs)
    with np.errstate(divide="ignore"):
        mag = 20 * np.log10(np.abs(H) + 1e-30)
    return f, mag, np.degrees(np.angle(H))


def spectrogram(h: np.ndarray, fs: float, nfft: int = 1024, overlap: float = 0.9):
    """Spektrogramm in dB: (Zeiten, Frequenzen, Matrix[t, f])."""
    nper = min(nfft, len(h))
    f, t, S = signal.spectrogram(h, fs, window="hann", nperseg=nper,
                                 noverlap=int(nper * overlap), mode="psd")
    with np.errstate(divide="ignore"):
        db = 10 * np.log10(S + 1e-30)
    return t, f, (db - db.max()).T
