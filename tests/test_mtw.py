import time

import numpy as np
import pytest
from scipy import signal

from akustik.dsp.generator import PinkNoise
from akustik.dsp.transfer import MultiWindowTransferFunction, TransferFunction

FS = 48000


def run(tf, x, y, frames=8):
    n = tf.length
    res = None
    for i in range(frames):
        s = i * n // 2
        res = tf.update(x[s:s + n], y[s:s + n])
    return res


def test_mtw_grid_is_monotonic_and_constant_resolution():
    tf = MultiWindowTransferFunction(FS)
    f = tf.freqs
    assert np.all(np.diff(f) > 0)
    df = np.diff(f)
    rel = df / f[1:]
    assert np.all(rel[f[1:] > 60] < 0.031)      # ≈ 1/24 Oktave oder feiner
    assert 300 < len(f) < 600                   # statt 16385 Bins
    times = tf.window_times_ms
    assert times[0][0] == pytest.approx(682.7, abs=0.1) and times[-1][0] == pytest.approx(5.33, abs=0.01)


def test_mtw_gain_phase_coherence_of_simple_system():
    rng = np.random.default_rng(0)
    x = rng.standard_normal(32768 * 6)
    y = 0.5 * x
    res = run(MultiWindowTransferFunction(FS), x, y)
    assert np.allclose(res.magnitude_db, -6.02, atol=0.01)
    assert np.allclose(res.phase_deg, 0, atol=0.01)
    assert np.all(res.coherence > 0.999)


def test_mtw_rejects_late_reflection_in_high_frequencies():
    """Direktschall + Reflexion nach 20 ms: lange FFT zeigt Kammfilter, MTW im Hochton kaum."""
    x = PinkNoise(FS, -12).render(32768 * 6)
    d = int(0.020 * FS)
    y = x + 0.7 * np.concatenate([np.zeros(d), x[:-d]])

    def ripple(res, lo, hi):
        sel = (res.freqs > lo) & (res.freqs < hi)
        return np.ptp(res.magnitude_db[sel])

    fft = run(TransferFunction(FS, 32768, averages=8), x, y)
    mtw = run(MultiWindowTransferFunction(FS), x, y)
    assert ripple(fft, 4000, 16000) > 10      # tiefe Kammfilter-Einbrüche
    assert ripple(mtw, 4000, 16000) < 3       # Reflexion liegt außerhalb der kurzen Fenster
    # die Reflexion zählt im kurzen Fenster als unkorrelierte Energie → Kohärenz 1/(1+0.7²)
    assert np.median(mtw.coherence[mtw.freqs > 4000]) == pytest.approx(1 / (1 + 0.49), abs=0.02)


def test_mtw_is_fast():
    tf = MultiWindowTransferFunction(FS)
    x = np.random.default_rng(1).standard_normal(32768)
    tf.update(x, x)
    t0 = time.perf_counter()
    for _ in range(10):
        tf.update(x, x, smoothing=24)
    assert (time.perf_counter() - t0) / 10 < 0.015
