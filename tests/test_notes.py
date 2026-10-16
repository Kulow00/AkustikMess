import numpy as np
import pytest

from akustik.dsp import notes
from akustik.dsp.spectrum import make_window, peak_frequency, power_spectrum


@pytest.mark.parametrize("f,name,cents", [
    (440.0, "A4", 0), (261.6256, "C4", 0), (2553.0, "D♯7", 43.9), (493.8833, "H4", 0),
    (27.5, "A0", 0), (445.0, "A4", 19.6),
])
def test_note_of(f, name, cents):
    n, c = notes.note_of(f)
    assert n == name
    assert c == pytest.approx(cents, abs=0.5)


def test_international_naming_and_a4_reference():
    assert notes.note_of(493.88, naming="International (B)")[0] == "B4"
    assert notes.note_of(442.0, a4=442.0) == ("A4", pytest.approx(0, abs=1e-9))


def test_a4_from_measured_tone():
    # gemessenes E5 eines auf 443 Hz gestimmten Instruments
    e5 = notes.freq_from_midi(76, 443.0)
    assert notes.a4_from_measured(e5) == pytest.approx(443.0, abs=1e-6)


def test_format_freq_precision():
    assert notes.format_freq(2553.4) == "2553 Hz"
    assert notes.format_freq(63.456) == "63.46 Hz"


@pytest.mark.parametrize("f", [61.73, 440.0, 2553.27, 9876.5])
def test_peak_frequency_subbin_accuracy(f):
    fs, n = 48000, 65536
    t = np.arange(n) / fs
    p = power_spectrum(np.sin(2 * np.pi * f * t), make_window("Hann", n))
    est, _ = peak_frequency(np.fft.rfftfreq(n, 1 / fs), p)
    assert est == pytest.approx(f, abs=0.02)
