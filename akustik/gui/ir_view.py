"""Impulsantwort-Modus: Sweep-Messung, Zeitbereichsansichten, Raumakustik, STI."""

from __future__ import annotations

import threading
import time

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets
from .._lazy import signal
from .._lazy import wavfile

from ..dsp import impulse, room, sti
from ..dsp.octave import band_filter_sos
from .common import (FreqAxis, FreqCursor, channel_combo, combo, curve_value, freq_plot,
                     set_channel_count, time_plot)
from .session import apply_controls_state, controls_state, name_controls
from .state import AppState

VIEWS = ["Linear", "Logarithmisch", "ETC (Energie-Zeit-Kurve)", "Schroeder-Abklingkurve",
         "Spektrogramm", "Frequenzgang"]


class MeasureWorker(QtCore.QThread):
    finished_ok = QtCore.Signal(object, float, str)   # ir, fs, info
    failed = QtCore.Signal(str)
    progress = QtCore.Signal(str)

    def __init__(self, engine, params: dict):
        super().__init__()
        self.engine = engine
        self.p = params
        self.cancel = threading.Event()

    def run(self) -> None:
        p, eng = self.p, self.engine
        try:
            fs = eng.fs
            sweep = impulse.exp_sweep(p["f1"], min(p["f2"], fs / 2 * 0.95), p["duration"], fs)
            sweep *= 10 ** (p["level"] / 20)
            acc = None
            peak = 0.0
            for i in range(p["averages"]):
                self.progress.emit(f"Sweep {i + 1}/{p['averages']} läuft …")
                rec = eng.play_and_record(sweep, [p["out"]], tail_s=p["tail"], cancel=self.cancel).astype(float)
                meas = rec[:, p["meas"]]
                peak = max(peak, float(np.abs(meas).max()))
                if p["ref"] >= 0:
                    ref = rec[:, p["ref"]]
                    if np.abs(ref).max() < 1e-4:
                        raise RuntimeError("Referenzkanal ist stumm – Loopback-Kabel prüfen "
                                           "oder Referenz auf „keiner“ stellen.")
                else:
                    ref = np.concatenate([sweep, np.zeros(len(rec) - len(sweep))])
                h = impulse.deconvolve(meas, ref, fs, p["f1"], p["f2"])
                acc = h if acc is None else acc + h
            h = acc / p["averages"]
            h = h[: int((p["tail"] + 0.1) * fs)]
            info = f"Spitzenpegel Aufnahme: {20 * np.log10(peak + 1e-12):.1f} dBFS"
            if peak > 0.98:
                info += " – ÜBERSTEUERT, Pegel reduzieren!"
            elif peak < 0.01:
                info += " – sehr leise, Pegel erhöhen."
            self.finished_ok.emit(h, float(fs), info)
        except InterruptedError:
            self.failed.emit("Messung abgebrochen.")
        except Exception as exc:  # noqa: BLE001 – Fehler an die Oberfläche melden
            self.failed.emit(str(exc))


