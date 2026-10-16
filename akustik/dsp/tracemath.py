"""Rechnen mit Messkurven: Differenz, Summe mit Laufzeit/Polarität, Ausrichtung."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def wrap_deg(p: np.ndarray) -> np.ndarray:
    return (np.asarray(p) + 180.0) % 360.0 - 180.0


def to_complex(mag_db: np.ndarray, phase_deg: np.ndarray) -> np.ndarray:
    return 10 ** (np.asarray(mag_db) / 20) * np.exp(1j * np.radians(phase_deg))


def same_grid(fa: np.ndarray, fb: np.ndarray) -> bool:
    return len(fa) == len(fb) and np.allclose(fa, fb)


def resample(f: np.ndarray, values: np.ndarray, grid: np.ndarray) -> np.ndarray:
    """Interpoliert reelle oder komplexe Werte (log. Frequenz) auf ``grid``."""
    lf, lg = np.log10(f), np.log10(grid)
    if np.iscomplexobj(values):
        return np.interp(lg, lf, values.real) + 1j * np.interp(lg, lf, values.imag)
    return np.interp(lg, lf, values)


def difference(fa, mag_a, ph_a, coh_a, fb, mag_b, ph_b, coh_b):
    """A − B: Betrag in dB, Phase (gewickelt), Kohärenz = Minimum beider.

    Liefert (f, mag, phase, coh) auf dem Raster von A (B wird bei Bedarf interpoliert).
    """
    if not same_grid(fa, fb):
        sel = (fa >= fb[0]) & (fa <= fb[-1])
        fa, mag_a, ph_a, coh_a = fa[sel], mag_a[sel], ph_a[sel], coh_a[sel]
        hb = resample(fb, to_complex(mag_b, ph_b), fa)
        mag_b = 20 * np.log10(np.abs(hb) + 1e-30)
        ph_b = np.degrees(np.angle(hb))
        coh_b = resample(fb, coh_b, fa)
    return fa, mag_a - mag_b, wrap_deg(ph_a - ph_b), np.minimum(coh_a, coh_b)


def shifted(f: np.ndarray, H: np.ndarray, delay_ms: float = 0.0,
            invert: bool = False, gain_db: float = 0.0) -> np.ndarray:
    """H mit zusätzlicher Laufzeit, Polarität und Pegel."""
    g = 10 ** (gain_db / 20) * (-1 if invert else 1)
    return H * g * np.exp(-2j * np.pi * f * delay_ms * 1e-3)


@dataclass
class Alignment:
    delay_ms: float
    invert: bool
    gain_db: float              # Summenpegel im Bereich relativ zur besseren Einzelkurve
    loss_db: float              # Abstand zur idealen (phasengleichen) Summe


def best_alignment(f: np.ndarray, Ha: np.ndarray, Hb: np.ndarray, f_lo: float, f_hi: float,
                   max_delay_ms: float = 20.0, step_ms: float = 0.01,
                   gain_b_db: float = 0.0) -> Alignment:
    """Laufzeit und Polarität für B, bei der A+B im Übergangsbereich maximal addiert.

    Bewertet wird gleichmäßig pro Oktave (log. Raster). Bei mehreren fast gleich
    guten Lösungen (Periodizität) gewinnt die kleinste Laufzeit.
    """
    grid = np.geomspace(max(f_lo, f[0]), min(f_hi, f[-1]), 200)
    a = resample(f, Ha, grid)
    b = resample(f, Hb, grid) * 10 ** (gain_b_db / 20)
    taus = np.arange(-max_delay_ms, max_delay_ms + step_ms / 2, step_ms)
    rot = np.exp(-2j * np.pi * grid[None, :] * taus[:, None] * 1e-3)
    best = None
    for invert in (False, True):
        s = a[None, :] + (-b if invert else b)[None, :] * rot
        score = 10 * np.log10(np.mean(np.abs(s) ** 2, axis=1) + 1e-30)
        # lokale Maxima (periodische Mehrfachlösungen); fast gleich gute → kleinste Laufzeit
        inner = np.nonzero((score[1:-1] >= score[:-2]) & (score[1:-1] >= score[2:]))[0] + 1
        peaks = np.concatenate([inner, [0, len(score) - 1]])
        cand = peaks[score[peaks] >= score.max() - 0.05]
        i = cand[np.argmin(np.abs(taus[cand]))]
        if best is None or score[i] > best[0] + 0.05:
            best = (score[i], taus[i], invert)
    score, tau, invert = best
    single = 10 * np.log10(max(np.mean(np.abs(a) ** 2), np.mean(np.abs(b) ** 2)) + 1e-30)
    ideal = 10 * np.log10(np.mean((np.abs(a) + np.abs(b)) ** 2) + 1e-30)
    return Alignment(float(round(tau, 4)), bool(invert), float(score - single), float(ideal - score))
