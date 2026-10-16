"""Zeitbudget der Echtzeit-Darstellung (Rechnen + Zeichnen) im Simulationsmodus."""

import os
import time

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from akustik.gui.common import log_decimate  # noqa: E402


def test_log_decimate_keeps_low_bins_and_peaks():
    f = np.fft.rfftfreq(32768, 1 / 48000)[1:]
    y = np.zeros_like(f)
    y[np.argmin(abs(f - 10000))] = 50.0          # schmale Spitze oben
    fd, d = log_decimate(f, y=("max", y), p=("phase", np.full_like(f, 179.0)))
    assert len(fd) < 1600
    assert np.array_equal(fd[:20], f[:20])       # Tiefen: jeder Bin bleibt erhalten
    assert d["y"].max() == 50.0                  # Spitze geht nicht verloren
    assert np.allclose(d["p"], 179.0)            # Kreismittel, kein Umklappen bei ±180°


def test_realtime_frame_budget(tmp_path):
    from conftest import make_window
    app, win = make_window(tmp_path)
    rt = win.realtime
    rt.timer.stop()  # Takt selbst steuern und messen
    for _ in range(5):
        rt.update_plots()
    plots = rt.p_mag.parentWidget()  # Bereich, der sich je Bild tatsächlich ändert
    times = []
    for _ in range(20):
        t0 = time.perf_counter()
        rt.update_plots()
        plots.grab()  # erzwingt komplettes Neuzeichnen aller Diagramme
        times.append(time.perf_counter() - t0)
    win.close()
    med = 1000 * float(np.median(times))
    print(f"Median pro Bild (rechnen + zeichnen): {med:.1f} ms")
    # muss mit Reserve in den 50-ms-Takt passen; geteilte CI-Rechner ohne Grafikkarte sind langsamer
    limit = 120 if os.environ.get("CI") else 35
    assert med < limit, med
