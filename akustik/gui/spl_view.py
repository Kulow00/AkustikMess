"""SPL-Modus: Pegelmessung, Verlauf, Protokoll, Alarme, Notizen, Bericht."""

from __future__ import annotations

import base64
import collections
import datetime as dt
import html
import os
import tempfile
import time

import numpy as np
import pyqtgraph as pg
import pyqtgraph.exporters
from PySide6 import QtCore, QtWidgets

from ..dsp.spl import SPLMeter, calibration_offset
from .common import channel_combo, combo, set_channel_count
from .session import apply_controls_state, controls_state, name_controls
from .state import AppState

ROLLING = {"LAeq 1 s": ("A", 1), "LAeq 1 min": ("A", 60), "LAeq 15 min": ("A", 900),
           "LCeq 1 s": ("C", 1), "LCeq 1 min": ("C", 60), "LCeq 15 min": ("C", 900)}
ALL_METRICS = (
    ["LAF", "LAS", "LAI", "LCF", "LCS", "LZF", "LZS"] + list(ROLLING)
    + ["LAeq", "LCeq", "LZeq", "LCpeak", "LZpeak", "LCpeakmax", "LZpeakmax",
       "LAFmax", "LAFmin", "LASmax", "LASmin", "LCFmax"]
)
DEFAULT_TILES = ["LAF", "LAS", "LAeq 1 min", "LAeq 15 min", "LAeq", "LCeq 1 min",
                 "LCeq", "LCpeakmax", "LAFmax", "LAFmin"]
HISTORY_MAX = 24 * 3600


class Tile(QtWidgets.QFrame):
    def __init__(self, name: str):
        super().__init__()
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        self.name = QtWidgets.QLabel(name)
        self.name.setStyleSheet("color: #aaa; font-size: 11px;")
        self.value = QtWidgets.QLabel("–")
        self.value.setStyleSheet("font-size: 22px; font-weight: bold;")
        lay.addWidget(self.name)
        lay.addWidget(self.value)

    def set(self, v: float | None) -> None:
        self.value.setText("–" if v is None or not np.isfinite(v) else f"{v:.1f}")


class CalibrationDialog(QtWidgets.QDialog):
    def __init__(self, state: AppState, channel: int, parent=None):
        super().__init__(parent)
        self.state, self.channel = state, channel
        self.setWindowTitle(f"Kalibrierung – Eingang {channel + 1}")
        f = QtWidgets.QFormLayout(self)
        info = QtWidgets.QLabel("Schallkalibrator (1 kHz) auf das Messmikrofon setzen, "
                                "einschalten und „Messen“ drücken. Alternativ den Wert "
                                "(dB SPL bei 0 dBFS RMS) direkt eingeben.")
        info.setWordWrap(True)
        f.addRow(info)
        self.ref = combo([94.0, 104.0, 114.0], 94.0)
        self.ref.setEditable(True)
        f.addRow("Kalibratorpegel [dB SPL]", self.ref)
        cur = state.calibration_for(channel)
        self.offset = QtWidgets.QDoubleSpinBox(minimum=0, maximum=200, decimals=2,
                                               value=cur if cur is not None else 100.0)
        f.addRow("Kalibrierwert [dB SPL @ 0 dBFS]", self.offset)
        self.lbl = QtWidgets.QLabel("")
        f.addRow(self.lbl)
        b_meas = QtWidgets.QPushButton("Messen (3 s)")
        b_meas.clicked.connect(self.measure)
        f.addRow(b_meas)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok
                                        | QtWidgets.QDialogButtonBox.Reset
                                        | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        bb.button(QtWidgets.QDialogButtonBox.Reset).setText("Kalibrierung löschen")
        bb.button(QtWidgets.QDialogButtonBox.Reset).clicked.connect(self._clear)
        f.addRow(bb)

    def measure(self) -> None:
        eng = self.state.engine
        if eng is None:
            self.lbl.setText("Audio ist nicht gestartet.")
            return
        self.lbl.setText("Messe …")
        QtWidgets.QApplication.processEvents()
        QtCore.QThread.msleep(3000)
        x = eng.ring.latest(int(eng.fs * 3), self.channel).astype(float)
        if np.sqrt(np.mean(x**2)) < 1e-5:
            self.lbl.setText("Kein Signal – Kalibrator eingeschaltet? Eingangsverstärkung?")
            return
        ref = float(self.ref.currentText().replace(",", "."))
        val = calibration_offset(x, ref)
        self.offset.setValue(val)
        self.lbl.setText(f"Gemessen: {20 * np.log10(np.sqrt(np.mean(x**2))):.1f} dBFS → "
                         f"Kalibrierwert {val:.2f} dB")

    def _ok(self) -> None:
        self.state.set_calibration(self.channel, self.offset.value())
        self.accept()

    def _clear(self) -> None:
        self.state.set_calibration(self.channel, None)
        self.accept()


