import numpy as np
import pytest

from akustik.audio.engine import AudioConfig, SimulatedEngine, SIMULATION
from akustik.dsp import targets, tracemath
from akustik.dsp.generator import PeriodicPinkNoise, PinkNoise
from akustik.dsp.spectrum import make_window, power_spectrum
from akustik.dsp.transfer import TransferFunction

FS = 48000


# --- Kurven-Rechnung ----------------------------------------------------------

def test_difference_same_and_different_grid():
    f = np.geomspace(20, 20000, 500)
    a = (np.full_like(f, -3.0), np.full_like(f, 170.0), np.full_like(f, 0.9))
    b = (np.full_like(f, -9.0), np.full_like(f, -170.0), np.full_like(f, 0.5))
    fd, mag, ph, coh = tracemath.difference(f, *a, f, *b)
    assert np.allclose(mag, 6.0) and np.allclose(ph, -20.0) and np.allclose(coh, 0.5)
    f2 = np.geomspace(30, 15000, 333)
    fd, mag, ph, _ = tracemath.difference(f, *a, f2, b[0][:333], b[1][:333], b[2][:333])
    assert fd[0] >= 30 and fd[-1] <= 15000
    assert np.allclose(mag, 6.0, atol=1e-6) and np.allclose(ph, -20.0, atol=1e-6)


def _crossover(f, fc=100.0, delay_b_ms=0.0, invert_b=False):
    """Tiefpass (Sub) und Hochpass (Top) 2. Ordnung; Top hat Zusatz-Laufzeit."""
    s = 1j * f / fc
    low = 1 / (s**2 + np.sqrt(2) * s + 1)
    high = s**2 / (s**2 + np.sqrt(2) * s + 1)
    high = tracemath.shifted(f, high, delay_b_ms, invert_b)
    return low, high


def test_best_alignment_recovers_delay_and_polarity():
    f = np.geomspace(20, 20000, 4000)
    sub, top = _crossover(f, delay_b_ms=3.2, invert_b=True)
    # Butterworth 2. Ordnung braucht selbst Polaritätsumkehr → zusammen „normal“ + 3.2 ms
    res = tracemath.best_alignment(f, sub, top, 60, 160)
    reference = tracemath.best_alignment(f, *_crossover(f), 60, 160)
    assert res.delay_ms == pytest.approx(reference.delay_ms - 3.2, abs=0.02)
    assert res.invert != reference.invert
    assert res.loss_db < reference.loss_db + 0.1
    aligned = sub + tracemath.shifted(f, top, res.delay_ms, res.invert)
    sel = (f > 60) & (f < 160)
    naive = sub + top
    assert np.mean(np.abs(aligned[sel])) > 1.5 * np.mean(np.abs(naive[sel]))


# --- Zielkurven ----------------------------------------------------------------

def test_target_interpolation_and_offset():
    pts = targets.PRESETS["X-Kurve (Kino, ISO 2969)"]
    assert targets.target_db(pts, [1000, 4000, 16000]) == pytest.approx([0, -3, -9])
    f = np.geomspace(20, 20000, 300)
    meas = targets.target_db(pts, f) + 7.5
    assert targets.auto_offset(f, meas, targets.target_db(pts, f)) == pytest.approx(7.5)


def test_parse_target_formats():
    text = "* Hauskurve\nFreq;dB\n20;6,5\n1000;0\n20000;-6\n"
    assert targets.parse_target(text) == [(20.0, 6.5), (1000.0, 0.0), (20000.0, -6.0)]
    frd = "# Mikrofon\n20.0 -1.5 -12.0\n1000 0.0 0\n20000 2.1 5\n"
    assert targets.parse_target(frd)[0] == (20.0, -1.5)
    with pytest.raises(ValueError):
        targets.parse_target("nichts brauchbares")


# --- Periodisches rosa Rauschen -----------------------------------------------

def test_periodic_pink_is_periodic_and_exactly_pink():
    n = 16384
    g = PeriodicPinkNoise(FS, -20, length=n)
    x = g.render(3 * n)
    assert np.allclose(x[:n], x[n:2 * n])
    assert 20 * np.log10(np.sqrt(np.mean(x**2))) == pytest.approx(-20, abs=0.01)
    X = np.abs(np.fft.rfft(x[:n])) ** 2
    f = np.fft.rfftfreq(n, 1 / FS)
    sel = (f > 40) & (f < 16000)
    slope = np.polyfit(np.log10(f[sel]), 10 * np.log10(X[sel]), 1)[0]
    assert slope == pytest.approx(-10.0, abs=0.01)  # −3 dB/Oktave = −10 dB/Dekade
    assert np.ptp(10 * np.log10(X[sel] * f[sel])) < 1e-6  # keine Streuung je Bin


def test_periodic_noise_gives_steadier_transfer_function():
    def spread(gen):
        tf = TransferFunction(FS, 16384, averages=1)
        x = gen.render(16384 * 4)
        y = np.convolve(x, [0.5, 0.3, 0.1])[: len(x)]
        mags = [tf.update(x[i:i + 16384], y[i:i + 16384]).magnitude_db for i in (0, 8192, 16384)]
        return np.std(mags, axis=0)[100:4000].mean()
    assert spread(PeriodicPinkNoise(FS, -12, 16384)) < spread(PinkNoise(FS, -12))


# --- Ein-/Ausblenden des Generators ------------------------------------------

def test_generator_fades_in_and_out():
    eng = SimulatedEngine(AudioConfig(input_device=SIMULATION))
    eng.fade_s = 0.1
    eng.set_generator(PinkNoise(FS, -6), [0])
    first = np.abs(eng._render_output(1024, 2)[:64, 0]).max()
    for _ in range(10):
        full = eng._render_output(1024, 2)
    assert first < 0.05 < np.abs(full[:, 0]).max()
    eng.set_generator(None, [])
    assert eng.generator is not None  # läuft noch aus
    for _ in range(10):
        out = eng._render_output(1024, 2)
    assert np.abs(out).max() == 0 and eng.generator is None
    eng.set_generator(PinkNoise(FS, -6), [0])
    eng.mute()
    for _ in range(2):
        out = eng._render_output(1024, 2)
    assert np.abs(out).max() == 0 and eng.generator is None  # Stummschalten ist schnell
