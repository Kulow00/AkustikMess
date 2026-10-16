"""Kammerton-Dialog: Bezugston A4 wählen, eingeben oder vom Eingang messen."""

from __future__ import annotations

import numpy as np
from PySide6 import QtCore, QtWidgets

from ..dsp.notes import NAMES, a4_from_measured, format_freq, note_of
from ..dsp.spectrum import make_window, peak_frequency, power_spectrum
from .common import channel_combo
from .state import AppState

PRESETS = [
    (440.0, "440 Hz – Standard (ISO 16)"),
    (442.0, "442 Hz – viele Orchester (DE/AT)"),
    (443.0, "443 Hz – Berliner/Wiener Orchester"),
    (441.0, "441 Hz"),
    (444.0, "444 Hz"),
    (432.0, "432 Hz"),
    (415.0, "415 Hz – Barock"),
    (466.0, "466 Hz – Chorton"),
]
MEASURE_SECONDS = 1.5
FFT_SIZE = 65536


class TuningDialog(QtWidgets.QDialog):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.setWindowTitle("Kammerton")
        self.setMinimumWidth(460)
        f = QtWidgets.QFormLayout(self)

        self.cb_preset = QtWidgets.QComboBox()
        self.cb_preset.addItem("– eigener Wert –", None)
        for hz, text in PRESETS:
            self.cb_preset.addItem(text, hz)
        self.sp_a4 = QtWidgets.QDoubleSpinBox(minimum=380.0, maximum=500.0, decimals=2,
                                              singleStep=0.1, suffix=" Hz", value=state.a4)
        self.cb_naming = QtWidgets.QComboBox()
        self.cb_naming.addItems(list(NAMES))
        self.cb_naming.setCurrentText(state.note_naming)
        f.addRow("Voreinstellung", self.cb_preset)
        f.addRow("Kammerton A4", self.sp_a4)
        f.addRow("Notennamen", self.cb_naming)
        self.cb_preset.currentIndexChanged.connect(self._preset)
        self.sp_a4.valueChanged.connect(self._sync_preset)
        self._sync_preset()

        g = QtWidgets.QGroupBox("Vom Eingang kalibrieren")
        gl = QtWidgets.QFormLayout(g)
        info = QtWidgets.QLabel("Referenzton (Stimmgabel, Stimmgerät, Instrument) am Mikrofon "
                                "spielen und „Ton messen“ drücken. Der Ton wird der nächsten Note "
                                "zugeordnet und der Kammerton so gesetzt, dass er genau stimmt.")
        info.setWordWrap(True)
        gl.addRow(info)
        self.cb_ch = channel_combo(state.input_channels, 0)
        gl.addRow("Eingang", self.cb_ch)
        self.btn_measure = QtWidgets.QPushButton("Ton messen")
        self.btn_measure.clicked.connect(self.measure)
        gl.addRow(self.btn_measure)
        self.lbl_result = QtWidgets.QLabel("")
        self.lbl_result.setWordWrap(True)
        self.lbl_result.setTextFormat(QtCore.Qt.RichText)
        gl.addRow(self.lbl_result)
        f.addRow(g)

        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def _preset(self) -> None:
        hz = self.cb_preset.currentData()
        if hz is not None:
            self.sp_a4.setValue(hz)

    def _sync_preset(self) -> None:
        idx = self.cb_preset.findData(round(self.sp_a4.value(), 2))
        self.cb_preset.blockSignals(True)
        self.cb_preset.setCurrentIndex(idx if idx >= 0 else 0)
        self.cb_preset.blockSignals(False)

    def measure(self) -> None:
        eng = self.state.engine
        if eng is None:
            self.lbl_result.setText("Audio ist nicht gestartet.")
            return
        ch = self.cb_ch.currentData() or 0
        x = eng.ring.latest(FFT_SIZE, ch).astype(float)
        if np.sqrt(np.mean(x**2)) < 1e-4:
            self.lbl_result.setText("Kein ausreichendes Signal am Eingang.")
            return
        freqs = np.fft.rfftfreq(FFT_SIZE, 1 / eng.fs)
        p = power_spectrum(x, make_window("Hann", FFT_SIZE))
        f0, pk = peak_frequency(freqs, p, 25.0, 5000.0)
        # Tonhaltigkeit prüfen: Spitze muss deutlich über dem Rest liegen
        if not np.isfinite(f0) or pk < 0.2 * p.sum():
            self.lbl_result.setText("Kein eindeutiger Ton erkannt – bitte einen gehaltenen, "
                                    "möglichst reinen Ton spielen.")
            return
        a4 = a4_from_measured(f0, self.sp_a4.value())
        name, cents = note_of(f0, self.sp_a4.value(), self.cb_naming.currentText())
        self.sp_a4.setValue(round(a4, 2))
        self.lbl_result.setText(
            f"Gemessen: <b>{format_freq(f0)}</b> = {name} ({cents:+.1f} ct bezogen auf den "
            f"bisherigen Kammerton)<br>→ Kammerton A4 = <b>{a4:.2f} Hz</b>")

    def _ok(self) -> None:
        self.state.set_tuning(self.sp_a4.value(), self.cb_naming.currentText())
        self.accept()
