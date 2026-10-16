"""Workflow-Funktionen in der Oberfläche: Tastenkürzel, Zielkurve, Kurven-Rechnung,
Crossover-Ausrichtung, Sitzungen und Generator (Simulationsmodus, ohne Bildschirm)."""

import os

import numpy as np
import pytest
from PySide6 import QtCore, QtWidgets
from PySide6.QtTest import QTest

from akustik.dsp import tracemath
from akustik.dsp.generator import PeriodicPinkNoise
from conftest import make_window, wait


@pytest.fixture(scope="module")
def win(tmp_path_factory):
    app, w = make_window(tmp_path_factory.mktemp("wf"))
    w.activateWindow()
    wait(app, 1.0)
    w.realtime.find_delay()
    wait(app, 1.5)
    yield app, w
    w.close()


def press(app, w, key, mods=QtCore.Qt.NoModifier):
    w.realtime.p_mag.setFocus()  # kein Eingabefeld im Fokus
    QtWidgets.QApplication.setActiveWindow(w)
    QTest.keyClick(w.realtime.p_mag, key, mods)
    app.processEvents()


def test_periodic_noise_follows_fft_size(win):
    app, w = win
    eng = w.state.engine
    assert isinstance(eng.generator, PeriodicPinkNoise)
    assert w.realtime.cb_tf_fft.currentText().startswith("MTW")  # Standard
    assert eng.generator.length == 32768
    w.realtime.cb_tf_fft.setCurrentText("16384")
    assert eng.generator.length == 16384
    w.realtime.cb_tf_fft.setCurrentIndex(0)
    assert eng.generator.length == 32768


def test_shortcuts(win):
    app, w = win
    rt = w.realtime
    n = len(rt.traces.traces)
    press(app, w, QtCore.Qt.Key_S)
    assert len(rt.traces.traces) == n + 1 and rt.traces.traces[-1]["kind"] == "tf"
    assert rt.traces.traces[-1]["delay_ms"] == pytest.approx(8.0, abs=0.1)
    press(app, w, QtCore.Qt.Key_S, QtCore.Qt.ShiftModifier)
    assert rt.traces.traces[-1]["kind"] == "spec"
    press(app, w, QtCore.Qt.Key_P)
    assert rt.chk_peak.isChecked()
    press(app, w, QtCore.Qt.Key_P)
    press(app, w, QtCore.Qt.Key_G)          # Generator aus (blendet aus)
    assert not w.a_gen.isChecked()
    press(app, w, QtCore.Qt.Key_G)          # wieder an
    assert w.a_gen.isChecked() and w.state.engine.generator_active
    press(app, w, QtCore.Qt.Key_2)
    assert w.tabs.currentWidget() is w.impulse
    press(app, w, QtCore.Qt.Key_1)
    # in einem Zahlenfeld darf „S“ nicht als Kürzel wirken
    n = len(rt.traces.traces)
    rt.sp_coh.setFocus()
    QTest.keyClick(rt.sp_coh, QtCore.Qt.Key_S)
    assert len(rt.traces.traces) == n
    wait(app, 1.5)


def test_mute_is_immediate(win):
    app, w = win
    w.mute()
    wait(app, 0.2)
    assert w.state.engine.generator is None and not w.a_gen.isChecked()
    w.a_gen.setChecked(True)
    wait(app, 2.0)


def test_level_limit(win):
    app, w = win
    w.state.set_generator_settings(-20.0, 0.5)
    assert w.sp_gen_level.maximum() == -20.0 and w.sp_gen_level.value() <= -20.0
    assert w.impulse.sp_level.maximum() == -20.0
    assert w.state.engine.generator.level_db <= -20.0
    w.state.set_generator_settings(-6.0, 0.5)


def test_target_curve_with_auto_offset(win):
    app, w = win
    rt = w.realtime
    rt.cb_target.setCurrentText("Flach")
    rt._apply_target_choice()
    wait(app, 1.0)
    x, y = rt.c_target.getData()
    assert len(x) > 100
    f, mag = rt.last_tf[0], rt.last_tf[1]
    sel = (f > 200) & (f < 5000)
    assert rt.sp_target_off.value() == pytest.approx(np.median(mag[sel]), abs=0.5)
    rt.cb_target.setCurrentText("keine")
    rt._apply_target_choice()
    assert len(rt.c_target.getData()[0] or []) == 0


