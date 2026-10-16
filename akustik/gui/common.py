"""Gemeinsame GUI-Bausteine: Frequenzachse, Plot-Fabrik, Messkurven-Speicher."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

FREQ_TICKS = [20, 31.5, 50, 63, 100, 125, 200, 250, 500, 1000, 2000, 4000, 5000, 8000, 10000, 16000, 20000]
FREQ_MAJOR = [20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000]

# Rot (Live-Übertragung) und Blau (Live-Spektrum) bewusst nicht am Anfang
TRACE_COLORS = ["#66dd66", "#ffcc33", "#dd77ff", "#33dddd", "#ff9944", "#ff88cc", "#ffffff", "#a0a0ff"]


def fmt_freq(f: float) -> str:
    if f >= 1000:
        v = f / 1000
        return f"{v:g}k"
    return f"{f:g}"


class FreqAxis(pg.AxisItem):
    """Logarithmische Frequenzachse mit Beschriftung 20, 50, 100 … 20k."""

    def tickValues(self, minVal, maxVal, size):
        if not self.logMode:
            return super().tickValues(minVal, maxVal, size)
        # nur Hauptlinien: jede Gitterlinie kostet bei jedem Neuzeichnen Zeit
        major = [np.log10(f) for f in FREQ_MAJOR if minVal <= np.log10(f) <= maxVal]
        if len(major) < 4:  # stark hineingezoomt → feinere Teilung
            major = [np.log10(d * m) for d in (1, 10, 100, 1000, 10000) for m in range(1, 10)
                     if minVal <= np.log10(d * m) <= maxVal]
        return [(1.0, major)]

    def tickStrings(self, values, scale, spacing):
        if not self.logMode:
            return super().tickStrings(values, scale, spacing)
        return [fmt_freq(round(10**v)) if spacing >= 1.0 else "" for v in values]

    def logTickStrings(self, values, scale, spacing):
        return self.tickStrings(values, scale, spacing)


LIVE_CURSOR_MS = 150   # Aktualisierung der Fadenkreuz-Werte bei ruhender Maus (~7 pro Sekunde)


class CursorGroup:
    """Verbindet mehrere Fadenkreuze: die senkrechte Linie folgt in allen Plots."""

    def __init__(self):
        self.members: list[FreqCursor] = []

    def show_freq(self, source: "FreqCursor", f: float | None) -> None:
        for m in self.members:
            if m is not source:
                m.show_vline(f)


class FreqCursor(QtCore.QObject):
    """Fadenkreuz mit genauer Frequenz, Note (± Cent) und Messwert unter der Maus.

    ``freq_axis`` ist "x" (Frequenzplots) oder "y" (Spektrogramm).
    ``value_fn(f)`` kann einen Text mit dem Kurvenwert bei Frequenz f liefern.
    """

    def __init__(self, plot: pg.PlotWidget, state, freq_axis: str = "x", unit: str = "dB",
                 value_fn=None, group: CursorGroup | None = None):
        super().__init__(plot)
        self.plot, self.state, self.freq_axis, self.unit = plot, state, freq_axis, unit
        self.value_fn = value_fn
        self.group = group
        if group is not None:
            group.members.append(self)
        self.vb = plot.getPlotItem().getViewBox()
        pen = pg.mkPen((255, 255, 255, 140), style=QtCore.Qt.DashLine)
        self.vline = pg.InfiniteLine(angle=90, movable=False, pen=pen)
        self.hline = pg.InfiniteLine(angle=0, movable=False, pen=pen)
        for item in (self.vline, self.hline):
            item.setZValue(1000)
            plot.addItem(item, ignoreBounds=True)
            item.hide()
        # Beschriftung als Overlay in Bildschirm-Pixeln (unabhängig von der log. Achse)
        self.label = QtWidgets.QLabel(plot)
        self.label.setTextFormat(QtCore.Qt.RichText)
        self.label.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.label.setStyleSheet("background: rgba(20,22,26,235); color: #fff; border: 1px solid #777;"
                                 "border-radius: 3px; padding: 4px 6px;")
        self.label.hide()
        # Mausbewegungen bündeln: höchstens ~60 Aktualisierungen pro Sekunde,
        # immer mit der neuesten Position (verhindert Rückstau beim schnellen Bewegen)
        self._pending = None
        self._throttle = QtCore.QTimer(self, singleShot=True, interval=16, timeout=self._flush)
        self._last_f = None
        # Live-Anzeige: steht die Maus still im Diagramm, Messwert trotzdem laufend aktualisieren
        self._last_pos = None
        self._live = QtCore.QTimer(self, interval=LIVE_CURSOR_MS, timeout=self._refresh)
        plot.scene().sigMouseMoved.connect(self._queue)
        plot.installEventFilter(self)

    def _queue(self, pos) -> None:
        self._pending = pos
        if not self._throttle.isActive():
            self._throttle.start()

    def _flush(self) -> None:
        if self._pending is not None:
            pos, self._pending = self._pending, None
            self._moved(pos)

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Leave:
            self._pending = None
            self._hide()
        return False

    def _refresh(self) -> None:
        if self._last_pos is None or not self.label.isVisible() or not self.plot.isVisible():
            self._live.stop()
            return
        self._moved(self._last_pos)

    def _hide(self) -> None:
        self._last_pos = None
        self._live.stop()
        if not (self.vline.isVisible() or self.label.isVisible()):
            return
        for item in (self.vline, self.hline, self.label):
            item.hide()
        if self.group:
            self.group.show_freq(self, None)

    def show_vline(self, f: float | None) -> None:
        """Nur die senkrechte Linie zeigen (von einem verbundenen Plot ausgelöst)."""
        if self.hline.isVisible():
            self.hline.hide()
        if self.label.isVisible():
            self.label.hide()
        if f is None or self.freq_axis != "x":
            if self.vline.isVisible():
                self.vline.hide()
            return
        self.vline.setPos(np.log10(f))
        if not self.vline.isVisible():
            self.vline.show()

    def _moved(self, pos) -> None:
        if not self.plot.isVisible() or not self.vb.sceneBoundingRect().contains(pos):
            self._hide()
            return
        p = self.vb.mapSceneToView(pos)
        x, y = p.x(), p.y()
        f = 10 ** (x if self.freq_axis == "x" else y)
        other = y if self.freq_axis == "x" else x
        from ..dsp.notes import format_freq, format_note  # noqa: PLC0415
        lines = [f"<b style='font-size:14px'>{format_freq(f)}</b>",
                 format_note(f, self.state.a4, self.state.note_naming)]
        if self.value_fn is not None:
            v = self.value_fn(f)
            if v:
                lines.append(v)
        lines.append(f"<span style='color:#999'>Cursor: {other:.2f} {self.unit}</span>")
        self.label.setText("<br>".join(lines))
        self.label.adjustSize()
        # zur Plotmitte hin ausrichten, damit die Beschriftung nicht aus dem Bild ragt
        wp = self.plot.mapFromScene(pos)
        w, h = self.label.width(), self.label.height()
        lx = wp.x() - w - 12 if wp.x() > self.plot.width() / 2 else wp.x() + 12
        ly = wp.y() + 12 if wp.y() < self.plot.height() / 2 else wp.y() - h - 12
        self.label.move(int(max(0, lx)), int(max(0, ly)))
        self.vline.setPos(x)
        self.hline.setPos(y)
        for item in (self.vline, self.hline, self.label):
            if not item.isVisible():
                item.show()
        self.label.raise_()
        self._last_pos = pos
        if not self._live.isActive():
            self._live.start()
        if self.group and self.freq_axis == "x":
            self.group.show_freq(self, f)


def log_decimate(f: np.ndarray, points: int = 1500, **series):
    """Reduziert Kurvendaten für die logarithmische Frequenzachse.

    Teilt die Achse in ``points`` gleich breite log-Abschnitte. Im Tiefenbereich
    (weniger als ein Bin pro Abschnitt) bleiben alle Punkte erhalten, oben werden
    viele Bins zu einem Punkt zusammengefasst. Je Datenreihe wählbar:
    ``("max", y)`` Spitzenwert (Spektrum), ``("mean", y)`` Mittelwert,
    ``("phase", y_deg)`` Kreismittel für Phasen.
    Liefert (f_neu, {name: y_neu}).
    """
    n = len(f)
    if n <= points:
        return f, {k: y for k, (_, y) in series.items()}
    lf = np.log10(f)
    starts = np.unique(np.searchsorted(lf, np.linspace(lf[0], lf[-1], points + 1)))
    starts = starts[starts < n]
    counts = np.diff(np.append(starts, n))
    centers = np.minimum(starts + counts // 2, n - 1)
    out = {}
    for name, (mode, y) in series.items():
        if mode == "max":
            out[name] = np.maximum.reduceat(y, starts)
        elif mode == "phase":
            z = np.add.reduceat(np.exp(1j * np.radians(y)), starts)
            out[name] = np.degrees(np.angle(z))
        else:
            out[name] = np.add.reduceat(y, starts) / counts
    return f[centers], out


def curve_value(freqs: np.ndarray | None, values: np.ndarray | None, f: float,
                stepped: bool = False) -> float | None:
    """Kurvenwert bei Frequenz f (Bänder: Wert des Bandes, sonst log-Interpolation)."""
    if freqs is None or values is None or len(values) == 0:
        return None
    if stepped:  # freqs sind Bandgrenzen
        i = np.searchsorted(freqs, f) - 1
        return float(values[i]) if 0 <= i < len(values) else None
    if f < freqs[0] or f > freqs[-1]:
        return None
    return float(np.interp(np.log10(f), np.log10(freqs), values))


GRID_PEN = (62, 66, 74)


GRID_X_SPAN = (np.log10(5), np.log10(48000))   # entspricht den Zoom-Grenzen der Frequenzachse


def add_static_grid(w: pg.PlotWidget, y_step: float, y_span=(-300, 300)) -> pg.PlotCurveItem:
    """Gitter als **ein** Linienobjekt (Segmentpaare) statt hunderter Einzellinien.

    Schneller aufgebaut und gezeichnet als ``showGrid`` (malt bei jeder Aktualisierung die ganze Fläche)
    und als einzelne ``InfiniteLine``-Objekte (je Linie ein eigenes Zeichenobjekt).
    """
    xs = [np.log10(f) for f in FREQ_MAJOR]
    ys = np.arange(y_span[0], y_span[1] + y_step / 2, y_step)
    px, py = [], []
    for x in xs:
        px += [x, x]
        py += [y_span[0], y_span[1]]
    for y in ys:
        px += [GRID_X_SPAN[0], GRID_X_SPAN[1]]
        py += [y, y]
    grid = pg.PlotCurveItem(np.array(px), np.array(py), pen=pg.mkPen(GRID_PEN), connect="pairs")
    grid.setZValue(-100)
    w.addItem(grid, ignoreBounds=True)
    return grid


def freq_plot(title: str = "", y_label: str = "dB", y_range=(-100, 0),
              y_grid: float = 10.0, y_span=(-300, 300)) -> pg.PlotWidget:
    w = pg.PlotWidget(axisItems={"bottom": FreqAxis(orientation="bottom")})
    w.setLogMode(x=True, y=False)
    w.setXRange(np.log10(20), np.log10(20000), padding=0)
    w.setYRange(*y_range, padding=0)
    add_static_grid(w, y_grid, y_span)
    w.setLabel("left", y_label)
    if title:
        w.setTitle(title)
    w.setMouseEnabled(x=True, y=True)
    w.getPlotItem().getViewBox().setLimits(xMin=np.log10(5), xMax=np.log10(48000))
    return w


def time_plot(title: str = "", y_label: str = "", x_label: str = "Zeit [s]") -> pg.PlotWidget:
    w = pg.PlotWidget()
    w.showGrid(x=True, y=True, alpha=0.25)
    w.setLabel("bottom", x_label)
    if y_label:
        w.setLabel("left", y_label)
    if title:
        w.setTitle(title)
    return w


class TraceStore(QtWidgets.QWidget):
    """Liste gespeicherter Messkurven (wie ein Datenregister) mit Ein-/Ausblenden."""

    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.traces: list[dict] = []
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.list = QtWidgets.QListWidget()
        self.list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)  # Strg/Umschalt
        self.list.setToolTip("Doppelklick: umbenennen (z. B. Messposition) · Strg+Klick: mehrere wählen")
        self.list.itemChanged.connect(self._item_changed)
        lay.addWidget(self.list)
        row = QtWidgets.QHBoxLayout()
        self.btn_delete = QtWidgets.QPushButton("Löschen")
        self.btn_save = QtWidgets.QPushButton("Exportieren…")
        self.btn_delete.clicked.connect(self.delete_selected)
        self.btn_save.clicked.connect(self.export_selected)
        row.addWidget(self.btn_delete)
        row.addWidget(self.btn_save)
        lay.addLayout(row)

    ARRAY_KEYS = ("freqs", "mag", "phase", "coh")

    def add(self, name: str, data: dict, color: str | None = None, visible: bool = True,
            emit: bool = True) -> dict:
        color = color or TRACE_COLORS[len(self.traces) % len(TRACE_COLORS)]
        trace = {**data, "name": name, "color": color, "visible": visible}
        self.traces.append(trace)
        item = QtWidgets.QListWidgetItem(name)
        item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEditable)
        self.list.blockSignals(True)
        item.setCheckState(QtCore.Qt.Checked if visible else QtCore.Qt.Unchecked)
        pix = QtGui.QPixmap(12, 12)
        pix.fill(QtGui.QColor(color))
        item.setIcon(QtGui.QIcon(pix))
        self.list.addItem(item)
        self.list.blockSignals(False)
        if emit:
            self.changed.emit()
        return trace

    def clear(self) -> None:
        self.traces = []
        self.list.clear()
        self.changed.emit()

    def selected(self, kind: str | None = None) -> list[dict]:
        rows = sorted(self.list.row(it) for it in self.list.selectedItems())
        return [self.traces[r] for r in rows if kind is None or self.traces[r].get("kind") == kind]

    def of_kind(self, kind: str) -> list[dict]:
        return [t for t in self.traces if t.get("kind") == kind]

    # --- Sitzung ---------------------------------------------------------------
    def to_session(self, prefix: str) -> tuple[list[dict], dict]:
        meta, arrays = [], {}
        for i, t in enumerate(self.traces):
            meta.append({k: v for k, v in t.items() if k not in self.ARRAY_KEYS})
            for k in self.ARRAY_KEYS:
                if t.get(k) is not None:
                    arrays[f"{prefix}{i}_{k}"] = np.asarray(t[k])
        return meta, arrays

    def from_session(self, prefix: str, meta: list[dict], arrays: dict) -> None:
        self.traces = []
        self.list.clear()
        for i, m in enumerate(meta):
            data = {k: v for k, v in m.items() if k not in ("name", "color", "visible")}
            for k in self.ARRAY_KEYS:
                if f"{prefix}{i}_{k}" in arrays:
                    data[k] = arrays[f"{prefix}{i}_{k}"]
            self.add(m["name"], data, m.get("color"), m.get("visible", True), emit=False)
        self.changed.emit()

    def _item_changed(self, item):
        i = self.list.row(item)
        if 0 <= i < len(self.traces):
            self.traces[i]["visible"] = item.checkState() == QtCore.Qt.Checked
            self.traces[i]["name"] = item.text()
            self.changed.emit()

    def delete_selected(self):
        # von hinten nach vorn, sonst verschieben sich die Positionen beim Löschen
        for i in sorted((self.list.row(it) for it in self.list.selectedItems()), reverse=True):
            self.list.takeItem(i)
            self.traces.pop(i)
        self.changed.emit()

    def export_selected(self):
        items = self.list.selectedItems() or [self.list.item(i) for i in range(self.list.count())]
        if not items:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Messkurven exportieren", "messkurven.csv", "CSV (*.csv)")
        if not path:
            return
        cols, header = [], []
        for item in items:
            t = self.traces[self.list.row(item)]
            for key in ("freqs", "mag", "phase", "coh"):
                if key in t and t[key] is not None:
                    cols.append(np.asarray(t[key], float))
                    header.append(f"{t['name']} {key}")
        n = max(len(c) for c in cols)
        arr = np.full((n, len(cols)), np.nan)
        for i, c in enumerate(cols):
            arr[: len(c), i] = c
        np.savetxt(path, arr, delimiter=";", header=";".join(header), comments="", fmt="%.6g")


def labeled(form: QtWidgets.QFormLayout, label: str, widget: QtWidgets.QWidget) -> QtWidgets.QWidget:
    form.addRow(label, widget)
    return widget


def combo(items, current=None) -> QtWidgets.QComboBox:
    c = QtWidgets.QComboBox()
    for it in items:
        c.addItem(str(it), it)
    if current is not None:
        idx = c.findData(current)
        if idx >= 0:
            c.setCurrentIndex(idx)
    return c


def channel_combo(n: int, current: int = 0, allow_none: bool = False) -> QtWidgets.QComboBox:
    c = QtWidgets.QComboBox()
    if allow_none:
        c.addItem("keiner", -1)
    for i in range(n):
        c.addItem(f"Eingang {i + 1}", i)
    idx = c.findData(current)
    c.setCurrentIndex(max(0, idx))
    return c


def set_channel_count(c: QtWidgets.QComboBox, n: int, prefix: str = "Eingang") -> None:
    cur = c.currentData()
    allow_none = c.count() and c.itemData(0) == -1
    c.blockSignals(True)
    c.clear()
    if allow_none:
        c.addItem("keiner", -1)
    for i in range(n):
        c.addItem(f"{prefix} {i + 1}", i)
    idx = c.findData(cur)
    c.setCurrentIndex(idx if idx >= 0 else 0)
    c.blockSignals(False)
