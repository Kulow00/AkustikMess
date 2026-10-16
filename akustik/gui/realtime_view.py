"""Echtzeit-Modus: Spektrum (RTA) und Zweikanal-Übertragungsfunktion."""

from __future__ import annotations

import time

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

from ..dsp import octave, targets, tracemath
from ..dsp.spectrum import WINDOWS, SpectrumAnalyzer, peak_frequency
from ..dsp.transfer import MultiWindowTransferFunction, TransferFunction, find_delay
from ..dsp.weighting import weighting_db
from ..dsp.notes import format_freq, format_note
from .common import (CursorGroup, FreqCursor, TraceStore, channel_combo, combo, curve_value,
                     freq_plot, log_decimate, set_channel_count)
from .session import apply_controls_state, controls_state, name_controls
from .state import AppState

FFT_SIZES = [2048, 4096, 8192, 16384, 32768, 65536]
MTW = "MTW (Multi-Time-Window)"
BANDINGS = {"Schmalband (FFT)": 0, "1/1 Oktave": 1, "1/3 Oktave": 3, "1/6 Oktave": 6,
            "1/12 Oktave": 12, "1/24 Oktave": 24, "1/48 Oktave": 48}
SMOOTHING = {"keine": 0, "1/48 Okt.": 48, "1/24 Okt.": 24, "1/12 Okt.": 12, "1/6 Okt.": 6, "1/3 Okt.": 3}
AVERAGES = {"keine": (1, False), "2": (2, False), "4": (4, False), "8": (8, False), "16": (16, False),
            "32": (32, False), "Exp. langsam": (32, True), "Exp. schnell": (6, True)}