def test_difference_and_live_relative(win):
    app, w = win
    rt = w.realtime
    rt.capture_tf()
    wait(app, 0.5)
    rt.capture_tf()
    n = len(rt.traces.traces)
    rt.traces.list.clearSelection()
    rt.traces.list.item(n - 2).setSelected(True)
    rt.traces.list.item(n - 1).setSelected(True)
    rt.difference_selected()
    diff = rt.traces.traces[-1]
    sel = (diff["freqs"] > 200) & (diff["freqs"] < 5000)
    assert abs(np.median(diff["mag"][sel])) < 0.5   # gleiche Messung → ~0 dB
    rt.traces.list.clearSelection()
    rt.traces.list.item(n - 1).setSelected(True)
    rt.chk_relative.setChecked(True)
    wait(app, 1.0)
    f, mag = rt.last_tf[0], rt.last_tf[1]
    sel = (f > 200) & (f < 5000)
    assert abs(np.median(mag[sel])) < 0.5
    rt.chk_relative.setChecked(False)


def test_alignment_dialog_finds_crossover_setting(win):
    app, w = win
    rt = w.realtime
    f = np.geomspace(20, 20000, 3000)
    s = 1j * f / 100
    sub = 1 / (s**2 + np.sqrt(2) * s + 1)
    top = tracemath.shifted(f, s**2 / (s**2 + np.sqrt(2) * s + 1), 2.5)  # Top 2.5 ms zu spät
    for name, H, delay in (("Sub", sub, 0.0), ("Top", top, 1.0)):
        # „Top“ wurde mit 1 ms Laufzeit-Kompensation gemessen → gespeicherte Phase ohne diese 1 ms
        Hm = tracemath.shifted(f, H, -delay)
        rt.traces.add(name, {"kind": "tf", "freqs": f, "mag": 20 * np.log10(np.abs(Hm)),
                             "phase": np.degrees(np.angle(Hm)), "coh": np.ones_like(f), "delay_ms": delay})
    rt.traces.list.clearSelection()
    n = len(rt.traces.traces)
    rt.traces.list.item(n - 2).setSelected(True)
    rt.traces.list.item(n - 1).setSelected(True)
    rt.open_alignment()
    dlg = rt.align_dialog
    assert dlg.cb_a.currentText() == "Sub" and dlg.cb_b.currentText() == "Top"
    dlg.optimize()
    expected = tracemath.best_alignment(f, sub, top, 60, 160)
    assert dlg.sp_delay.value() == pytest.approx(expected.delay_ms, abs=0.02)
    assert dlg.chk_invert.isChecked() == expected.invert
    assert "Verlust" in dlg.lbl.text()
    dlg.save_sum()
    assert rt.traces.traces[-1]["name"].startswith("Summe Sub + Top")
    dlg.close()


def test_delete_multiple_traces(win):
    app, w = win
    store = w.realtime.traces
    for name in ("x1", "x2", "x3"):
        store.add(name, {"kind": "spec", "freqs": np.arange(1, 4.0), "mag": np.zeros(3), "stepped": False})
    n = len(store.traces)
    store.list.clearSelection()
    store.list.item(n - 3).setSelected(True)
    store.list.item(n - 1).setSelected(True)
    store.delete_selected()
    assert [t["name"] for t in store.traces[-1:]] == ["x2"]
    assert store.list.count() == len(store.traces) == n - 2
    store.list.clearSelection()
    store.list.item(store.list.count() - 1).setSelected(True)
    store.delete_selected()


def test_session_roundtrip_and_recovery(win, tmp_path, monkeypatch):
    app, w = win
    rt = w.realtime
    w.impulse.set_ir(np.exp(-np.arange(48000) / 4000.0) * np.random.default_rng(1).standard_normal(48000), 48000.0)
    w.spl._add_note_entry("Soundcheck Band")
    rt.cb_target.setCurrentText("X-Kurve (Kino, ISO 2969)")
    rt._apply_target_choice()
    rt.cb_smooth.setCurrentText("1/6 Okt.")
    n_traces = len(rt.traces.traces)
    path = str(tmp_path / "test.akmess")
    assert w.save_to(path)
    # alles verändern / leeren
    rt.set_state({}, {})
    rt.cb_smooth.setCurrentText("keine")
    w.impulse.set_state({}, {})
    w.spl.set_state({}, {})
    assert len(rt.traces.traces) == 0 and w.impulse.ir is None
    assert w.load_from(path)
    assert len(rt.traces.traces) == n_traces
    assert rt.traces.traces[0]["delay_ms"] is not None
    assert rt.cb_smooth.currentText() == "1/6 Okt."
    assert rt.target_points is not None
    assert w.impulse.ir is not None and len(w.impulse.results) > 0
    assert any(t == "Soundcheck Band" for _, t in w.spl.notes)
    assert w.windowTitle().startswith("test.akmess")
    # Absturz simulieren → Wiederherstellung aus der automatischen Sicherung
    w.autosave()
    assert os.path.exists(w.autosave_path)
    rt.set_state({}, {})
    w.state.settings.setValue("clean_exit", False)
    monkeypatch.setattr(QtWidgets.QMessageBox, "question",
                        staticmethod(lambda *a, **k: QtWidgets.QMessageBox.Yes))
    w._check_recovery()
    assert len(rt.traces.traces) == n_traces
