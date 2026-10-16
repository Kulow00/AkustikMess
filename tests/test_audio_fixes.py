"""Generator-Ausgabe (macOS: getrennte Geräte), Darstellungsbereich, Kohärenz-Ausblendung ohne Aussetzer."""

import sys
import types

import numpy as np
import pytest
from PySide6 import QtWidgets

from akustik.audio.engine import AudioConfig, AudioEngine
from akustik.dsp.generator import WhiteNoise
from conftest import make_window, wait

DEVICES = [
    {"name": "MacBook Pro Mikrofon", "hostapi": 0, "max_input_channels": 1, "max_output_channels": 0,
     "default_samplerate": 48000.0},
    {"name": "MacBook Pro Lautsprecher", "hostapi": 0, "max_input_channels": 0, "max_output_channels": 2,
     "default_samplerate": 48000.0},
    {"name": "Interface 2i2", "hostapi": 0, "max_input_channels": 2, "max_output_channels": 2,
     "default_samplerate": 48000.0},
]


class _FakeStream:
    def __init__(self, kind, **kw):
        self.kind, self.kw, self.started, self.closed = kind, kw, False, False

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def close(self):
        self.closed = True


@pytest.fixture
def fake_sd(monkeypatch):
    created = []
    sd = types.ModuleType("sounddevice")
    sd.query_hostapis = lambda: [{"name": "Core Audio"}]

    def query_devices(device=None, kind=None):
        if kind == "output":
            return DEVICES[1]
        return DEVICES

    sd.query_devices = query_devices
    for kind in ("Stream", "InputStream", "OutputStream"):
        setattr(sd, kind, lambda kind=kind, **kw: created.append(_FakeStream(kind, **kw)) or created[-1])
    monkeypatch.setitem(sys.modules, "sounddevice", sd)
    return created


def test_separate_devices_use_separate_streams(fake_sd):
    eng = AudioEngine(AudioConfig(input_device="MacBook Pro Mikrofon", output_device="MacBook Pro Lautsprecher",
                                  host_api="Core Audio", input_channels=1, output_channels=2))
    eng.start()
    assert [s.kind for s in fake_sd] == ["InputStream", "OutputStream"] and not eng.duplex
    assert all(s.started for s in fake_sd)
    # Ausgabe-Callback spielt den Generator, auch ohne Eingangsdaten im selben Stream
    eng.fade_s = 0.001
    eng.set_generator(WhiteNoise(eng.fs, -6.0), [1])
    out = np.zeros((1024, 2), np.float32)
    status = types.SimpleNamespace(output_underflow=True, __bool__=lambda self: True)
    for _ in range(3):
        fake_sd[1].kw["callback"](out, 1024, None, None)
    assert np.abs(out[:, 1]).max() > 0.01 and np.abs(out[:, 0]).max() == 0
    eng._count(types.SimpleNamespace(output_underflow=True))
    assert eng.output_underruns == 1
    eng.stop()
    assert all(s.closed for s in fake_sd)


def test_same_device_uses_duplex(fake_sd):
    eng = AudioEngine(AudioConfig(input_device="Interface 2i2", output_device="Interface 2i2",
                                  host_api="Core Audio"))
    eng.start()
    assert [s.kind for s in fake_sd] == ["Stream"] and eng.duplex
    eng.stop()


def test_dialog_never_silently_without_output(fake_sd, monkeypatch):
    from akustik.gui import audio_dialog
    devs = [{"name": d["name"], "hostapi": "Core Audio", "inputs": d["max_input_channels"],
             "outputs": d["max_output_channels"], "samplerate": 48000.0} for d in DEVICES]
    monkeypatch.setattr(audio_dialog, "list_devices", lambda: (["Core Audio"], devs))
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    # früher gespeichert: nur Eingang → Vorschlag: System-Standardausgang
    dlg = audio_dialog.AudioDialog(AudioConfig(input_device="MacBook Pro Mikrofon", output_device=None,
                                               host_api="Core Audio"))
    assert dlg.result_config().output_device == "MacBook Pro Lautsprecher"
    # Interface mit Ein- und Ausgang → derselbe Ausgang
    dlg = audio_dialog.AudioDialog(AudioConfig(input_device="Interface 2i2", output_device="gibt es nicht",
                                               host_api="Core Audio"))
    assert dlg.result_config().output_device == "Interface 2i2"


