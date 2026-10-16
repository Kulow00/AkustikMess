import numpy as np
import pytest
from scipy import signal

from akustik.dsp import impulse, octave, room, spectrum, spl, sti, transfer, weighting
from akustik.dsp.generator import PinkNoise, Sine

FS = 48000


def sine(f, seconds, amp=np.sqrt(2)):
    t = np.arange(int(seconds * FS)) / FS
    return amp * np.sin(2 * np.pi * f * t)


def synthetic_room_ir(t60, seconds=None, seed=1):
    seconds = seconds or 1.5 * t60
    rng = np.random.default_rng(seed)
    n = int(seconds * FS)
    t = np.arange(n) / FS
    return rng.standard_normal(n) * np.exp(-3 * np.log(10) * t / t60)


# --- Bänder und Bewertungen -------------------------------------------------

def test_third_octave_centers_contain_nominal():
    c = octave.band_centers(3)
    assert np.any(np.isclose(c, 1000))
    labels = [octave.band_label(f, 3) for f in c]
    assert "31.5" in labels and "1k" in labels and "12.5k" in labels


@pytest.mark.parametrize("f,a,c", [(100, -19.1, -0.3), (1000, 0.0, 0.0), (10000, -2.5, -4.4)])
def test_weighting_table(f, a, c):
    assert weighting.weighting_db(f, "A") == pytest.approx(a, abs=0.1)
    assert weighting.weighting_db(f, "C") == pytest.approx(c, abs=0.1)


def test_digital_weighting_matches_analytic():
    for curve in ("A", "C"):
        sos = weighting.weighting_sos(curve, FS)
        f = np.array([31.5, 100, 1000, 4000, 8000])
        _, h = signal.sosfreqz(sos, worN=f, fs=FS)
        err = 20 * np.log10(np.abs(h)) - weighting.weighting_db(f, curve)
        assert np.all(np.abs(err) < 0.7), (curve, err)  # IEC Klasse-1-Toleranz bis 8 kHz


# --- Spektrum ---------------------------------------------------------------

def test_power_spectrum_parseval_and_band_sum():
    x = sine(1000, 1.0)  # Effektivwert 1
    an = spectrum.SpectrumAnalyzer(FS, 16384)
    p = an.update(x[:16384])
    assert p.sum() == pytest.approx(1.0, rel=0.02)
    centers = octave.band_centers(3)
    bands = octave.band_power_from_spectrum(an.freqs, p, centers, 3)
    assert bands[np.argmin(abs(centers - 1000))] == pytest.approx(1.0, rel=0.05)


def test_fine_bands_narrower_than_bins_are_smooth():
    # weißes Spektrum, 2.9-Hz-Bins, 1/48-Oktave-Bänder unter 100 Hz (schmaler als ein Bin)
    f = np.fft.rfftfreq(16384, 1 / FS)
    power = np.ones_like(f)
    centers = octave.band_centers(48, 20, 100)
    lo, hi = octave.band_edges(centers, 48)
    density = octave.band_power_from_spectrum(f, power, centers, 48) / (hi - lo)
    assert np.allclose(density, 1 / (f[1] - f[0]), rtol=1e-6)  # keine Spitzen
    # Gesamtleistung bleibt erhalten
    all_c = octave.band_centers(3, 20, 20000)
    assert octave.band_power_from_spectrum(f, power, all_c, 3).sum() == pytest.approx(
        np.sum(power[(f > octave.band_edges(all_c[0], 3)[0]) & (f < octave.band_edges(all_c[-1], 3)[1])]),
        rel=0.01)


def test_pink_noise_level_and_slope():
    g = PinkNoise(FS, level_db=-20)
    x = g.render(FS * 10)
    assert 20 * np.log10(np.sqrt(np.mean(x**2))) == pytest.approx(-20, abs=1.0)
    f, p = signal.welch(x, FS, nperseg=8192)
    centers = np.array([125, 250, 500, 1000, 2000, 4000])
    bands = octave.band_power_from_spectrum(f, p * (f[1] - f[0]), centers, 1)
    lv = 10 * np.log10(bands)
    assert np.ptp(lv) < 1.5  # rosa: gleiche Energie pro Oktave


def test_sine_generator_rms():
    x = Sine(FS, level_db=-6, freq=1000).render(FS)
    assert 20 * np.log10(np.sqrt(np.mean(x**2))) == pytest.approx(-6, abs=0.05)


# --- Übertragungsfunktion -----------------------------------------------------