class SPLView(QtWidgets.QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.meter: SPLMeter | None = None
        self.pos = 0
        self.tiles: dict[str, Tile] = {}
        self.selected = list(DEFAULT_TILES)
        self.log_file = None
        self.notes: list[tuple[float, str]] = []
        self.alarms: list[tuple[float, str, float]] = []
        self._alarm_state = 0
        self.note_lines: list = []
        self._build()
        name_controls(self)
        self.reset()
        self.timer = QtCore.QTimer(self, interval=100, timeout=self.process)
        state.engine_changed.connect(self._engine_changed)
        state.calibration_changed.connect(self.reset)

    # --- Sitzung ---------------------------------------------------------------
    def get_state(self) -> tuple[dict, dict]:
        meta = {"controls": controls_state(self), "tiles": self.selected,
                "notes": [[ts, text] for ts, text in self.notes]}
        arrays = {f"spl_hist_{k}": np.asarray(v, float) for k, v in self.hist.items()}
        return meta, arrays

    def set_state(self, meta: dict, arrays: dict) -> None:
        apply_controls_state(self, meta.get("controls", {}))
        self.selected = [t for t in meta.get("tiles", self.selected) if t in ALL_METRICS]
        self._rebuild_tiles()
        for line in self.note_lines:
            self.plot.removeItem(line)
        self.note_lines, self.notes = [], []
        self.notes_list.clear()
        for ts, text in meta.get("notes", []):
            self._add_note_entry(text, alarm=text.startswith("ALARM"), ts=float(ts))
        for k in self.hist:
            if f"spl_hist_{k}" in arrays:
                self.hist[k].clear()
                self.hist[k].extend(arrays[f"spl_hist_{k}"].tolist())
        self._update_history()

    # --- Aufbau --------------------------------------------------------------
    def _build(self) -> None:
        lay = QtWidgets.QHBoxLayout(self)
        left = QtWidgets.QVBoxLayout()
        self.main_value = QtWidgets.QLabel("–")
        self.main_value.setAlignment(QtCore.Qt.AlignCenter)
        self.main_value.setMinimumHeight(130)
        self.main_name = QtWidgets.QLabel("")
        self.main_name.setAlignment(QtCore.Qt.AlignCenter)
        self.main_name.setStyleSheet("font-size: 16px; color: #ccc;")
        left.addWidget(self.main_name)
        left.addWidget(self.main_value)
        self.cal_warning = QtWidgets.QLabel("")
        self.cal_warning.setStyleSheet("color: #ffaa33;")
        self.cal_warning.setAlignment(QtCore.Qt.AlignCenter)
        left.addWidget(self.cal_warning)
        self.grid = QtWidgets.QGridLayout()
        left.addLayout(self.grid)
        self.plot = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem(orientation="bottom")})
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.plot.setLabel("left", "dB")
        self.plot.addLegend(offset=(10, 10))
        self.c_aeq = self.plot.plot(name="LAeq 1 s", pen=pg.mkPen("#55aaff", width=1.5))
        self.c_ceq = self.plot.plot(name="LCeq 1 s", pen=pg.mkPen("#ff9944", width=1))
        self.c_a15 = self.plot.plot(name="LAeq 15 min", pen=pg.mkPen("#66dd66", width=2))
        self.l_warn = pg.InfiniteLine(angle=0, pen=pg.mkPen("#ffcc33", style=QtCore.Qt.DashLine))
        self.l_alarm = pg.InfiniteLine(angle=0, pen=pg.mkPen("#ff4444", style=QtCore.Qt.DashLine))
        self.plot.addItem(self.l_warn)
        self.plot.addItem(self.l_alarm)
        left.addWidget(self.plot, 1)
        lay.addLayout(left, 1)

        panel = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(panel)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        scroll.setFixedWidth(300)
        lay.addWidget(scroll)

        g = QtWidgets.QGroupBox("Messung")
        f = QtWidgets.QFormLayout(g)
        self.cb_ch = channel_combo(2, 0)
        self.cb_ch.currentIndexChanged.connect(self.reset)
        f.addRow("Kanal", self.cb_ch)
        b_cal = QtWidgets.QPushButton("Kalibrieren…")
        b_cal.clicked.connect(self.calibrate)
        b_reset = QtWidgets.QPushButton("Zurücksetzen (Leq, Max, Verlauf)")
        b_reset.clicked.connect(self.reset)
        f.addRow(b_cal)
        f.addRow(b_reset)
        self.cb_main = combo(ALL_METRICS, "LAeq 1 min")
        f.addRow("Hauptanzeige", self.cb_main)
        b_tiles = QtWidgets.QPushButton("Kennwerte auswählen…")
        b_tiles.clicked.connect(self.choose_tiles)
        f.addRow(b_tiles)
        self.cb_window = combo(["5 min", "15 min", "60 min", "4 h", "alles"], "15 min")
        f.addRow("Verlauf", self.cb_window)
        pl.addWidget(g)

        g = QtWidgets.QGroupBox("Ampel / Alarm (Hauptanzeige)")
        f = QtWidgets.QFormLayout(g)
        self.sp_warn = QtWidgets.QDoubleSpinBox(minimum=0, maximum=160, value=96, suffix=" dB")
        self.sp_alarm = QtWidgets.QDoubleSpinBox(minimum=0, maximum=160, value=100, suffix=" dB")
        self.chk_beep = QtWidgets.QCheckBox("Signalton bei Alarm")
        f.addRow("Gelb ab", self.sp_warn)
        f.addRow("Rot (Alarm) ab", self.sp_alarm)
        f.addRow(self.chk_beep)
        self.sp_warn.valueChanged.connect(lambda v: self.l_warn.setValue(v))
        self.sp_alarm.valueChanged.connect(lambda v: self.l_alarm.setValue(v))
        self.l_warn.setValue(96)
        self.l_alarm.setValue(100)
        pl.addWidget(g)

        g = QtWidgets.QGroupBox("Protokoll & Notizen")
        v = QtWidgets.QVBoxLayout(g)
        self.btn_log = QtWidgets.QPushButton("Protokoll starten (CSV)…")
        self.btn_log.setCheckable(True)
        self.btn_log.toggled.connect(self.toggle_log)
        v.addWidget(self.btn_log)
        self.ed_note = QtWidgets.QLineEdit(placeholderText="Ereignis-Notiz, z. B. „Band startet“")
        self.ed_note.returnPressed.connect(self.add_note)
        b_note = QtWidgets.QPushButton("Notiz setzen")
        b_note.clicked.connect(self.add_note)
        v.addWidget(self.ed_note)
        v.addWidget(b_note)
        self.notes_list = QtWidgets.QListWidget()
        v.addWidget(self.notes_list)
        b_rep = QtWidgets.QPushButton("Bericht erstellen (HTML)…")
        b_rep.clicked.connect(self.report)
        v.addWidget(b_rep)
        pl.addWidget(g, 1)
        self._rebuild_tiles()

    def _rebuild_tiles(self) -> None:
        for t in self.tiles.values():
            t.setParent(None)
        self.tiles = {}
        for i, name in enumerate(self.selected):
            t = Tile(name)
            self.tiles[name] = t
            self.grid.addWidget(t, i // 5, i % 5)

    def choose_tiles(self) -> None:
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Kennwerte auswählen")
        v = QtWidgets.QVBoxLayout(dlg)
        lst = QtWidgets.QListWidget()
        for m in ALL_METRICS:
            it = QtWidgets.QListWidgetItem(m)
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Checked if m in self.selected else QtCore.Qt.Unchecked)
            lst.addItem(it)
        v.addWidget(lst)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        if dlg.exec():
            self.selected = [lst.item(i).text() for i in range(lst.count())
                             if lst.item(i).checkState() == QtCore.Qt.Checked]
            self._rebuild_tiles()

    # --- Engine / Messung ------------------------------------------------------
    def _engine_changed(self, engine) -> None:
        set_channel_count(self.cb_ch, self.state.input_channels)
        if engine is None:
            self.timer.stop()
            return
        self.reset()
        self.timer.start()

    def reset(self) -> None:
        ch = self.cb_ch.currentData() or 0
        cal = self.state.calibration_for(ch)
        self.cal_warning.setText("" if cal is not None else
                                 "Nicht kalibriert – Werte in dBFS (re. Vollaussteuerung)")
        # Bewertungsfilter erst bei laufendem Audio entwerfen (lädt scipy – nicht schon beim Programmstart)
        self.meter = SPLMeter(self.state.fs, cal if cal is not None else 0.0) if self.state.engine else None
        self.pos = self.state.engine.ring.total if self.state.engine else 0
        self.sec_energy = {"A": 0.0, "C": 0.0}
        self.sec_samples = 0
        self.sec_peak = -np.inf
        self.sec_laf_max = -np.inf
        self.rolling = {c: collections.deque(maxlen=900) for c in ("A", "C")}
        self.hist = {k: collections.deque(maxlen=HISTORY_MAX) for k in ("t", "A", "C", "A15")}
        self.values: dict[str, float] = {}

    def process(self) -> None:
        eng = self.state.engine
        if eng is None or self.meter is None:
            return
        ch = self.cb_ch.currentData() or 0
        data, self.pos = eng.ring.since(self.pos)
        if not len(data) or ch >= data.shape[1]:
            return
        x = data[:, ch].astype(float)
        fs = eng.fs
        # in 100-ms-Stücke teilen, damit Sekundenwerte sauber getrennt werden
        for chunk in np.array_split(x, max(1, len(x) // int(fs * 0.1))):
            cur = self.meter.process(chunk)
            for c in ("A", "C"):
                self.sec_energy[c] += self.meter.block_energy[c] * len(chunk)
            self.sec_samples += len(chunk)
            self.sec_peak = max(self.sec_peak, cur["LCpeak"])
            self.sec_laf_max = max(self.sec_laf_max, cur["LAF"])
            if self.sec_samples >= fs:
                self._second_done()
        self.values.update(self.meter.current)
        self._update_display()

    def _second_done(self) -> None:
        cal = self.meter.cal_db
        now = time.time()
        for c in ("A", "C"):
            self.rolling[c].append(self.sec_energy[c] / self.sec_samples)
        for name, (c, n) in ROLLING.items():
            vals = list(self.rolling[c])[-n:]
            self.values[name] = 10 * np.log10(np.mean(vals) + 1e-20) + cal
        self.hist["t"].append(now)
        self.hist["A"].append(self.values["LAeq 1 s"])
        self.hist["C"].append(self.values["LCeq 1 s"])
        self.hist["A15"].append(self.values["LAeq 15 min"])
        if self.log_file is not None:
            self.log_file.write(";".join([
                dt.datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S"),
                *(f"{v:.1f}".replace(".", ",") for v in (
                    self.values["LAeq 1 s"], self.values["LCeq 1 s"], self.sec_laf_max,
                    self.meter.current["LAS"], self.sec_peak,
                    self.values["LAeq 1 min"], self.values["LAeq 15 min"])),
                ""]) + "\n")
            self.log_file.flush()
        self.sec_energy = {"A": 0.0, "C": 0.0}
        self.sec_samples = 0
        self.sec_peak = -np.inf
        self.sec_laf_max = -np.inf
        self._update_history()

    def _update_display(self) -> None:
        name = self.cb_main.currentText()
        v = self.values.get(name)
        self.main_name.setText(name + (" [dB]" if self.cal_warning.text() == "" else " [dBFS]"))
        color = "#66dd66"
        state = 0
        if v is not None and np.isfinite(v):
            if v >= self.sp_alarm.value():
                color, state = "#ff4444", 2
            elif v >= self.sp_warn.value():
                color, state = "#ffcc33", 1
        self.main_value.setText("–" if v is None or not np.isfinite(v) else f"{v:.1f}")
        self.main_value.setStyleSheet(f"font-size: 96px; font-weight: bold; color: {color};")
        if state == 2 and self._alarm_state < 2:
            self.alarms.append((time.time(), name, v))
            self._add_note_entry(f"ALARM: {name} = {v:.1f} dB", alarm=True)
            if self.chk_beep.isChecked():
                QtWidgets.QApplication.beep()
        self._alarm_state = state
        for n, tile in self.tiles.items():
            tile.set(self.values.get(n))

    def _update_history(self) -> None:
        if not self.hist["t"]:
            return
        t = np.array(self.hist["t"])
        win = self.cb_window.currentText()
        span = {"5 min": 300, "15 min": 900, "60 min": 3600, "4 h": 14400}.get(win)
        sel = t >= t[-1] - span if span else slice(None)
        self.c_aeq.setData(t[sel], np.array(self.hist["A"])[sel])
        self.c_ceq.setData(t[sel], np.array(self.hist["C"])[sel])
        self.c_a15.setData(t[sel], np.array(self.hist["A15"])[sel])

    # --- Kalibrierung, Protokoll, Notizen, Bericht -------------------------------
    def calibrate(self) -> None:
        CalibrationDialog(self.state, self.cb_ch.currentData() or 0, self).exec()

    def toggle_log(self, on: bool) -> None:
        if on:
            name = f"pegelprotokoll_{dt.datetime.now():%Y%m%d_%H%M%S}.csv"
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Protokoll speichern", name, "CSV (*.csv)")
            if not path:
                self.btn_log.setChecked(False)
                return
            self.log_file = open(path, "w", encoding="utf-8-sig")
            self.log_file.write("Zeit;LAeq 1s;LCeq 1s;LAFmax 1s;LAS;LCpeak 1s;LAeq 1min;LAeq 15min;Notiz\n")
            self.btn_log.setText(f"Protokoll läuft: {os.path.basename(path)} (stoppen)")
        else:
            if self.log_file is not None:
                self.log_file.close()
                self.log_file = None
            self.btn_log.setText("Protokoll starten (CSV)…")

    def add_note(self) -> None:
        text = self.ed_note.text().strip()
        if text:
            self._add_note_entry(text)
            self.ed_note.clear()

    def add_note_text(self, text: str) -> None:
        """Notiz von außen (z. B. Fernbedienung) setzen."""
        self._add_note_entry(text)

    def _add_note_entry(self, text: str, alarm: bool = False, ts: float | None = None) -> None:
        now = time.time() if ts is None else ts
        self.notes.append((now, text))
        self.notes_list.addItem(f"{dt.datetime.fromtimestamp(now):%H:%M:%S}  {text}")
        line = pg.InfiniteLine(pos=now, angle=90, label=text[:30],
                               pen=pg.mkPen("#ff4444" if alarm else "#cccccc", style=QtCore.Qt.DotLine),
                               labelOpts={"position": 0.95, "color": "#ccc"})
        self.plot.addItem(line)
        self.note_lines.append(line)
        if self.log_file is not None and ts is None:
            self.log_file.write(f"{dt.datetime.fromtimestamp(now):%Y-%m-%d %H:%M:%S};;;;;;;;"
                                f"{text.replace(';', ',')}\n")

    def report(self) -> None:
        if not self.hist["t"]:
            QtWidgets.QMessageBox.information(self, "Bericht", "Noch keine Messdaten vorhanden.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Bericht speichern", f"pegelbericht_{dt.datetime.now():%Y%m%d_%H%M}.html", "HTML (*.html)")
        if not path:
            return
        tmp = os.path.join(tempfile.gettempdir(), "akustikmess_verlauf.png")
        exp = pg.exporters.ImageExporter(self.plot.plotItem)
        exp.parameters()["width"] = 1400
        exp.export(tmp)
        with open(tmp, "rb") as fh:
            img = base64.b64encode(fh.read()).decode()
        t = np.array(self.hist["t"])
        a = np.array(self.hist["A"])
        cal = "kalibriert" if self.cal_warning.text() == "" else "NICHT kalibriert (dBFS)"
        rows = [
            ("Beginn", dt.datetime.fromtimestamp(t[0]).strftime("%d.%m.%Y %H:%M:%S")),
            ("Ende", dt.datetime.fromtimestamp(t[-1]).strftime("%d.%m.%Y %H:%M:%S")),
            ("Dauer", str(dt.timedelta(seconds=int(t[-1] - t[0] + 1)))),
            ("Kalibrierung", cal),
            ("LAeq gesamt", f"{self.values.get('LAeq', float('nan')):.1f} dB"),
            ("LCeq gesamt", f"{self.values.get('LCeq', float('nan')):.1f} dB"),
            ("LAFmax", f"{self.values.get('LAFmax', float('nan')):.1f} dB"),
            ("LCpeak max", f"{self.values.get('LCpeakmax', float('nan')):.1f} dB"),
            ("Höchster LAeq 15 min", f"{np.nanmax(self.hist['A15']):.1f} dB"),
            (f"Zeit mit LAeq 1 s ≥ {self.sp_warn.value():.0f} dB",
             str(dt.timedelta(seconds=int(np.sum(a >= self.sp_warn.value()))))),
            (f"Zeit mit LAeq 1 s ≥ {self.sp_alarm.value():.0f} dB",
             str(dt.timedelta(seconds=int(np.sum(a >= self.sp_alarm.value()))))),
        ]
        notes = "".join(f"<tr><td>{dt.datetime.fromtimestamp(ts):%H:%M:%S}</td><td>{html.escape(n)}</td></tr>"
                        for ts, n in self.notes) or "<tr><td colspan=2>keine</td></tr>"
        doc = f"""<!doctype html><html lang="de"><meta charset="utf-8"><title>Pegelbericht</title>
<style>body{{font-family:Segoe UI,Helvetica,Arial,sans-serif;max-width:1000px;margin:24px auto;color:#222}}
table{{border-collapse:collapse;margin:12px 0}}td,th{{border:1px solid #ccc;padding:4px 10px;text-align:left}}
img{{max-width:100%;border:1px solid #ccc}}</style>
<h1>Pegelbericht</h1><p>Erstellt mit AkustikMess am {dt.datetime.now():%d.%m.%Y %H:%M}</p>
<h2>Zusammenfassung</h2><table>{''.join(f'<tr><th>{k}</th><td>{v}</td></tr>' for k, v in rows)}</table>
<h2>Pegelverlauf</h2><img src="data:image/png;base64,{img}" alt="Pegelverlauf">
<h2>Ereignisse und Alarme</h2><table><tr><th>Zeit</th><th>Notiz</th></tr>{notes}</table></html>"""
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(doc)
        QtWidgets.QMessageBox.information(self, "Bericht", f"Bericht gespeichert:\n{path}")