class ImpulseView(QtWidgets.QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.ir: np.ndarray | None = None
        self.fs = 48000.0
        self.results: list[room.BandResult] = []
        self.worker: MeasureWorker | None = None
        self._build()
        name_controls(self)
        state.engine_changed.connect(self._engine_changed)
        state.generator_settings_changed.connect(self._apply_level_limit)
        self._apply_level_limit()

    def _apply_level_limit(self) -> None:
        """Sweep-Pegel nie über die eingestellte Pegelgrenze (Lautsprecherschutz)."""
        self.sp_level.setMaximum(self.state.level_limit_db)

    # --- Sitzung ---------------------------------------------------------------
    def get_state(self) -> tuple[dict, dict]:
        arrays = {} if self.ir is None else {"ir": self.ir}
        return {"controls": controls_state(self), "fs": self.fs}, arrays

    def set_state(self, meta: dict, arrays: dict) -> None:
        apply_controls_state(self, meta.get("controls", {}))
        if "ir" in arrays:
            self.set_ir(arrays["ir"], float(meta.get("fs", 48000.0)))
        else:
            self.ir, self.results = None, []
            self.table.clear()
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            self.p_time.clear()
            self.lbl_sti.setText("STI: –    STIPA: –")

    # --- Aufbau --------------------------------------------------------------
    def _build(self) -> None:
        lay = QtWidgets.QHBoxLayout(self)
        left = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self.stack = QtWidgets.QStackedWidget()
        self.p_time = time_plot("", "Amplitude")
        # nur sichtbaren Ausschnitt zeichnen, Spitzen beim Ausdünnen erhalten
        self.p_time.setDownsampling(auto=True, mode="peak")
        self.p_time.setClipToView(True)
        self.p_freq = freq_plot("Frequenzgang", "dB", (-60, 10))
        self.p_spectro = pg.PlotWidget(axisItems={"left": FreqAxis(orientation="left")})
        self.p_spectro.getAxis("left").logMode = True
        self.p_spectro.setLabel("bottom", "Zeit [s]")
        self.img = pg.ImageItem()
        self.img.setColorMap(pg.colormap.get("inferno"))
        self.p_spectro.addItem(self.img)
        for w in (self.p_time, self.p_freq, self.p_spectro):
            self.stack.addWidget(w)
        self.c_freq = self.p_freq.plot(pen=pg.mkPen("#55aaff", width=1.5))
        self.freq_resp = None  # (f, mag) für die Cursor-Anzeige

        def freq_value(f):
            if self.freq_resp is None:
                return None
            v = curve_value(*self.freq_resp, f)
            return None if v is None else f"Messwert: {v:.1f} dB"

        FreqCursor(self.p_freq, self.state, unit="dB", value_fn=freq_value)
        FreqCursor(self.p_spectro, self.state, freq_axis="y", unit="s")
        left.addWidget(self.stack)

        self.table = QtWidgets.QTableWidget()
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(22)
        res_box = QtWidgets.QWidget()
        rl = QtWidgets.QVBoxLayout(res_box)
        rl.setContentsMargins(0, 0, 0, 0)
        self.lbl_sti = QtWidgets.QLabel("STI: –    STIPA: –")
        self.lbl_sti.setStyleSheet("font-size: 15px; font-weight: bold; padding: 4px;")
        rl.addWidget(self.lbl_sti)
        rl.addWidget(self.table)
        left.addWidget(res_box)
        left.setSizes([500, 260])
        lay.addWidget(left, 1)

        panel = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(panel)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        scroll.setFixedWidth(300)
        lay.addWidget(scroll)

        g = QtWidgets.QGroupBox("Messung (Sinus-Sweep)")
        f = QtWidgets.QFormLayout(g)
        self.cb_out = channel_combo(2, 0)
        self.cb_meas = channel_combo(2, 0)
        self.cb_ref = channel_combo(2, 1, allow_none=True)
        self.cb_len = combo([1, 2, 3, 5, 10], 3)
        self.sp_f1 = QtWidgets.QDoubleSpinBox(minimum=10, maximum=1000, value=20, suffix=" Hz")
        self.sp_f2 = QtWidgets.QDoubleSpinBox(minimum=1000, maximum=96000, value=20000, suffix=" Hz")
        self.sp_level = QtWidgets.QDoubleSpinBox(minimum=-60, maximum=0, value=-12, suffix=" dBFS")
        self.sp_avg = QtWidgets.QSpinBox(minimum=1, maximum=16, value=1)
        self.sp_tail = QtWidgets.QDoubleSpinBox(minimum=0.5, maximum=15, value=3.0, suffix=" s")
        f.addRow("Ausgang", self.cb_out)
        f.addRow("Messkanal", self.cb_meas)
        f.addRow("Referenz (Loopback)", self.cb_ref)
        f.addRow("Sweep-Länge [s]", self.cb_len)
        f.addRow("Startfrequenz", self.sp_f1)
        f.addRow("Endfrequenz", self.sp_f2)
        f.addRow("Pegel", self.sp_level)
        f.addRow("Mittelungen", self.sp_avg)
        f.addRow("IR-Länge", self.sp_tail)
        self.btn_measure = QtWidgets.QPushButton("Messen")
        self.btn_measure.setStyleSheet("font-weight: bold; padding: 6px;")
        self.btn_measure.clicked.connect(self.measure)
        self.btn_cancel = QtWidgets.QPushButton("Abbrechen")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel)
        f.addRow(self.btn_measure)
        f.addRow(self.btn_cancel)
        pl.addWidget(g)

        g = QtWidgets.QGroupBox("Ansicht")
        f = QtWidgets.QFormLayout(g)
        self.cb_view = combo(VIEWS, "Logarithmisch")
        self.cb_band = combo(["Breitband", 63, 125, 250, 500, 1000, 2000, 4000, 8000], "Breitband")
        f.addRow("Darstellung", self.cb_view)
        f.addRow("Oktavband", self.cb_band)
        self.cb_view.currentIndexChanged.connect(self.redraw)
        self.cb_band.currentIndexChanged.connect(self.redraw)
        pl.addWidget(g)

        g = QtWidgets.QGroupBox("Datei")
        v = QtWidgets.QVBoxLayout(g)
        b_load = QtWidgets.QPushButton("IR laden (WAV)…")
        b_save = QtWidgets.QPushButton("IR speichern (WAV)…")
        b_csv = QtWidgets.QPushButton("Kennwerte exportieren (CSV)…")
        b_load.clicked.connect(self.load_wav)
        b_save.clicked.connect(self.save_wav)
        b_csv.clicked.connect(self.export_csv)
        for b in (b_load, b_save, b_csv):
            v.addWidget(b)
        pl.addWidget(g)

        self.status = QtWidgets.QLabel("Bereit. Lautsprecher an den Ausgang, Messmikrofon an den "
                                       "Messkanal. Optional: Ausgang per Kabel zurück auf den "
                                       "Referenzeingang (Loopback) für exakte Laufzeit.")
        self.status.setWordWrap(True)
        pl.addWidget(self.status)
        pl.addStretch(1)

    def _engine_changed(self, engine) -> None:
        set_channel_count(self.cb_meas, self.state.input_channels)
        set_channel_count(self.cb_ref, self.state.input_channels)
        set_channel_count(self.cb_out, self.state.output_channels, "Ausgang")

    # --- Messung --------------------------------------------------------------
    def measure(self) -> None:
        eng = self.state.engine
        if eng is None:
            self.status.setText("Zuerst Audio starten (Symbolleiste).")
            return
        if eng.generator is not None:
            self.status.setText("Hinweis: Generator wird während der Messung pausiert.")
        params = dict(out=self.cb_out.currentData(), meas=self.cb_meas.currentData(),
                      ref=self.cb_ref.currentData(), duration=float(self.cb_len.currentData()),
                      f1=self.sp_f1.value(), f2=self.sp_f2.value(), level=self.sp_level.value(),
                      averages=self.sp_avg.value(), tail=self.sp_tail.value())
        if params["ref"] == params["meas"]:
            self.status.setText("Referenz und Messkanal dürfen nicht gleich sein.")
            return
        self.worker = MeasureWorker(eng, params)
        self.worker.progress.connect(self.status.setText)
        self.worker.finished_ok.connect(self._measured)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(lambda: (self.btn_measure.setEnabled(True), self.btn_cancel.setEnabled(False)))
        self.btn_measure.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.worker.start()

    def cancel(self) -> None:
        if self.worker is not None:
            self.worker.cancel.set()

    def _failed(self, msg: str) -> None:
        self.status.setText(f"Fehler: {msg}")

    def _measured(self, h: np.ndarray, fs: float, info: str) -> None:
        self.set_ir(h, fs)
        self.status.setText(f"Messung fertig ({time.strftime('%H:%M:%S')}). {info}")

    def set_ir(self, h: np.ndarray, fs: float) -> None:
        self.ir, self.fs = np.asarray(h, float), fs
        self.results = room.analyze(self.ir, fs)
        try:
            r_sti = sti.sti_from_ir(self.ir, fs, "STI")
            r_stipa = sti.sti_from_ir(self.ir, fs, "STIPA")
            self.lbl_sti.setText(f"STI: {r_sti.sti:.2f} ({r_sti.rating})      "
                                 f"STIPA: {r_stipa.sti:.2f} ({r_stipa.rating})      "
                                 f"<span style='font-weight:normal;font-size:11px'>"
                                 f"ohne Störgeräusch/Maskierung</span>")
        except ValueError as exc:
            self.lbl_sti.setText(f"STI nicht berechenbar: {exc}")
        self._fill_table()
        self.redraw()

    def _fill_table(self) -> None:
        res = self.results
        self.table.setColumnCount(len(res))
        self.table.setRowCount(len(room.METRICS))
        self.table.setHorizontalHeaderLabels([r.label for r in res])
        self.table.setVerticalHeaderLabels([name for _, name in room.METRICS])
        for c, r in enumerate(res):
            for row, (key, _) in enumerate(room.METRICS):
                v = getattr(r, key)
                fmt = "{:.2f}" if key in ("edt", "t20", "t30") else "{:.1f}"
                text = "–" if v is None or not np.isfinite(v) else fmt.format(v)
                item = QtWidgets.QTableWidgetItem(text)
                item.setTextAlignment(QtCore.Qt.AlignCenter)
                self.table.setItem(row, c, item)
        self.table.resizeColumnsToContents()

    # --- Darstellung ------------------------------------------------------------
    def _band_ir(self) -> np.ndarray:
        band = self.cb_band.currentData()
        if band == "Breitband" or self.ir is None:
            return self.ir
        return signal.sosfilt(band_filter_sos(float(band), 1, self.fs), self.ir)

    def redraw(self) -> None:
        if self.ir is None:
            return
        view = self.cb_view.currentText()
        h = self._band_ir()
        t = np.arange(len(h)) / self.fs
        if view in VIEWS[:4]:
            self.stack.setCurrentWidget(self.p_time)
            self.p_time.clear()
            pen = pg.mkPen("#55aaff", width=1)
            step = max(1, len(h) // 200000)
            if view == "Linear":
                self.p_time.setLabel("left", "Amplitude")
                self.p_time.plot(t[::step], (h / np.abs(h).max())[::step], pen=pen)
            elif view == "Logarithmisch":
                self.p_time.setLabel("left", "dB")
                self.p_time.plot(t[::step], impulse.log_view(h)[::step], pen=pen)
            elif view.startswith("ETC"):
                self.p_time.setLabel("left", "dB")
                self.p_time.plot(t[::step], impulse.etc(h)[::step], pen=pen)
            else:
                self.p_time.setLabel("left", "dB")
                start = impulse.ir_start(h)
                edc = room.schroeder(h[start:], self.fs)
                te = (np.arange(len(edc)) + start) / self.fs
                self.p_time.plot(te[::step], edc[::step], pen=pg.mkPen("#ffcc33", width=2))
                self.p_time.plot(t[::step], impulse.etc(h)[::step], pen=pg.mkPen("#55aaff55"))
                for y in (-5, -25, -35):
                    self.p_time.addLine(y=y, pen=pg.mkPen("#888", style=QtCore.Qt.DashLine))
            if view != "Linear":
                self.p_time.setYRange(-100, 2)
            self.p_time.enableAutoRange(axis="x")
        elif view == "Frequenzgang":
            self.stack.setCurrentWidget(self.p_freq)
            start = max(0, impulse.ir_start(h) - int(0.002 * self.fs))
            f, mag, _ = impulse.frequency_response(h[start:], self.fs)
            mag -= np.median(mag[(f > 200) & (f < 5000)])
            self.freq_resp = (f[1:], mag[1:])
            self.c_freq.setData(f[1:], mag[1:])
        else:
            self.stack.setCurrentWidget(self.p_spectro)
            start = max(0, impulse.ir_start(h) - int(0.01 * self.fs))
            seg = h[start: start + int(min(2.0, len(h) / self.fs) * self.fs)]
            ts, fr, db = impulse.spectrogram(seg, self.fs, nfft=2048, overlap=0.95)
            f_log = np.logspace(np.log10(20), np.log10(self.fs / 2 * 0.95), 300)
            img = np.array([np.interp(f_log, fr, row) for row in db])
            self.img.setImage(img, levels=(-80, 0))
            x0, x1 = ts[0], ts[-1]
            y0, y1 = np.log10(f_log[0]), np.log10(f_log[-1])
            self.img.setRect(QtCore.QRectF(x0, y0, x1 - x0, y1 - y0))
            self.p_spectro.setXRange(x0, x1, padding=0)
            self.p_spectro.setYRange(y0, y1, padding=0)

    # --- Dateien ----------------------------------------------------------------
    def load_wav(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Impulsantwort laden", "", "WAV (*.wav)")
        if not path:
            return
        fs, raw = wavfile.read(path)
        data = raw.astype(float)
        if np.issubdtype(raw.dtype, np.integer):
            data /= np.iinfo(raw.dtype).max
        if data.ndim > 1:
            data = data[:, 0]
        self.set_ir(data, float(fs))
        self.status.setText(f"Geladen: {path}")

    def save_wav(self) -> None:
        if self.ir is None:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Impulsantwort speichern",
                                                        "impulsantwort.wav", "WAV (*.wav)")
        if path:
            norm = self.ir / (np.abs(self.ir).max() + 1e-30) * 0.9
            wavfile.write(path, int(self.fs), norm.astype(np.float32))

    def export_csv(self) -> None:
        if not self.results:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Kennwerte exportieren",
                                                        "raumakustik.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", encoding="utf-8-sig") as fh:
            fh.write("Kennwert;" + ";".join(r.label for r in self.results) + "\n")
            for key, name in room.METRICS:
                vals = [getattr(r, key) for r in self.results]
                fh.write(name + ";" + ";".join(
                    "" if not np.isfinite(v) else f"{v:.3f}".replace(".", ",") for v in vals) + "\n")
            fh.write("\n" + self.lbl_sti.text().split("<span")[0] + "\n")