def test_transfer_function_gain_delay_coherence():
    rng = np.random.default_rng(0)
    n, d = 16384, 480
    tf = transfer.TransferFunction(FS, n, averages=8)
    x = rng.standard_normal(n * 10 + d)
    y = 0.5 * np.concatenate([np.zeros(d), x[:-d]])
    found = transfer.find_delay(x[: 4 * n], y[: 4 * n], max_delay=FS)
    assert found == d
    for i in range(8):
        s = i * n + d
        res = tf.update(x[s - d: s - d + n], y[s: s + n])
    band = (res.freqs > 50) & (res.freqs < 15000)
    assert np.median(res.magnitude_db[band]) == pytest.approx(-6.02, abs=0.1)
    assert np.median(np.abs(res.phase_deg[band])) < 1.0
    assert np.median(res.coherence[band]) > 0.99


def test_fractional_smoothing_complex():
    f = np.linspace(0, 24000, 4097)
    v = np.ones_like(f) * (1 + 1j)
    out = spectrum.fractional_smooth(f, v, 3)
    assert np.allclose(out[10:], 1 + 1j)


# --- Impulsantwort -------------------------------------------------------------

def test_sweep_deconvolution_recovers_ir():
    x = impulse.exp_sweep(20, 20000, 2.0, FS)
    h_true = np.zeros(2000)
    h_true[100] = 1.0
    h_true[600] = -0.4
    y = signal.fftconvolve(x, h_true)
    h = impulse.deconvolve(y, x, FS)
    assert int(np.argmax(np.abs(h))) == 100
    assert h[600] / h[100] == pytest.approx(-0.4, abs=0.05)


# --- Raumakustik ---------------------------------------------------------------

@pytest.mark.parametrize("t60", [0.5, 1.2, 2.5])
def test_reverberation_time_with_noise(t60):
    h = synthetic_room_ir(t60, seconds=2 * t60 + 0.5)
    h = h + np.random.default_rng(5).standard_normal(len(h)) * 10 ** (-70 / 20)
    res = {r.label: r for r in room.analyze(h, FS)}
    b = res["Breitband"]
    assert b.t30 == pytest.approx(t60, rel=0.05)
    assert b.t20 == pytest.approx(t60, rel=0.05)
    a = 13.8155 / t60
    c80_theory = 10 * np.log10(np.exp(a * 0.08) - 1)
    assert b.c80 == pytest.approx(c80_theory, abs=0.5)


# --- STI -----------------------------------------------------------------------

def test_sti_matches_analytic_exponential_decay():
    t60 = 1.0
    h = synthetic_room_ir(t60, seconds=3.0)
    res = sti.sti_from_ir(h, FS, "STI")
    m_theory = [1 / np.sqrt(1 + (2 * np.pi * np.array(sti.MOD_FREQS) * t60 / 13.8) ** 2)] * 7
    expected, _ = sti.sti_from_mtf(m_theory)
    assert res.sti == pytest.approx(expected, abs=0.03)
    stipa = sti.sti_from_ir(h, FS, "STIPA")
    assert stipa.sti == pytest.approx(expected, abs=0.04)


def test_sti_dirac_is_one():
    h = np.zeros(FS)
    h[10] = 1
    assert sti.sti_from_ir(h, FS).sti > 0.98


# --- Schallpegel ---------------------------------------------------------------

def test_spl_meter_sine_1k():
    m = spl.SPLMeter(FS, cal_db=94.0)
    x = sine(1000, 8.0)  # Effektivwert 1 → 94 dB; 8 s, damit „S“ (τ = 1 s) eingeschwungen ist
    for blk in np.array_split(x, 160):
        cur = m.process(blk)
    assert cur["LAF"] == pytest.approx(94.0, abs=0.1)
    assert cur["LAS"] == pytest.approx(94.0, abs=0.2)
    assert cur["LZeq"] == pytest.approx(94.0, abs=0.1)
    assert cur["LZpeak"] == pytest.approx(97.0, abs=0.1)
    assert cur["LAI"] == pytest.approx(94.0, abs=0.5)


def test_spl_a_weighting_at_100hz():
    m = spl.SPLMeter(FS, cal_db=94.0)
    cur = m.process(sine(100, 3.0))
    assert cur["LAeq"] == pytest.approx(94.0 - 19.1, abs=0.3)


def test_calibration_offset():
    x = sine(1000, 1.0, amp=0.1)  # −23 dBFS
    off = spl.calibration_offset(x, 94.0)
    assert off == pytest.approx(94.0 + 23.01, abs=0.05)