def test_generator_starts_audio_and_warns_without_output(tmp_path, monkeypatch):
    app, w = make_window(tmp_path, start=False)
    try:
        assert w.state.engine is None
        w.a_gen.setChecked(True)                    # Generator ohne laufendes Audio
        wait(app, 0.3)
        assert w.state.engine is not None and w.state.engine.generator_active
        warned = []
        monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda *a, **k: warned.append(a))
        monkeypatch.setattr(type(w.state.engine), "has_output", property(lambda self: False))
        w.a_gen.setChecked(False)
        w.a_gen.setChecked(True)
        assert warned and not w.a_gen.isChecked()
    finally:
        w.close()


def test_view_range_sidebar_and_zoom_limit(tmp_path):
    app, w = make_window(tmp_path, start=False)
    rt = w.realtime
    try:
        rt.sp_view_f_lo.setValue(100)
        rt.sp_view_f_hi.setValue(5000)
        rt.sp_view_spec_bot.setValue(-90)
        rt.sp_view_spec_top.setValue(-10)
        (x0, x1), (y0, y1) = rt.p_spec.getPlotItem().getViewBox().viewRange()
        assert 10 ** x0 == pytest.approx(100, rel=0.01) and 10 ** x1 == pytest.approx(5000, rel=0.01)
        assert (y0, y1) == pytest.approx((-90, -10), abs=0.01)
        # Zoom mit der Maus → Felder folgen
        rt.p_spec.setYRange(-60, -20, padding=0)
        wait(app, 0.05)
        assert rt.sp_view_spec_bot.value() == pytest.approx(-60, abs=1)
        # nicht tiefer als −150 dB
        rt.p_spec.setYRange(-400, 0, padding=0)
        wait(app, 0.05)
        assert rt.p_spec.getPlotItem().getViewBox().viewRange()[1][0] >= -150.01
        assert rt.sp_view_spec_bot.minimum() == -150
        rt.reset_view_range()
        assert rt.sp_view_f_lo.value() == 20 and rt.sp_view_spec_bot.value() == -120
    finally:
        w.close()


def test_blanking_keeps_curve_continuous(tmp_path):
    app, w = make_window(tmp_path, start=False)
    rt = w.realtime
    try:
        f = np.geomspace(20, 20000, 1500)
        coh = np.full_like(f, 0.6)
        rng = np.random.default_rng(1)
        coh[rng.choice(len(f), 150, replace=False)] = 0.05     # einzelne Ausreißer → keine Lücken
        coh[(f > 3000) & (f < 6000)] = 0.02                    # wirklich unbrauchbarer Bereich
        rt._coh_hist = None
        bad = rt._blank_mask(f, coh, 0.2)
        assert not bad[f < 2500].any()
        assert bad[(f > 3300) & (f < 5500)].all()
    finally:
        w.close()


def test_calibrated_spectrum_keeps_full_range(tmp_path):
    app, w = make_window(tmp_path, start=True)
    rt = w.realtime
    try:
        wait(app, 0.3)
        cal = w.state.calibration_for(rt.cb_spec_ch.currentData() or 0)
        off = cal if cal is not None else 0.0
        _, (y0, y1) = rt.p_spec.getPlotItem().getViewBox().viewRange()
        assert (y0, y1) == pytest.approx((off - 120, off), abs=0.01)
        assert rt.sp_view_spec_bot.minimum() == pytest.approx(off - 150)
    finally:
        w.close()
