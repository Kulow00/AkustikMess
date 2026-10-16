"""Schallpegelmesser nach IEC 61672-1 (Software-Teil).

Konvention: ``cal_db`` ist der Schalldruckpegel, der einem Effektivwert von 1.0
(0 dBFS RMS) am Eingang entspricht. Pegel = 10·log10(mittleres Quadrat) + cal_db.
"""

from __future__ import annotations

import numpy as np
from .._lazy import signal

from .weighting import CURVES, weighting_sos

TIME_WEIGHTINGS = {"F": 0.125, "S": 1.0}
IMPULSE_RISE, IMPULSE_FALL = 0.035, 1.5
TINY = 1e-20


def level(ms: float, cal_db: float) -> float:
    return float(10 * np.log10(ms + TINY) + cal_db)


def calibration_offset(x: np.ndarray, reference_db: float) -> float:
    """Kalibrierung mit Schallkalibrator (z. B. 94 dB bei 1 kHz)."""
    ms = float(np.mean(np.asarray(x, float) ** 2))
    return reference_db - 10 * np.log10(ms + TINY)


class SPLMeter:
    """Verarbeitet fortlaufende Blöcke und liefert aktuelle Pegelwerte.

    Kennwerte (Schlüssel): z. B. ``LAF``, ``LAS``, ``LAI``, ``LAeq``, ``LCpeak``,
    ``LAFmax``, ``LAFmin`` – für jede Bewertung A, C, Z.
    """

    def __init__(self, fs: float, cal_db: float = 100.0):
        self.fs = fs
        self.cal_db = cal_db
        self._sos = {c: weighting_sos(c, fs) for c in CURVES}
        self.reset()

    def reset(self) -> None:
        self._zi = {c: (signal.sosfilt_zi(s) * 0 if s is not None else None)
                    for c, s in self._sos.items()}
        self._exp = {(c, tw): 0.0 for c in CURVES for tw in ("F", "S", "I")}
        self._impulse_rise_zi = {c: 0.0 for c in CURVES}
        self._sum = {c: 0.0 for c in CURVES}
        self._count = 0
        self._peak_max = {c: 0.0 for c in CURVES}
        self.current: dict[str, float] = {}
        self.maxima: dict[str, float] = {}
        self.minima: dict[str, float] = {}
        self.block_energy: dict[str, float] = {}  # mittl. Quadrat des letzten Blocks

    def _filter(self, curve: str, x: np.ndarray) -> np.ndarray:
        sos = self._sos[curve]
        if sos is None:
            return x
        y, self._zi[curve] = signal.sosfilt(sos, x, zi=self._zi[curve])
        return y

    def _exp_avg(self, key, y2: np.ndarray, tau: float) -> np.ndarray:
        a = 1 - np.exp(-1 / (self.fs * tau))
        out, zf = signal.lfilter([a], [1, -(1 - a)], y2, zi=[(1 - a) * self._exp[key]])
        self._exp[key] = float(out[-1])
        return out

    def _impulse(self, curve: str, y2: np.ndarray) -> float:
        # schneller Anstieg (35 ms), danach Spitzenwert-Halter mit 1.5 s Abfall
        a = 1 - np.exp(-1 / (self.fs * IMPULSE_RISE))
        rise, _ = signal.lfilter([a], [1, -(1 - a)], y2,
                                 zi=[(1 - a) * self._impulse_rise_zi[curve]])
        self._impulse_rise_zi[curve] = float(rise[-1])
        step = 16
        r = rise[::step]
        decay = np.exp(-step / (self.fs * IMPULSE_FALL))
        v = self._exp[(curve, "I")]
        for s in r:
            v = s if s > v else v * decay
        self._exp[(curve, "I")] = v
        return v

    def process(self, x: np.ndarray) -> dict[str, float]:
        x = np.asarray(x, float)
        if not len(x):
            return self.current
        self._count += len(x)
        cur = {}
        for c in CURVES:
            y = self._filter(c, x)
            y2 = y * y
            for tw, tau in TIME_WEIGHTINGS.items():
                out = self._exp_avg((c, tw), y2, tau)
                cur[f"L{c}{tw}"] = level(out[-1], self.cal_db)
                self._track(f"L{c}{tw}", level(out.max(), self.cal_db), level(out.min(), self.cal_db))
            cur[f"L{c}I"] = level(self._impulse(c, y2), self.cal_db)
            self._track(f"L{c}I", cur[f"L{c}I"], cur[f"L{c}I"])
            self._sum[c] += y2.sum()
            self.block_energy[c] = float(y2.mean())
            cur[f"L{c}eq"] = level(self._sum[c] / self._count, self.cal_db)
            self._peak_max[c] = max(self._peak_max[c], float(np.abs(y).max()))
            cur[f"L{c}peak"] = float(20 * np.log10(np.abs(y).max() + TINY) + self.cal_db)
            cur[f"L{c}peakmax"] = float(20 * np.log10(self._peak_max[c] + TINY) + self.cal_db)
        for k, v in self.maxima.items():
            cur[f"{k}max"] = v
        for k, v in self.minima.items():
            cur[f"{k}min"] = v
        cur["Dauer"] = self._count / self.fs
        self.current = cur
        return cur

    def _track(self, key: str, hi: float, lo: float) -> None:
        # erste 0.5 s ignorieren (Einschwingen der Zeitbewertung)
        if self._count < 0.5 * self.fs:
            return
        self.maxima[key] = max(self.maxima.get(key, -np.inf), hi)
        self.minima[key] = min(self.minima.get(key, np.inf), lo)
