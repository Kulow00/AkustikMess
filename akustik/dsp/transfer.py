"""Zweikanal-Übertragungsfunktion (Referenz → Messung) mit Kohärenz."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .spectrum import Averager, fractional_smooth, make_window


@dataclass
class TransferResult:
    freqs: np.ndarray
    H: np.ndarray            # komplexe Übertragungsfunktion
    coherence: np.ndarray    # 0..1

    @property
    def magnitude_db(self) -> np.ndarray:
        with np.errstate(divide="ignore"):
            return 20 * np.log10(np.abs(self.H))

    @property
    def phase_deg(self) -> np.ndarray:
        return np.degrees(np.angle(self.H))


class TransferFunction:
    """H1-Schätzer: H = Gxy / Gxx, gemittelte Kreuz- und Autospektren."""

    def __init__(self, fs: float, fft_size: int = 16384, window: str = "Hann",
                 averages: int = 8, exponential: bool = False):
        self.fs = fs
        self.configure(fft_size, window, averages, exponential)

    def configure(self, fft_size: int, window: str, averages: int, exponential: bool) -> None:
        self.fft_size = int(fft_size)
        self.window = make_window(window, self.fft_size)
        self.freqs = np.fft.rfftfreq(self.fft_size, 1 / self.fs)
        self.avg = Averager(averages, exponential)

    def reset(self) -> None:
        self.avg.reset()

    @property
    def length(self) -> int:
        """Benötigte Samples je Kanal und Aktualisierung."""
        return self.fft_size

    def update(self, ref: np.ndarray, meas: np.ndarray, smoothing: int | None = None) -> TransferResult:
        X = np.fft.rfft(np.asarray(ref, float) * self.window)
        Y = np.fft.rfft(np.asarray(meas, float) * self.window)
        gxy, gxx, gyy = self.avg.update(np.conj(X) * Y, np.abs(X) ** 2, np.abs(Y) ** 2)
        return _finish(self.freqs, gxy, gxx, gyy, smoothing)


def _finish(f, gxy, gxx, gyy, smoothing) -> TransferResult:
    """H, Kohärenz und Glättung aus gemittelten Kreuz-/Autospektren."""
    tiny = 1e-30
    H = gxy / (gxx + tiny)
    coh = np.clip(np.abs(gxy) ** 2 / (gxx * gyy + tiny), 0, 1)
    if smoothing:
        # Betrag als Leistungsmittel, Phase aus dem normierten Zeiger, Kohärenz direkt –
        # komplexes Mitteln von Gxy würde bei Phasendrehung im Fenster auslöschen.
        mag = np.sqrt(fractional_smooth(f, np.abs(H) ** 2, smoothing))
        ph = np.angle(fractional_smooth(f, H / (np.abs(H) + tiny), smoothing))
        H = mag * np.exp(1j * ph)
        coh = fractional_smooth(f, coh, smoothing)
    return TransferResult(f, H, coh)


class MultiWindowTransferFunction:
    """Multi-Time-Window-Übertragungsfunktion (MTW).

    Mehrere FFT-Größen (z. B. 32768 … 256 Samples) arbeiten parallel; jede
    liefert nur den Frequenzbereich, in dem ihre Auflösung gerade ausreicht
    (Bin-Abstand ≤ ``resolution`` × Frequenz, Standard ≈ 1/24 Oktave). Ergebnis:
    • ca. gleich viele Punkte pro Oktave statt tausender Punkte im Hochton,
    • lange Zeitfenster im Bass (feine Auflösung), kurze im Hochton – späte
      Reflexionen fallen dort aus dem Fenster, Betrag und Kohärenz werden ruhiger.

    Alle Fenstergrößen werten dieselbe Zeitspanne (= größte FFT) aus: kleine
    FFTs mitteln dazu über viele 50 %-überlappende Abschnitte.
    """

    def __init__(self, fs: float, max_fft: int = 32768, min_fft: int = 256,
                 resolution: float = 0.03, averages: int = 8, exponential: bool = False):
        self.fs = fs
        self.max_fft, self.min_fft, self.resolution = int(max_fft), int(min_fft), resolution
        sizes = []
        n = self.max_fft
        while n >= self.min_fft:
            sizes.append(n)
            n //= 2
        # N ist fein genug ab f ≥ fs / (N · resolution); jede Größe deckt bis zur nächsten ab
        starts = [0.0] + [fs / (s * resolution) for s in sizes[1:]]
        ends = starts[1:] + [fs / 2 + 1]
        self.bands = []
        freq_parts = []
        for size, lo, hi in zip(sizes, starts, ends):
            f = np.fft.rfftfreq(size, 1 / fs)
            idx = np.nonzero((f > 0) & (f >= lo) & (f < hi))[0]
            if len(idx):
                self.bands.append((size, make_window("Hann", size), idx))
                freq_parts.append(f[idx])
        self.freqs = np.concatenate(freq_parts)
        self.avg = Averager(averages, exponential)

    @property
    def length(self) -> int:
        return self.max_fft

    @property
    def window_times_ms(self) -> list[tuple[float, float, float]]:
        """(Fensterlänge ms, ab Frequenz, bis Frequenz) je Fenstergröße."""
        out = []
        for size, _, idx in self.bands:
            f = np.fft.rfftfreq(size, 1 / self.fs)[idx]
            out.append((1000 * size / self.fs, float(f[0]), float(f[-1])))
        return out

    def reset(self) -> None:
        self.avg.reset()

    def update(self, ref: np.ndarray, meas: np.ndarray, smoothing: int | None = None) -> TransferResult:
        ref = np.asarray(ref, float)[-self.max_fft:]
        meas = np.asarray(meas, float)[-self.max_fft:]
        parts_xy, parts_xx, parts_yy = [], [], []
        for size, win, idx in self.bands:
            hop = size // 2
            segs_x = np.lib.stride_tricks.sliding_window_view(ref, size)[::hop]
            segs_y = np.lib.stride_tricks.sliding_window_view(meas, size)[::hop]
            X = np.fft.rfft(segs_x * win, axis=1)[:, idx]
            Y = np.fft.rfft(segs_y * win, axis=1)[:, idx]
            parts_xy.append(np.mean(np.conj(X) * Y, axis=0))
            parts_xx.append(np.mean(np.abs(X) ** 2, axis=0))
            parts_yy.append(np.mean(np.abs(Y) ** 2, axis=0))
        gxy, gxx, gyy = self.avg.update(np.concatenate(parts_xy), np.concatenate(parts_xx),
                                        np.concatenate(parts_yy))
        return _finish(self.freqs, gxy, gxx, gyy, smoothing)


def find_delay(ref: np.ndarray, meas: np.ndarray, max_delay: int | None = None) -> int:
    """Laufzeit (Samples, ``meas`` hinter ``ref``) per PHAT-Kreuzkorrelation."""
    n = len(ref) + len(meas)
    nfft = 1 << (n - 1).bit_length()
    X = np.fft.rfft(ref, nfft)
    Y = np.fft.rfft(meas, nfft)
    cross = np.conj(X) * Y
    cross /= np.abs(cross) + 1e-20
    r = np.fft.irfft(cross, nfft)
    limit = len(meas) if max_delay is None else min(max_delay, len(meas))
    return int(np.argmax(np.abs(r[:limit])))
