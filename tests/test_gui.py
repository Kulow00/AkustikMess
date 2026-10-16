"""End-to-end-Test der Oberfläche im Simulationsmodus (ohne Bildschirm)."""

import os
import time

import numpy as np
import pytest
from PySide6 import QtCore, QtWidgets

from conftest import wait

SHOTS = os.environ.get("AKUSTIK_SCREENSHOTS")


def shot(win, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        win.grab().save(os.path.join(SHOTS, name))


def test_realtime_transfer_function(window):
    app, win = window
    rt = win.realtime
    wait(app, 1.0)
    rt.find_delay()
    assert rt.sp_delay.value() == pytest.approx(8.0, abs=0.1)
    # MTW (Standard): im Bass langes Fenster → hohe Kohärenz; im Hochton zählt der
    # Nachhall des simulierten Raums (≈ so laut wie der Direktschall) als unkorreliert
    wait(app, 3.0)
    f, mag, phase, coh = rt.last_tf
    assert len(f) < 1000
    assert np.median(coh[(f > 150) & (f < 400)]) > 0.6
    assert 0.35 < np.median(coh[(f > 4000) & (f < 12000)]) < 0.85
    assert np.isfinite(np.nanmedian(mag[(f > 200) & (f < 5000)]))
    shot(win, "1_echtzeit_mtw.png")
    # feste lange FFT: sieht den Nachhall als korreliert
    rt.cb_tf_fft.setCurrentText("32768")
    wait(app, 3.0)
    f, mag, phase, coh = rt.last_tf
    band = (f > 200) & (f < 5000)
    assert np.median(coh[band]) > 0.9
    rt.capture_tf()
    assert len(rt.traces.traces) == 1
    shot(win, "1_echtzeit.png")
    rt.cb_tf_fft.setCurrentIndex(0)


def test_hover_cursor_shows_exact_frequency_and_note(window):
    app, win = window
    rt = win.realtime
    win.state.set_tuning(440.0, "Deutsch (H)")
    cursor = rt.cursors[1]  # Betrag der Übertragungsfunktion
    vb = rt.p_mag.getPlotItem().getViewBox()
    scene_pos = vb.mapViewToScene(QtCore.QPointF(np.log10(2553.0), -10.0))
    rt.p_mag.scene().sigMouseMoved.emit(scene_pos)
    wait(app, 0.1)  # Mausbewegungen werden gebündelt (≤ 60/s)
    text = cursor.label.text()
    assert "2553 Hz" in text and "D♯7 +44 ct" in text and "Messwert" in text
    assert cursor.label.isVisible()
    assert rt.p_mag.rect().contains(cursor.label.geometry())  # vollständig im Plot
    # gekoppelte senkrechte Linie im Phasenplot
    assert rt.cursors[0].vline.isVisible()
    assert rt.cursors[0].vline.value() == pytest.approx(np.log10(2553.0), abs=1e-3)
    shot(win, "1b_cursor.png")
    # Maus steht still: Messwert wird trotzdem live aktualisiert
    original = cursor.value_fn
    cursor.value_fn = lambda f: "Messwert: LIVE"
    try:
        wait(app, 0.4)
        assert "LIVE" in cursor.label.text() and "2553 Hz" in cursor.label.text()
        assert cursor._live.isActive()
        QtWidgets.QApplication.sendEvent(rt.p_mag, QtCore.QEvent(QtCore.QEvent.Leave))
        assert not cursor._live.isActive() and not cursor.label.isVisible()
    finally:
        cursor.value_fn = original


def test_spectrum_peak_and_tuning_from_input(window):
    app, win = window
    from akustik.dsp.notes import freq_from_midi
    from akustik.gui.tuning_dialog import TuningDialog
    e5_at_443 = freq_from_midi(76, 443.0)  # 663.75 Hz
    win.cb_gen.setCurrentText("Sinus")
    win.sp_gen_freq.setValue(round(e5_at_443, 2))
    win.update_generator(True)
    wait(app, 2.0)
    title = win.realtime.p_spec.plotItem.titleLabel.text
    assert "663.7 Hz" in title or "663.8 Hz" in title, title
    assert "E5 +12 ct" in title  # bezogen auf A4 = 440 Hz
    dlg = TuningDialog(win.state, win)
    dlg.cb_ch.setCurrentIndex(dlg.cb_ch.findData(1))  # Loopback-Eingang
    dlg.measure()
    assert dlg.sp_a4.value() == pytest.approx(443.0, abs=0.02), dlg.lbl_result.text()
    dlg._ok()
    assert win.state.a4 == pytest.approx(443.0, abs=0.02)
    assert "443" in win.a_tuning.text()
    win.state.set_tuning(440.0, "Deutsch (H)")
    win.cb_gen.setCurrentText("Rosa Rauschen")
    win.update_generator(True)
    wait(app, 1.0)


def test_impulse_measurement(window):
    app, win = window
    win.tabs.setCurrentWidget(win.impulse)
    iv = win.impulse
    iv.cb_len.setCurrentIndex(iv.cb_len.findData(1))
    iv.sp_tail.setValue(1.8)
    iv.measure()
    end = time.monotonic() + 15
    while iv.ir is None and time.monotonic() < end:
        wait(app, 0.1)
    assert iv.ir is not None, iv.status.text()
    res = {r.label: r for r in iv.results}
    assert 0.8 < res["1k"].t30 < 1.2
    assert "STI" in iv.lbl_sti.text()
    shot(win, "2_impulsantwort.png")
    iv.cb_view.setCurrentText("Spektrogramm")
    shot(win, "2b_spektrogramm.png")


def test_spl_meter(window):
    app, win = window
    win.tabs.setCurrentWidget(win.spl)
    win.spl.reset()
    wait(app, 2.5)
    v = win.spl.values
    assert np.isfinite(v["LAF"]) and np.isfinite(v["LAeq 1 s"])
    assert 60 < v["LAeq"] < 120   # rosa Rauschen −18 dBFS bei Kalibrierung 120 dB
    assert len(win.spl.hist["t"]) >= 1
    win.spl.ed_note.setText("Test-Notiz")
    win.spl.add_note()
    shot(win, "3_spl.png")
