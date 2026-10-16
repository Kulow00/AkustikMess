"""Raumakustische Kenngrößen aus der Impulsantwort (ISO 3382-1/-2)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import signal

from .impulse import ir_start
from .octave import band_filter_sos, band_label


def _envelope(e: np.ndarray, win: int) -> tuple[np.ndarray, np.ndarray]:
    """Mittlere Energie in Blöcken der Länge ``win``; liefert (Blockmitten, Werte)."""
    win = max(1, int(win))
    nb = len(e) // win
    if nb < 2:
        return np.array([len(e) / 2]), np.array([e.mean()])
    blocks = e[: nb * win].reshape(nb, win).mean(axis=1)
    centers = np.arange(nb) * win + win / 2
    return centers, blocks


def lundeby(h: np.ndarray, fs: float) -> tuple[int, float]:
    """Lundeby-Verfahren: Schnittpunkt Abklingkurve/Grundrauschen.

    Liefert (Schnittpunkt in Samples, Kompensationsenergie für den
    abgeschnittenen Rest in derselben Einheit wie Σh²).
    """
    e = np.asarray(h, float) ** 2
    n = len(e)
    if n < fs * 0.05 or e.max() <= 0:
        return n, 0.0

    def env_db(win):
        c, env = _envelope(e, win)
        return c, 10 * np.log10(env + 1e-300)

    try:
        # 1) Hüllkurve aus 10-ms-Blöcken, Grundrauschen aus den letzten 10 %
        c, L = env_db(int(0.01 * fs))
        noise_db = 10 * np.log10(e[int(0.9 * n):].mean() + 1e-300)
        cross = n
        slope = intercept = None
        for _ in range(5):
            # 2) Regression vom Maximum bis 10 dB über dem Rauschen
            i0 = int(np.argmax(L))
            below = np.nonzero(L[i0:] < noise_db + 10)[0]
            i1 = i0 + below[0] if len(below) else len(L) - 1
            if i1 - i0 < 2:
                break
            slope, intercept = np.polyfit(c[i0:i1], L[i0:i1], 1)  # dB/Sample
            if slope >= 0:
                break
            new_cross = float(np.clip((noise_db - intercept) / slope, 1, n))
            # 3) neue Blocklänge: ca. 5 Blöcke pro 10 dB Abfall
            c, L = env_db(max(int(-10 / slope / 5), int(0.002 * fs)))
            # 4) Rauschen neu schätzen ab 5 dB unterhalb des Schnittpunkts
            t_noise = min(int(new_cross - 5 / slope), int(0.9 * n))
            noise_db = 10 * np.log10(e[t_noise:].mean() + 1e-300)
            converged = abs(new_cross - cross) < 0.001 * fs
            cross = new_cross
            if converged:
                break
        if slope is None or slope >= 0:
            return n, 0.0
        cross_i = int(np.clip(cross, 1, n))
        # 5) Kompensation: Restenergie der extrapolierten Exponentialkurve
        a = -slope * np.log(10) / 10  # Energieabfall in 1/Sample
        comp = 10 ** ((intercept + slope * cross_i) / 10) / a
        return cross_i, float(max(comp, 0.0))
    except (ValueError, np.linalg.LinAlgError):
        return n, 0.0


def schroeder(h: np.ndarray, fs: float, use_lundeby: bool = True) -> np.ndarray:
    """Schroeder-Rückwärtsintegral in dB (0 dB am Anfang)."""
    e = np.asarray(h, float) ** 2
    cross, comp = lundeby(h, fs) if use_lundeby else (len(e), 0.0)
    e = e[:cross]
    edc = np.cumsum(e[::-1])[::-1] + comp
    with np.errstate(divide="ignore"):
        return 10 * np.log10(edc / edc[0])


def decay_time(edc_db: np.ndarray, fs: float, start_db: float, end_db: float) -> float:
    """Nachhallzeit (auf 60 dB extrapoliert) per Regression im Bereich start..end."""
    i0 = np.nonzero(edc_db <= start_db)[0]
    i1 = np.nonzero(edc_db <= end_db)[0]
    if not len(i0) or not len(i1) or i1[0] - i0[0] < 3:
        return float("nan")
    a, b = i0[0], i1[0]
    t = np.arange(a, b + 1) / fs
    slope, _ = np.polyfit(t, edc_db[a: b + 1], 1)
    return float(-60 / slope) if slope < 0 else float("nan")


def clarity(e: np.ndarray, fs: float, ms: float) -> float:
    k = int(ms * 1e-3 * fs)
    early, late = e[:k].sum(), e[k:].sum()
    return float(10 * np.log10(early / late)) if late > 0 and early > 0 else float("nan")


@dataclass
class BandResult:
    label: str
    center: float | None
    edt: float
    t20: float
    t30: float
    c50: float
    c80: float
    d50: float
    ts_ms: float
    edc_db: np.ndarray = field(repr=False, default=None)


METRICS = [
    ("edt", "EDT [s]"), ("t20", "T20 [s]"), ("t30", "T30 [s]"),
    ("c50", "C50 [dB]"), ("c80", "C80 [dB]"), ("d50", "D50 [%]"), ("ts_ms", "Ts [ms]"),
]

OCTAVES = [63, 125, 250, 500, 1000, 2000, 4000, 8000]


def analyze_band(h: np.ndarray, fs: float, label: str, center: float | None) -> BandResult:
    edc = schroeder(h, fs)
    cross, _ = lundeby(h, fs)
    e = np.asarray(h, float)[:cross] ** 2
    total = e.sum()
    k50 = int(0.05 * fs)
    t = np.arange(len(e)) / fs
    return BandResult(
        label=label, center=center,
        edt=decay_time(edc, fs, 0.0, -10.0),
        t20=decay_time(edc, fs, -5.0, -25.0),
        t30=decay_time(edc, fs, -5.0, -35.0),
        c50=clarity(e, fs, 50), c80=clarity(e, fs, 80),
        d50=float(100 * e[:k50].sum() / total) if total > 0 else float("nan"),
        ts_ms=float(1000 * (t * e).sum() / total) if total > 0 else float("nan"),
        edc_db=edc,
    )


def analyze(h: np.ndarray, fs: float, centers: list[float] = OCTAVES) -> list[BandResult]:
    """Kenngrößen pro Oktavband und breitbandig. ``h`` beginnt idealerweise am Direktschall."""
    h = np.asarray(h, float)
    h = h[max(0, ir_start(h) - int(0.001 * fs)):]
    results = []
    for fc in centers:
        if fc * 2 ** 0.5 >= fs / 2:
            continue
        sos = band_filter_sos(fc, 1, fs, order=3)
        hb = signal.sosfilt(sos, h)
        results.append(analyze_band(hb, fs, band_label(fc, 1), fc))
    results.append(analyze_band(h, fs, "Breitband", None))
    return results