class RealtimeView(QtWidgets.QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.spec: SpectrumAnalyzer | None = None
        self.tf: TransferFunction | None = None
        self.peak_hold = None
        self.last_tf = None
        self.last_spec = None
        self._title_time = 0.0
        self.peak_text = ""
        self.remote_active = False  # Fernbedienung braucht Daten auch bei verdeckter Ansicht
        self._build()
        self.timer = QtCore.QTimer(self, interval=50, timeout=self.update_plots)
        state.engine_changed.connect(self._engine_changed)
        state.calibration_changed.connect(self._reset_spectrum)

    # --- Aufbau --------------------------------------------------------------
    def _build(self) -> None:
        lay = QtWidgets.QHBoxLayout(self)
        splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self.p_phase = freq_plot("Phase", "Phase [°]", (-180, 180), y_grid=90, y_span=(-180, 180))
        self.p_mag = freq_plot("Übertragungsfunktion – Betrag", "dB", (-40, 20), y_grid=6)
        self.p_coh = freq_plot("", "Kohärenz", (0, 1.05), y_grid=0.5, y_span=(0, 1))
        self.p_spec = freq_plot("Spektrum", "dBFS", (-120, 0))
        for p in (self.p_phase, self.p_coh, self.p_spec):
            p.setXLink(self.p_mag)
        self.p_phase.getAxis("left").setTicks([[(v, str(v)) for v in (-180, -90, 0, 90, 180)]])
        self.p_coh.setMaximumHeight(130)
        for p in (self.p_phase, self.p_mag, self.p_coh, self.p_spec):
            splitter.addWidget(p)
        splitter.setSizes([200, 300, 90, 300])
        lay.addWidget(splitter, 1)

        self.c_phase = self.p_phase.plot(pen=pg.mkPen("#ff5555", width=1.5), connect="finite")
        self.c_mag = self.p_mag.plot(pen=pg.mkPen("#ff5555", width=1.5), connect="finite")
        self.c_coh = self.p_coh.plot(pen=pg.mkPen("#ff5555", width=1), connect="finite")
        self.c_spec = self.p_spec.plot(pen=pg.mkPen("#55aaff", width=1.5),
                                       fillLevel=-200, brush=(85, 170, 255, 60))
        self.c_peak = self.p_spec.plot(pen=pg.mkPen("#ffcc33", width=1, style=QtCore.Qt.DotLine))
        self.trace_items: list = []

        # Fadenkreuz mit genauer Frequenz und Note; senkrechte Linie in allen Plots gekoppelt
        group = CursorGroup()

        def tf_value(idx, unit, fmt):
            def fn(f):
                if self.last_tf is None:
                    return None
                v = curve_value(self.last_tf[0], self.last_tf[idx], f)
                return None if v is None else f"Messwert: {fmt.format(v)} {unit}"
            return fn

        def spec_value(f):
            if self.last_spec is None:
                return None
            x, lv, stepped = self.last_spec
            v = curve_value(x, lv, f, stepped)
            return None if v is None else f"Messwert: {v:.1f} {self.p_spec.getAxis('left').labelText}"

        self.cursors = [
            FreqCursor(self.p_phase, self.state, unit="°", value_fn=tf_value(2, "°", "{:.0f}"), group=group),
            FreqCursor(self.p_mag, self.state, unit="dB", value_fn=tf_value(1, "dB", "{:.1f}"), group=group),
            FreqCursor(self.p_coh, self.state, unit="", value_fn=tf_value(3, "", "{:.2f}"), group=group),
            FreqCursor(self.p_spec, self.state, unit="dB", value_fn=spec_value, group=group),
        ]

        # Bedienfeld
        panel = QtWidgets.QWidget()
        form_lay = QtWidgets.QVBoxLayout(panel)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        scroll.setFixedWidth(300)
        lay.addWidget(scroll)

        top = QtWidgets.QHBoxLayout()
        self.cb_layout = combo(["Beides", "Nur Übertragungsfunktion", "Nur Spektrum"])
        self.cb_layout.currentIndexChanged.connect(self._apply_layout)
        top.addWidget(QtWidgets.QLabel("Ansicht:"))
        top.addWidget(self.cb_layout, 1)
        form_lay.addLayout(top)

        g_spec = QtWidgets.QGroupBox("Spektrum")
        f = QtWidgets.QFormLayout(g_spec)
        self.cb_spec_ch = channel_combo(2, 0)
        self.cb_spec_fft = combo(FFT_SIZES, 16384)
        self.cb_spec_avg = combo(list(AVERAGES), "4")
        self.cb_spec_band = combo(list(BANDINGS), "1/3 Oktave")
        self.cb_spec_window = combo(list(WINDOWS), "Hann")
        self.cb_weight = combo(["Z", "A", "C"], "Z")
        self.chk_peak = QtWidgets.QCheckBox("Spitzenwert halten")
        f.addRow("Kanal", self.cb_spec_ch)
        f.addRow("FFT-Größe", self.cb_spec_fft)
        f.addRow("Mittelung", self.cb_spec_avg)
        f.addRow("Darstellung", self.cb_spec_band)
        f.addRow("Fenster", self.cb_spec_window)
        f.addRow("Bewertung", self.cb_weight)
        f.addRow(self.chk_peak)
        for w in (self.cb_spec_ch, self.cb_spec_fft, self.cb_spec_avg, self.cb_spec_window):
            w.currentIndexChanged.connect(self._reset_spectrum)
        self.chk_peak.toggled.connect(lambda _: setattr(self, "peak_hold", None))
        form_lay.addWidget(g_spec)

        g_tf = QtWidgets.QGroupBox("Übertragungsfunktion")
        f = QtWidgets.QFormLayout(g_tf)
        self.cb_ref = channel_combo(2, 1)
        self.cb_meas = channel_combo(2, 0)
        self.cb_tf_fft = combo([MTW, *FFT_SIZES], MTW)
        self.cb_tf_fft.setToolTip("MTW: lange Zeitfenster im Bass, kurze im Hochton (≈1/24 Oktave "
                                  "überall) – ruhigere Kurven, späte Reflexionen werden ausgeblendet.")
        self.cb_tf_avg = combo(list(AVERAGES), "8")
        self.cb_smooth = combo(list(SMOOTHING), "1/24 Okt.")
        self.sp_delay = QtWidgets.QDoubleSpinBox(decimals=2, maximum=1000.0, singleStep=0.02, suffix=" ms")
        self.btn_delay = QtWidgets.QPushButton("Laufzeit finden")
        self.btn_delay.clicked.connect(self.find_delay)
        # MTW bewertet Hall im Hochton ehrlich als unkorreliert → niedrigere Schwelle als bei fester FFT
        self.sp_coh = QtWidgets.QDoubleSpinBox(decimals=2, maximum=1.0, singleStep=0.05, value=0.3)
        self.chk_blank = QtWidgets.QCheckBox("Ausblenden unter Kohärenz-Schwelle")
        self.chk_blank.setChecked(True)
        f.addRow("Referenz", self.cb_ref)
        f.addRow("Messung", self.cb_meas)
        f.addRow("FFT-Größe", self.cb_tf_fft)
        f.addRow("Mittelung", self.cb_tf_avg)
        f.addRow("Glättung", self.cb_smooth)
        f.addRow("Verzögerung", self.sp_delay)
        f.addRow(self.btn_delay)
        f.addRow("Kohärenz-Schwelle", self.sp_coh)
        f.addRow(self.chk_blank)
        for w in (self.cb_ref, self.cb_meas, self.cb_tf_fft, self.cb_tf_avg):
            w.currentIndexChanged.connect(self._reset_tf)
        self.sp_delay.valueChanged.connect(self._reset_tf)
        form_lay.addWidget(g_tf)

        g_tg = QtWidgets.QGroupBox("Zielkurve")
        f = QtWidgets.QFormLayout(g_tg)
        self.cb_target = combo(["keine", *targets.PRESETS, "Aus Datei…"], "keine")
        self.sp_tol = QtWidgets.QDoubleSpinBox(minimum=0, maximum=12, value=3.0, decimals=1,
                                               singleStep=0.5, suffix=" dB")
        self.chk_target_auto = QtWidgets.QCheckBox("Pegel automatisch an Messung angleichen")
        self.chk_target_auto.setChecked(True)
        self.sp_target_off = QtWidgets.QDoubleSpinBox(minimum=-60, maximum=60, decimals=1,
                                                      singleStep=0.5, suffix=" dB")
        f.addRow("Kurve", self.cb_target)
        f.addRow("Toleranz ±", self.sp_tol)
        f.addRow(self.chk_target_auto)
        f.addRow("Versatz", self.sp_target_off)
        self.cb_target.activated.connect(self._target_selected)
        for w in (self.sp_tol, self.sp_target_off):
            w.valueChanged.connect(self._draw_target)
        self.chk_target_auto.toggled.connect(lambda on: self.sp_target_off.setEnabled(not on))
        self.sp_target_off.setEnabled(False)
        form_lay.addWidget(g_tg)

        g_tr = QtWidgets.QGroupBox("Gespeicherte Kurven")
        v = QtWidgets.QVBoxLayout(g_tr)
        row = QtWidgets.QHBoxLayout()
        b1 = QtWidgets.QPushButton("Übertragung (S)")
        b2 = QtWidgets.QPushButton("Spektrum (⇧S)")
        b1.setToolTip("Aktuelle Übertragungsfunktion speichern")
        b2.setToolTip("Aktuelles Spektrum speichern")
        b1.clicked.connect(self.capture_tf)
        b2.clicked.connect(self.capture_spec)
        row.addWidget(b1)
        row.addWidget(b2)
        v.addLayout(row)
        self.traces = TraceStore()
        self.traces.changed.connect(self._redraw_traces)
        v.addWidget(self.traces)
        row = QtWidgets.QHBoxLayout()
        b_diff = QtWidgets.QPushButton("Differenz A − B")
        b_diff.setToolTip("Zwei gewählte Übertragungsfunktionen voneinander abziehen")
        b_diff.clicked.connect(self.difference_selected)
        b_align = QtWidgets.QPushButton("Crossover…")
        b_align.setToolTip("Zwei Kurven virtuell summieren und Laufzeit/Polarität ausrichten")
        b_align.clicked.connect(self.open_alignment)
        row.addWidget(b_diff)
        row.addWidget(b_align)
        v.addLayout(row)
        self.chk_relative = QtWidgets.QCheckBox("Live relativ zur gewählten Kurve")
        self.chk_relative.setToolTip("Zeigt Live − gespeicherte Kurve: ideal zum Einstellen von EQs")
        self.chk_relative.toggled.connect(self._relative_toggled)
        v.addWidget(self.chk_relative)
        form_lay.addWidget(g_tr, 1)

        self.status = QtWidgets.QLabel("Kein Audio-Gerät aktiv")
        self.status.setWordWrap(True)
        form_lay.addWidget(self.status)

        # Zielkurve (Linie + Toleranzband) im Betragsplot
        pen_t = pg.mkPen("#e0e0e0", width=1.5, style=QtCore.Qt.DashLine)
        self.c_target = self.p_mag.plot(pen=pen_t)
        self.c_tol_hi = self.p_mag.plot(pen=pg.mkPen((224, 224, 224, 60)))
        self.c_tol_lo = self.p_mag.plot(pen=pg.mkPen((224, 224, 224, 60)))
        self.tol_band = pg.FillBetweenItem(self.c_tol_lo, self.c_tol_hi, brush=(224, 224, 224, 28))
        self.tol_band.setZValue(-60)
        self.p_mag.addItem(self.tol_band)
        self.target_points: list | None = None
        self.target_file_points: list | None = None
        self.relative_ref: dict | None = None
        name_controls(self)

    def _apply_layout(self) -> None:
        mode = self.cb_layout.currentText()
        show_tf = mode != "Nur Spektrum"
        show_spec = mode != "Nur Übertragungsfunktion"
        for p in (self.p_phase, self.p_mag, self.p_coh):
            p.setVisible(show_tf)
        self.p_spec.setVisible(show_spec)

    # --- Engine ----------------------------------------------------------------
    def _engine_changed(self, engine) -> None:
        n = self.state.input_channels
        for c in (self.cb_spec_ch, self.cb_ref, self.cb_meas):
            set_channel_count(c, n)
        if engine is None:
            self.timer.stop()
            self.status.setText("Kein Audio-Gerät aktiv")
            return
        self._reset_spectrum()
        self._reset_tf()
        self.timer.start()

    def _reset_spectrum(self) -> None:
        fft = self.cb_spec_fft.currentData()
        count, exp = AVERAGES[self.cb_spec_avg.currentText()]
        self.spec = SpectrumAnalyzer(self.state.fs, fft, self.cb_spec_window.currentText(), count, exp)
        self.peak_hold = None
        cal = self.state.calibration_for(self.cb_spec_ch.currentData() or 0)
        self.p_spec.setLabel("left", "dB SPL" if cal is not None else "dBFS")
        if cal is not None:
            self.p_spec.setYRange(cal - 120, cal, padding=0)
        else:
            self.p_spec.setYRange(-120, 0, padding=0)

    def _reset_tf(self) -> None:
        fft = self.cb_tf_fft.currentData()
        count, exp = AVERAGES[self.cb_tf_avg.currentText()]
        if fft == MTW:
            self.tf = MultiWindowTransferFunction(self.state.fs, averages=count, exponential=exp)
        else:
            self.tf = TransferFunction(self.state.fs, fft, "Hann", count, exp)

    def tf_period(self) -> int:
        """Periodenlänge für periodisches Rauschen passend zur Übertragungsfunktion."""
        fft = self.cb_tf_fft.currentData()
        return 32768 if fft == MTW else int(fft)

    # --- Messung --------------------------------------------------------------
    def find_delay(self) -> None:
        eng = self.state.engine
        if eng is None:
            return
        n = int(eng.fs * 2)
        buf = eng.ring.latest(n).astype(float)
        ref, meas = buf[:, self.cb_ref.currentData()], buf[:, self.cb_meas.currentData()]
        if np.std(ref) < 1e-6:
            self.status.setText("Referenzsignal ist stumm – Generator einschalten?")
            return
        d = find_delay(ref, meas, max_delay=int(eng.fs))
        self.sp_delay.setValue(1000 * d / eng.fs)
        self.status.setText(f"Laufzeit: {1000 * d / eng.fs:.2f} ms ≈ {343 * d / eng.fs:.2f} m")

    def update_plots(self) -> None:
        eng = self.state.engine
        if eng is None:
            return
        t0 = time.perf_counter()
        if (self.p_spec.isVisible() or self.remote_active) and self.spec is not None:
            self._update_spectrum(eng)
        if (self.p_mag.isVisible() or self.remote_active) and self.tf is not None:
            self._update_tf(eng)
        ms = 1000 * (time.perf_counter() - t0)
        if eng.xruns:
            self.status.setText(f"Rechenzeit {ms:.0f} ms · Aussetzer: {eng.xruns}")

    def _spectrum_db(self, freqs, power, cal):
        offset = cal if cal is not None else 0.0
        band = BANDINGS[self.cb_spec_band.currentText()]
        weight = self.cb_weight.currentText()
        if band:
            centers = octave.band_centers(band, 20, min(20000, self.state.fs / 2 * 0.9))
            bp = octave.band_power_from_spectrum(freqs, power, centers, band)
            lv = 10 * np.log10(bp + 1e-30) + offset + weighting_db(centers, weight)
            lo, hi = octave.band_edges(centers, band)
            edges = np.concatenate([lo, hi[-1:]])
            return edges, lv, True
        # Leistung je FFT-Bin: ein Sinuston zeigt seinen echten Pegel
        f = freqs[1:]
        lv = 10 * np.log10(power[1:] + 1e-30) + offset + weighting_db(f, weight)
        return f, lv, False

    def _update_spectrum(self, eng) -> None:
        ch = self.cb_spec_ch.currentData() or 0
        if ch >= eng.ring.channels:
            return
        x = eng.ring.latest(self.spec.fft_size)[:, ch]
        power = self.spec.update(x)
        cal = self.state.calibration_for(ch)
        x_axis, lv, stepped = self._spectrum_db(self.spec.freqs, power, cal)
        # stärkste Spektrallinie mit Sub-Bin-Genauigkeit und Note im Titel
        # (Titel nur ~5× pro Sekunde setzen – jede Änderung löst ein Neu-Layout aus)
        now = time.monotonic()
        if now - self._title_time > 0.2:
            self._title_time = now
            fpk, ppk = peak_frequency(self.spec.freqs, power)
            if np.isfinite(fpk) and ppk > 1e-12:
                lvl = 10 * np.log10(ppk) + (cal or 0.0)
                self.peak_text = (f"Spitze: {format_freq(fpk)} · "
                                  f"{format_note(fpk, self.state.a4, self.state.note_naming)} · {lvl:.1f} dB")
                self.p_spec.setTitle(
                    f"Spektrum &nbsp;·&nbsp; Spitze: <b>{format_freq(fpk)}</b> &nbsp;"
                    f"{format_note(fpk, self.state.a4, self.state.note_naming)} &nbsp;"
                    f"({lvl:.1f} dB) &nbsp;·&nbsp; A4 = {self.state.a4:g} Hz")
        self.last_spec = (x_axis, lv, stepped)  # volle Auflösung für das Fadenkreuz
        if self.chk_peak.isChecked():
            if self.peak_hold is None or self.peak_hold.shape != lv.shape:
                self.peak_hold = lv.copy()
            self.peak_hold = np.maximum(self.peak_hold, lv)
        if stepped:
            self.c_spec.setData(x_axis, lv, stepMode="center", fillLevel=-200, skipFiniteCheck=True)
            if self.chk_peak.isChecked():
                self.c_peak.setData(x_axis, self.peak_hold, stepMode="center")
        else:
            fd, d = log_decimate(x_axis, lv=("max", lv),
                                 peak=("max", self.peak_hold if self.chk_peak.isChecked() else lv))
            self.c_spec.setData(fd, d["lv"], stepMode=None, fillLevel=-200, skipFiniteCheck=True)
            if self.chk_peak.isChecked():
                self.c_peak.setData(fd, d["peak"], stepMode=None)
        if not self.chk_peak.isChecked():
            self.c_peak.setData([], [])

    def _update_tf(self, eng) -> None:
        ref_ch, meas_ch = self.cb_ref.currentData(), self.cb_meas.currentData()
        if ref_ch is None or meas_ch is None or max(ref_ch, meas_ch) >= eng.ring.channels:
            return
        n = self.tf.length
        d = int(round(self.sp_delay.value() * 1e-3 * eng.fs))
        buf = eng.ring.latest(n + d).astype(float)
        ref, meas = buf[:n, ref_ch], buf[d:d + n, meas_ch]
        if np.std(ref) < 1e-7:
            self.status.setText("Referenz stumm – für die Übertragungsfunktion den Generator "
                                "einschalten oder ein Musiksignal anlegen.")
            return
        res = self.tf.update(ref, meas, SMOOTHING[self.cb_smooth.currentText()])
        keep = res.freqs > 0  # Gleichanteil weglassen (log. Achse)
        f = res.freqs[keep]
        mag, phase, coh = res.magnitude_db[keep], res.phase_deg[keep], res.coherence[keep]
        r = self.relative_ref
        if r is not None:  # Live − gespeicherte Kurve
            f, mag, phase, coh = tracemath.difference(f, mag, phase, coh, np.asarray(r["freqs"]),
                                                      r["mag"], r["phase"], r["coh"])
        self.last_tf = (f, mag, phase, coh)  # volle Auflösung für Fadenkreuz und Speichern
        if self.target_points is not None and self.chk_target_auto.isChecked():
            off = targets.auto_offset(f, mag, targets.target_db(self.target_points, f))
            if abs(off - self.sp_target_off.value()) > 0.3:  # nur bei spürbarer Änderung neu zeichnen
                self.sp_target_off.setValue(round(off, 1))
        fd, d = log_decimate(f, mag=("mean", mag), phase=("phase", phase), coh=("mean", coh))
        mag, phase, coh = d["mag"], d["phase"], d["coh"]
        if self.chk_blank.isChecked():
            bad = coh < self.sp_coh.value()
            mag = np.where(bad, np.nan, mag)
            phase = np.where(bad, np.nan, phase)
        self.c_mag.setData(fd, mag)
        self.c_phase.setData(fd, phase)
        self.c_coh.setData(fd, coh, skipFiniteCheck=True)
        if not eng.xruns:
            if isinstance(self.tf, MultiWindowTransferFunction):
                times = self.tf.window_times_ms
                res_txt = (f"MTW {len(times)} Fenster: {times[0][0]:.0f} ms (Bass) … "
                           f"{times[-1][0]:.1f} ms (ab {times[-1][1] / 1000:.1f} kHz)")
            else:
                res_txt = f"Auflösung {eng.fs / n:.2f} Hz"
            self.status.setText(f"Laufzeit-Kompensation {self.sp_delay.value():.2f} ms · {res_txt}")

    # --- Zielkurve ----------------------------------------------------------------
    def _target_selected(self) -> None:
        name = self.cb_target.currentText()
        if name == "Aus Datei…":
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "Zielkurve laden", "", "Text/CSV/FRD (*.txt *.csv *.frd);;Alle Dateien (*)")
            if not path:
                self.cb_target.setCurrentText("keine")
                self.target_points = None
                self._draw_target()
                return
            try:
                with open(path, encoding="utf-8-sig", errors="replace") as fh:
                    self.target_file_points = targets.parse_target(fh.read())
            except (OSError, ValueError) as exc:
                QtWidgets.QMessageBox.warning(self, "Zielkurve", f"Datei nicht lesbar:\n{exc}")
                self.cb_target.setCurrentText("keine")
                self.target_points = None
                self._draw_target()
                return
        self._apply_target_choice()

    def _apply_target_choice(self) -> None:
        name = self.cb_target.currentText()
        if name == "keine":
            self.target_points = None
        elif name == "Aus Datei…":
            self.target_points = self.target_file_points
        else:
            self.target_points = targets.PRESETS[name]
        self._draw_target()

    def _draw_target(self) -> None:
        if self.target_points is None:
            for c in (self.c_target, self.c_tol_hi, self.c_tol_lo):
                c.setData([], [])
            self.tol_band.setVisible(False)
            return
        f = np.geomspace(20, 20000, 400)
        t = targets.target_db(self.target_points, f) + self.sp_target_off.value()
        tol = self.sp_tol.value()
        self.c_target.setData(f, t)
        self.c_tol_hi.setData(f, t + tol)
        self.c_tol_lo.setData(f, t - tol)
        self.tol_band.setVisible(tol > 0)

    # --- Kurven-Rechnung ------------------------------------------------------------
    def difference_selected(self) -> None:
        sel = self.traces.selected("tf")
        if len(sel) != 2:
            QtWidgets.QMessageBox.information(
                self, "Differenz", "Bitte genau zwei gespeicherte Übertragungsfunktionen markieren "
                "(Strg+Klick). Die zuerst stehende ist A.")
            return
        a, b = sel
        f, mag, ph, coh = tracemath.difference(np.asarray(a["freqs"]), a["mag"], a["phase"], a["coh"],
                                               np.asarray(b["freqs"]), b["mag"], b["phase"], b["coh"])
        self.traces.add(f"{a['name']} − {b['name']}",
                        {"kind": "tf", "freqs": f, "mag": mag, "phase": ph, "coh": coh, "delay_ms": 0.0})

    def _relative_toggled(self, on: bool) -> None:
        if not on:
            self.relative_ref = None
            self.p_mag.setTitle("Übertragungsfunktion – Betrag")
            return
        sel = self.traces.selected("tf")
        if not sel:
            QtWidgets.QMessageBox.information(self, "Relativ", "Bitte zuerst eine gespeicherte "
                                              "Übertragungsfunktion in der Liste markieren.")
            self.chk_relative.setChecked(False)
            return
        self.relative_ref = sel[0]
        self.p_mag.setTitle(f"Übertragungsfunktion – <b>relativ zu „{sel[0]['name']}“</b>")

    def open_alignment(self) -> None:
        from .align_dialog import AlignDialog  # noqa: PLC0415 – erst bei Bedarf laden
        self.align_dialog = AlignDialog(self.state, self.traces, self)
        self.align_dialog.show()

    def reset_averages(self) -> None:
        for a in (self.spec, self.tf):
            if a is not None:
                a.avg.reset()
        self.peak_hold = None

    def capture_current(self) -> None:
        """Taste S: Übertragungsfunktion speichern, im reinen Spektrum-Modus das Spektrum."""
        if self.p_mag.isVisible() and self.last_tf is not None:
            self.capture_tf()
        else:
            self.capture_spec()

    # --- Sitzung -------------------------------------------------------------------
    def get_state(self) -> tuple[dict, dict]:
        traces_meta, arrays = self.traces.to_session("rt_trace")
        meta = {"controls": controls_state(self), "traces": traces_meta,
                "target_file_points": self.target_file_points}
        return meta, arrays

    def set_state(self, meta: dict, arrays: dict) -> None:
        self.chk_relative.setChecked(False)
        apply_controls_state(self, meta.get("controls", {}))
        self.target_file_points = meta.get("target_file_points")
        self._apply_target_choice()
        self.traces.from_session("rt_trace", meta.get("traces", []), arrays)

    # --- Gespeicherte Kurven ----------------------------------------------------
    def capture_tf(self, name: str | None = None) -> None:
        if self.last_tf is None:
            return
        f, mag, phase, coh = (a.copy() for a in self.last_tf)
        rel = f" (relativ zu {self.relative_ref['name']})" if self.relative_ref else ""
        label = f"{name} ({time.strftime('%H:%M')})" if name else f"Übertragung {time.strftime('%H:%M:%S')}"
        self.traces.add(f"{label}{rel}",
                        {"kind": "tf", "freqs": f, "mag": mag, "phase": phase, "coh": coh,
                         "delay_ms": 0.0 if self.relative_ref else self.sp_delay.value()})

    def capture_spec(self, name: str | None = None) -> None:
        if self.last_spec is None:
            return
        x, lv, stepped = self.last_spec
        label = f"{name} – Spektrum ({time.strftime('%H:%M')})" if name else f"Spektrum {time.strftime('%H:%M:%S')}"
        self.traces.add(label,
                        {"kind": "spec", "freqs": x.copy(), "mag": lv.copy(), "stepped": stepped})

    def _redraw_traces(self) -> None:
        for plot, item in self.trace_items:
            plot.removeItem(item)
        self.trace_items = []
        for t in self.traces.traces:
            if not t["visible"]:
                continue
            pen = pg.mkPen(t["color"], width=1.2)
            if t["kind"] == "tf":
                fd, d = log_decimate(t["freqs"], mag=("mean", t["mag"]), phase=("phase", t["phase"]),
                                     coh=("mean", t["coh"]))
                for plot, key in ((self.p_mag, "mag"), (self.p_phase, "phase"), (self.p_coh, "coh")):
                    item = plot.plot(fd, d[key], pen=pen, connect="finite")
                    self.trace_items.append((plot, item))
            elif t["stepped"]:
                item = self.p_spec.plot(t["freqs"], t["mag"], pen=pen, stepMode="center")
                self.trace_items.append((self.p_spec, item))
            else:
                fd, d = log_decimate(t["freqs"], mag=("max", t["mag"]))
                item = self.p_spec.plot(fd, d["mag"], pen=pen)
                self.trace_items.append((self.p_spec, item))
