"""Crossover-/Sub-Ausrichtung: zwei gespeicherte Übertragungsfunktionen virtuell summieren.

Laufzeit, Polarität und Pegel von B lassen sich verschieben; die Summe wird
sofort berechnet. „Optimum finden“ sucht die Einstellung mit maximaler Summe
im markierten Übergangsbereich.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

from ..dsp import tracemath
from .common import CursorGroup, FreqCursor, TraceStore, curve_value, freq_plot, log_decimate
from .state import AppState


def trace_complex(t: dict) -> tuple[np.ndarray, np.ndarray]:
    """Gespeicherte Kurve → komplexe Übertragungsfunktion inkl. der beim Messen
    kompensierten Laufzeit (sonst würden Kurven mit unterschiedlicher
    Laufzeit-Kompensation falsch summiert)."""
    f = np.asarray(t["freqs"])
    H = tracemath.to_complex(t["mag"], t["phase"])
    return f, tracemath.shifted(f, H, t.get("delay_ms", 0.0))


class AlignDialog(QtWidgets.QDialog):
    def __init__(self, state: AppState, traces: TraceStore, parent=None):
        super().__init__(parent)
        self.state, self.traces = state, traces
        self.setWindowTitle("Crossover-Ausrichtung (virtuelle Summe)")
        self.resize(1200, 760)
        self.sum = None
        lay = QtWidgets.QHBoxLayout(self)

        plots = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self.p_phase = freq_plot("Phase", "Phase [°]", (-180, 180), y_grid=90, y_span=(-180, 180))
        self.p_mag = freq_plot("Betrag", "dB", (-30, 15), y_grid=6)
        self.p_phase.setXLink(self.p_mag)
        plots.addWidget(self.p_phase)
        plots.addWidget(self.p_mag)
        plots.setSizes([260, 440])
        lay.addWidget(plots, 1)
        self.c = {
            "a": (self.p_mag.plot(pen=pg.mkPen("#ff5555", width=1.5)),
                  self.p_phase.plot(pen=pg.mkPen("#ff5555", width=1.5))),
            "b": (self.p_mag.plot(pen=pg.mkPen("#55aaff", width=1.5)),
                  self.p_phase.plot(pen=pg.mkPen("#55aaff", width=1.5))),
        }
        self.c_sum = self.p_mag.plot(pen=pg.mkPen("#ffffff", width=2.5))
        self.region = pg.LinearRegionItem(values=(np.log10(60), np.log10(160)),
                                          brush=(255, 204, 51, 35))
        self.region.setZValue(-50)
        self.p_mag.addItem(self.region)
        self.region.sigRegionChangeFinished.connect(self._region_moved)

        group = CursorGroup()
        FreqCursor(self.p_phase, state, unit="°", group=group)
        FreqCursor(self.p_mag, state, unit="dB", value_fn=self._sum_value, group=group)

        panel = QtWidgets.QWidget()
        panel.setFixedWidth(300)
        f = QtWidgets.QFormLayout(panel)
        info = QtWidgets.QLabel("Zwei gespeicherte Übertragungsfunktionen wählen, z. B. "
                                "<span style='color:#ff5555'>A = Sub</span> und "
                                "<span style='color:#55aaff'>B = Top</span>, jeweils einzeln "
                                "gemessen. <b>Weiß</b> = berechnete Summe.")
        info.setWordWrap(True)
        f.addRow(info)
        self.cb_a = QtWidgets.QComboBox()
        self.cb_b = QtWidgets.QComboBox()
        f.addRow("Kurve A", self.cb_a)
        f.addRow("Kurve B", self.cb_b)
        g = QtWidgets.QGroupBox("Kurve B anpassen")
        gf = QtWidgets.QFormLayout(g)
        self.sp_delay = QtWidgets.QDoubleSpinBox(minimum=-50, maximum=50, decimals=2, singleStep=0.05,
                                                 suffix=" ms")
        self.sl_delay = QtWidgets.QSlider(QtCore.Qt.Horizontal, minimum=-2000, maximum=2000)
        self.chk_invert = QtWidgets.QCheckBox("Polarität umkehren")
        self.sp_gain = QtWidgets.QDoubleSpinBox(minimum=-24, maximum=24, decimals=1, singleStep=0.5,
                                                suffix=" dB")
        gf.addRow("Laufzeit", self.sp_delay)
        gf.addRow(self.sl_delay)
        gf.addRow(self.chk_invert)
        gf.addRow("Pegel", self.sp_gain)
        f.addRow(g)
        g2 = QtWidgets.QGroupBox("Übergangsbereich")
        gf2 = QtWidgets.QFormLayout(g2)
        self.sp_lo = QtWidgets.QDoubleSpinBox(minimum=10, maximum=20000, value=60, suffix=" Hz")
        self.sp_hi = QtWidgets.QDoubleSpinBox(minimum=10, maximum=20000, value=160, suffix=" Hz")
        gf2.addRow("von", self.sp_lo)
        gf2.addRow("bis", self.sp_hi)
        self.sp_max = QtWidgets.QDoubleSpinBox(minimum=1, maximum=50, value=20, suffix=" ms")
        gf2.addRow("Suchbereich ±", self.sp_max)
        b_opt = QtWidgets.QPushButton("Optimum finden")
        b_opt.setStyleSheet("font-weight: bold; padding: 5px;")
        b_opt.clicked.connect(self.optimize)
        gf2.addRow(b_opt)
        f.addRow(g2)
        self.lbl = QtWidgets.QLabel("")
        self.lbl.setWordWrap(True)
        self.lbl.setTextFormat(QtCore.Qt.RichText)
        f.addRow(self.lbl)
        b_save = QtWidgets.QPushButton("Summe als Kurve speichern")
        b_save.clicked.connect(self.save_sum)
        f.addRow(b_save)
        lay.addWidget(panel)

        self._fill_traces()
        for w in (self.cb_a, self.cb_b):
            w.currentIndexChanged.connect(self.recompute)
        self.sp_delay.valueChanged.connect(self._delay_spin)
        self.sl_delay.valueChanged.connect(lambda v: self.sp_delay.setValue(v / 100))
        self.chk_invert.toggled.connect(self.recompute)
        self.sp_gain.valueChanged.connect(self.recompute)
        for w in (self.sp_lo, self.sp_hi):
            w.valueChanged.connect(self._range_spin)
        self.recompute()

    def _fill_traces(self) -> None:
        tfs = self.traces.of_kind("tf")
        sel = self.traces.selected("tf")
        for cb in (self.cb_a, self.cb_b):
            cb.clear()
            for t in tfs:
                cb.addItem(t["name"], id(t))
        if len(sel) >= 2:  # Zuordnung über Identität (Kurven enthalten Arrays)
            self.cb_a.setCurrentIndex(self.cb_a.findData(id(sel[0])))
            self.cb_b.setCurrentIndex(self.cb_b.findData(id(sel[1])))
        elif len(tfs) >= 2:
            self.cb_b.setCurrentIndex(1)
        if len(tfs) < 2:
            self.lbl.setText("Es werden mindestens <b>zwei gespeicherte Übertragungsfunktionen</b> "
                             "benötigt (z. B. Sub allein und Top allein messen und jeweils speichern).")

    def _trace(self, cb) -> dict | None:
        key = cb.currentData()
        return next((t for t in self.traces.of_kind("tf") if id(t) == key), None)

    def _delay_spin(self, v: float) -> None:
        self.sl_delay.blockSignals(True)
        self.sl_delay.setValue(int(round(v * 100)))
        self.sl_delay.blockSignals(False)
        self.recompute()

    def _range_spin(self) -> None:
        self.region.blockSignals(True)
        self.region.setRegion((np.log10(self.sp_lo.value()), np.log10(self.sp_hi.value())))
        self.region.blockSignals(False)
        self.recompute()

    def _region_moved(self) -> None:
        lo, hi = self.region.getRegion()
        for sp, v in ((self.sp_lo, lo), (self.sp_hi, hi)):
            sp.blockSignals(True)
            sp.setValue(round(10 ** v, 1))
            sp.blockSignals(False)
        self.recompute()

    def _data(self):
        ta, tb = self._trace(self.cb_a), self._trace(self.cb_b)
        if ta is None or tb is None:
            return None
        fa, Ha = trace_complex(ta)
        fb, Hb = trace_complex(tb)
        if not tracemath.same_grid(fa, fb):
            Hb = tracemath.resample(fb, Hb, fa)
        return fa, Ha, Hb

    def recompute(self) -> None:
        d = self._data()
        if d is None:
            return
        f, Ha, Hb = d
        Hb2 = tracemath.shifted(f, Hb, self.sp_delay.value(), self.chk_invert.isChecked(),
                                self.sp_gain.value())
        S = Ha + Hb2
        db = lambda H: 20 * np.log10(np.abs(H) + 1e-30)  # noqa: E731
        self.sum = (f, db(S), np.degrees(np.angle(S)))
        for key, H in (("a", Ha), ("b", Hb2)):
            fd, dd = log_decimate(f, m=("mean", db(H)), p=("phase", np.degrees(np.angle(H))))
            self.c[key][0].setData(fd, dd["m"])
            self.c[key][1].setData(fd, dd["p"])
        fd, dd = log_decimate(f, m=("mean", db(S)))
        self.c_sum.setData(fd, dd["m"])
        sel = (f >= self.sp_lo.value()) & (f <= self.sp_hi.value())
        if np.any(sel):
            gain = 10 * np.log10(np.mean(np.abs(S[sel]) ** 2) /
                                 max(np.mean(np.abs(Ha[sel]) ** 2), np.mean(np.abs(Hb2[sel]) ** 2)))
            ideal = 10 * np.log10(np.mean((np.abs(Ha[sel]) + np.abs(Hb2[sel])) ** 2) /
                                  np.mean(np.abs(S[sel]) ** 2))
            dphi = np.degrees(np.angle(np.mean(Hb2[sel] * np.conj(Ha[sel]))))
            color = "#66dd66" if ideal < 1 else "#ffcc33" if ideal < 3 else "#ff5555"
            self.lbl.setText(
                f"Im Übergangsbereich:<br>Summe <b>{gain:+.1f} dB</b> gegenüber der lauteren Einzelkurve<br>"
                f"Verlust zur idealen Summe: <b style='color:{color}'>{ideal:.1f} dB</b><br>"
                f"Mittlere Phasendifferenz B−A: {dphi:+.0f}°")

    def optimize(self) -> None:
        d = self._data()
        if d is None:
            return
        f, Ha, Hb = d
        res = tracemath.best_alignment(f, Ha, Hb, self.sp_lo.value(), self.sp_hi.value(),
                                       self.sp_max.value(), 0.01, self.sp_gain.value())
        self.chk_invert.blockSignals(True)
        self.chk_invert.setChecked(res.invert)
        self.chk_invert.blockSignals(False)
        self.sp_delay.setValue(res.delay_ms)
        self.recompute()
        self.lbl.setText(self.lbl.text() + f"<br><br><b>Vorschlag:</b> B um {res.delay_ms:+.2f} ms "
                         f"verschieben{', Polarität umkehren' if res.invert else ''}.<br>"
                         "<span style='color:#999'>Positiv = B später. Bei negativem Wert "
                         "stattdessen A um den Betrag verzögern.</span>")

    def _sum_value(self, f):
        if self.sum is None:
            return None
        v = curve_value(self.sum[0], self.sum[1], f)
        return None if v is None else f"Summe: {v:.1f} dB"

    def save_sum(self) -> None:
        if self.sum is None:
            return
        f, mag, ph = self.sum
        ta, tb = self._trace(self.cb_a), self._trace(self.cb_b)
        coh = np.minimum(ta["coh"], tracemath.resample(np.asarray(tb["freqs"]), np.asarray(tb["coh"]), f)
                         if not tracemath.same_grid(ta["freqs"], tb["freqs"]) else tb["coh"])
        name = (f"Summe {ta['name']} + {tb['name']} ({self.sp_delay.value():+.2f} ms"
                f"{', invertiert' if self.chk_invert.isChecked() else ''})")
        self.traces.add(name, {"kind": "tf", "freqs": f, "mag": mag, "phase": ph, "coh": coh,
                               "delay_ms": 0.0})
