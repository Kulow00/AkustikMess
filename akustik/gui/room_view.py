"""Raum-Modus: Lautsprecher im Raum, Pegelkarte der Hörfläche, Messpunkte (Messung ↔ Vorhersage)."""

from __future__ import annotations

import copy
import math

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from ..dsp import roommodel as rm
from .session import apply_controls_state, controls_state, name_controls
from .state import AppState

# Farbskala ähnlich üblicher Planungsprogramme: leise blau → laut rot
CMAP = pg.ColorMap(np.array([0.0, 0.2, 0.4, 0.6, 0.8, 1.0]),
                   np.array([(20, 30, 110), (30, 110, 230), (40, 200, 200), (90, 210, 60),
                             (250, 220, 40), (230, 40, 30)], dtype=np.ubyte))
BAND_A = "Breitband (A-bewertet)"

# Spalten der Lautsprecher-Tabelle: (Attribut, Überschrift, Art)
COLUMNS = [("enabled", "An", "bool"), ("name", "Name", "str"), ("kind", "Typ", "kind"),
           ("x", "X [m]", "float"), ("y", "Y [m]", "float"), ("z", "Höhe [m]", "float"),
           ("azimuth", "Richtung [°]", "float"), ("tilt", "Neigung [°]", "float"),
           ("level", "Pegel @1 m [dB]", "float"), ("delay_ms", "Delay [ms]", "float"),
           ("polarity", "Polarität", "pol"), ("cov_h", "Öffnung H [°]", "float"),
           ("cov_v", "Öffnung V [°]", "float"), ("f_low", "Hochpass [Hz]", "float"),
           ("f_high", "Tiefpass [Hz]", "float")]


def example_setup(room: rm.Room) -> list[rm.Speaker]:
    w = room.width
    return [rm.Speaker.top("Top L", x=1.5, y=0.5, z=3.0, azimuth=12, tilt=-5, f_low=100),
            rm.Speaker.top("Top R", x=w - 1.5, y=0.5, z=3.0, azimuth=-12, tilt=-5, f_low=100),
            *rm.sub_setup("L/R-Stacks", room, count=2, y=0.5)]


class _Worker(QtCore.QThread):
    done = QtCore.Signal(int, object)

    def __init__(self, job_id, room, speakers, band, fraction):
        super().__init__()
        self.args = (job_id, copy.deepcopy(room), copy.deepcopy(speakers), band, fraction)

    def run(self) -> None:
        job_id, room, speakers, band, fraction = self.args
        try:
            self.done.emit(job_id, rm.level_map(room, speakers, band, fraction))
        except Exception as exc:  # noqa: BLE001
            self.done.emit(job_id, exc)


class RoomView(QtWidgets.QWidget):
    def __init__(self, state: AppState, realtime=None, parent=None):
        super().__init__(parent)
        self.state, self.realtime = state, realtime
        self.room = rm.Room()
        self.speakers: list[rm.Speaker] = example_setup(self.room)
        self.points: list[rm.MeasPoint] = []
        self.map = None                 # (xs, ys, levels)
        self._job = 0
        self._workers: list[_Worker] = []
        self._placing = False
        self._build()
        self._recalc = QtCore.QTimer(self, singleShot=True, interval=120, timeout=self.compute)
        self._fill_room_spins()
        self._fill_table()
        self.schedule()

    # --- Aufbau -------------------------------------------------------------------
    def _build(self) -> None:
        lay = QtWidgets.QHBoxLayout(self)
        left = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self.plot = pg.PlotWidget()
        self.plot.setAspectLocked(True)
        self.plot.getViewBox().invertY(True)          # Bühne oben, wie auf einem Plan
        self.plot.setLabel("bottom", "Breite x [m]")
        self.plot.setLabel("left", "Tiefe y [m] (0 = Bühnenkante)")
        self.plot.showGrid(x=True, y=True, alpha=0.15)
        self.img = pg.ImageItem(axisOrder="row-major")
        self.img.setZValue(-10)
        self.plot.addItem(self.img)
        self.cbar = pg.ColorBarItem(values=(70, 100), colorMap=CMAP, interactive=False, label="dB SPL")
        self.cbar.setImageItem(self.img, insert_in=self.plot.getPlotItem())
        self.outline = pg.PlotDataItem(pen=pg.mkPen("#ddd", width=2))
        self.stage = pg.PlotDataItem(pen=pg.mkPen("#ffcc33", width=3, style=QtCore.Qt.DashLine))
        self.plot.addItem(self.outline)
        self.plot.addItem(self.stage)
        self.pts_item = pg.ScatterPlotItem(size=11, symbol="o", pen=pg.mkPen("k", width=1.5),
                                           brush=pg.mkBrush("#ffffff"))
        self.pts_item.setZValue(20)
        self.plot.addItem(self.pts_item)
        self.spk_items: list = []
        self.pt_labels: list = []
        self.hover = QtWidgets.QLabel(self.plot)
        self.hover.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.hover.setStyleSheet("background: rgba(20,22,26,230); color: #fff; padding: 3px 6px; border-radius: 3px;")
        self.hover.hide()
        self.plot.scene().sigMouseMoved.connect(self._mouse_moved)
        self.plot.scene().sigMouseClicked.connect(self._mouse_clicked)
        left.addWidget(self.plot)

        box = QtWidgets.QWidget()
        bl = QtWidgets.QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        row = QtWidgets.QHBoxLayout()
        for text, slot in (("+ Top", lambda: self.add_speaker("top")), ("+ Sub", lambda: self.add_speaker("sub")),
                           ("Duplizieren", self.duplicate_speaker), ("Entfernen", self.remove_speaker)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(QtWidgets.QLabel("Lautsprecher auch in der Karte mit der Maus verschiebbar."))
        bl.addLayout(row)
        self.table = QtWidgets.QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([c[1] for c in COLUMNS])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.itemChanged.connect(self._table_changed)
        bl.addWidget(self.table)
        left.addWidget(box)
        left.setSizes([620, 230])
        lay.addWidget(left, 1)

        panel = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(panel)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        scroll.setFixedWidth(320)
        lay.addWidget(scroll)

        def spin(lo, hi, val, suffix, step=0.5, dec=2):
            s = QtWidgets.QDoubleSpinBox(minimum=lo, maximum=hi, value=val, decimals=dec, singleStep=step,
                                         suffix=suffix)
            s.setKeyboardTracking(False)
            return s

        g = QtWidgets.QGroupBox("Raum")
        f = QtWidgets.QFormLayout(g)
        self.sp_len = spin(2, 300, 20, " m")
        self.sp_wid = spin(2, 300, 14, " m")
        self.sp_hei = spin(2, 60, 6, " m")
        self.sp_lis = spin(0, 20, 1.2, " m", 0.1)
        self.sp_res = spin(0.1, 2, 0.25, " m", 0.05)
        self.sp_stage = spin(0, 30, 5, " m", 0.5)
        self.sp_stage.setToolTip("Bühnenbereich hinter der Bühnenkante – zeigt, wie viel Pegel auf der Bühne ankommt")
        f.addRow("Länge (Tiefe)", self.sp_len)
        f.addRow("Breite", self.sp_wid)
        f.addRow("Höhe", self.sp_hei)
        f.addRow("Hörhöhe", self.sp_lis)
        f.addRow("Bühnentiefe", self.sp_stage)
        f.addRow("Raster", self.sp_res)
        for s in (self.sp_len, self.sp_wid, self.sp_hei, self.sp_lis, self.sp_res, self.sp_stage):
            s.valueChanged.connect(self._room_changed)
        pl.addWidget(g)

        g = QtWidgets.QGroupBox("Anzeige")
        f = QtWidgets.QFormLayout(g)
        self.cb_res = QtWidgets.QComboBox()
        self.cb_res.addItems(["Oktaven", "Terzen"])
        self.cb_band = QtWidgets.QComboBox()
        self.sp_range = spin(6, 60, 24, " dB", 3, 0)
        self.sp_offset = spin(-60, 60, 0, " dB", 0.5, 1)
        self.sp_offset.setToolTip("Korrektur aller vorhergesagten Pegel (z. B. nach „An Messung angleichen“)")
        f.addRow("Auflösung", self.cb_res)
        f.addRow("Frequenz", self.cb_band)
        f.addRow("Farbbereich", self.sp_range)
        f.addRow("Pegelkorrektur", self.sp_offset)
        self.lbl_stats = QtWidgets.QLabel("–")
        self.lbl_stats.setWordWrap(True)
        f.addRow(self.lbl_stats)
        self.cb_res.currentIndexChanged.connect(self._fill_bands)
        self.cb_band.currentIndexChanged.connect(self.schedule)
        self.sp_range.valueChanged.connect(self._redraw_map)
        self.sp_offset.valueChanged.connect(self._redraw_map)
        pl.addWidget(g)
        self._fill_bands()

        g = QtWidgets.QGroupBox("Subwoofer-Setup")
        f = QtWidgets.QFormLayout(g)
        self.cb_sub = QtWidgets.QComboBox()
        self.cb_sub.addItems(rm.SUB_SETUPS)
        self.sp_sub_n = QtWidgets.QSpinBox(minimum=1, maximum=32, value=4)
        self.sp_sub_d = spin(0.2, 10, 1.2, " m", 0.1)
        self.sp_sub_y = spin(-5, 50, 0.5, " m", 0.1)
        self.sp_sub_z = spin(0, 20, 0.4, " m", 0.1)
        self.sp_sub_lvl = spin(80, 160, 124, " dB", 1, 1)
        self.sp_sub_x = spin(20, 300, 100, " Hz", 5, 0)
        self.sp_sub_f = spin(20, 200, 63, " Hz", 1, 0)
        self.sp_sub_arc = spin(0, 170, 60, " °", 5, 0)
        f.addRow("Muster", self.cb_sub)
        f.addRow("Anzahl", self.sp_sub_n)
        f.addRow("Abstand", self.sp_sub_d)
        f.addRow("Position y", self.sp_sub_y)
        f.addRow("Höhe", self.sp_sub_z)
        f.addRow("Pegel je Sub @1 m", self.sp_sub_lvl)
        f.addRow("Übergang (Tiefpass)", self.sp_sub_x)
        f.addRow("Zielfrequenz (Cardioid)", self.sp_sub_f)
        f.addRow("Bogenwinkel (Arc)", self.sp_sub_arc)
        hint = QtWidgets.QLabel("Endfire: Subs hintereinander, vordere verzögert – bündelt nach vorn. "
                                "Cardioid: hinterer Sub invertiert und verzögert – leise auf der Bühne. "
                                "Arc: Linie mit Delays wie ein Bogen – gleichmäßiger in der Breite.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        f.addRow(hint)
        b = QtWidgets.QPushButton("Subs erzeugen (ersetzt vorhandene Subs)")
        b.clicked.connect(self.generate_subs)
        f.addRow(b)
        pl.addWidget(g)

        g = QtWidgets.QGroupBox("Messpunkte")
        v = QtWidgets.QVBoxLayout(g)
        self.btn_place = QtWidgets.QPushButton("Punkt setzen (in die Karte klicken)")
        self.btn_place.setCheckable(True)
        self.btn_place.toggled.connect(self._place_toggled)
        v.addWidget(self.btn_place)
        self.list_pts = QtWidgets.QListWidget()
        self.list_pts.setMinimumHeight(110)
        v.addWidget(self.list_pts)
        row = QtWidgets.QHBoxLayout()
        b1 = QtWidgets.QPushButton("Messung zuordnen…")
        b1.setToolTip("Gespeichertes Spektrum aus dem Echtzeit-Modus oder einen Pegel eingeben")
        b1.clicked.connect(self.assign_measurement)
        b2 = QtWidgets.QPushButton("Entfernen")
        b2.clicked.connect(self.remove_point)
        row.addWidget(b1)
        row.addWidget(b2)
        v.addLayout(row)
        b3 = QtWidgets.QPushButton("Vorhersage an Messung angleichen")
        b3.setToolTip("Setzt die Pegelkorrektur so, dass Vorhersage und Messung im Mittel übereinstimmen")
        b3.clicked.connect(self.align_to_measurements)
        v.addWidget(b3)
        pl.addWidget(g)

        info = QtWidgets.QLabel("Vorhersage im Freifeld (ohne Reflexionen und Nachhall): zeigt Abdeckung, "
                                "Interferenzen und Laufzeiteffekte. Raumakustik folgt in Stufe 2.")
        info.setWordWrap(True)
        info.setStyleSheet("color: gray;")
        pl.addWidget(info)
        pl.addStretch(1)
        name_controls(self)

    # --- Daten ↔ Bedienelemente -------------------------------------------------------
    def _fill_room_spins(self) -> None:
        for s, v in ((self.sp_len, self.room.length), (self.sp_wid, self.room.width), (self.sp_hei, self.room.height),
                     (self.sp_lis, self.room.listen_height), (self.sp_res, self.room.resolution),
                     (self.sp_stage, self.room.stage_depth)):
            s.blockSignals(True)
            s.setValue(v)
            s.blockSignals(False)

    def _room_changed(self) -> None:
        self.room = rm.Room(length=self.sp_len.value(), width=self.sp_wid.value(), height=self.sp_hei.value(),
                            listen_height=self.sp_lis.value(), resolution=self.sp_res.value(),
                            stage_depth=self.sp_stage.value())
        self.schedule()

    def _fill_bands(self) -> None:
        cur = self.band
        self.cb_band.blockSignals(True)
        self.cb_band.clear()
        self.cb_band.addItem(BAND_A, "A")
        for fc in (rm.OCTAVES if self.cb_res.currentText() == "Oktaven" else rm.THIRDS):
            self.cb_band.addItem(f"{fc:g} Hz" if fc < 1000 else f"{fc / 1000:g} kHz", fc)
        i = self.cb_band.findData(cur)
        self.cb_band.setCurrentIndex(i if i >= 0 else self.cb_band.findData(63 if cur is None else 1000))
        self.cb_band.blockSignals(False)
        self.schedule()

    @property
    def band(self):
        return self.cb_band.currentData() if hasattr(self, "cb_band") and self.cb_band.count() else None

    @property
    def fraction(self) -> int:
        return 1 if self.cb_res.currentText() == "Oktaven" else 3

    def band_key(self, band=None) -> str:
        band = self.band if band is None else band
        return "A" if band == "A" else f"{float(band):g}"

    def _fill_table(self) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.speakers))
        for r, sp in enumerate(self.speakers):
            for c, (key, _, kind) in enumerate(COLUMNS):
                val = getattr(sp, key)
                if kind == "bool":
                    item = QtWidgets.QTableWidgetItem()
                    item.setFlags(QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
                    item.setCheckState(QtCore.Qt.Checked if val else QtCore.Qt.Unchecked)
                elif kind == "kind":
                    item = QtWidgets.QTableWidgetItem("Sub" if val == "sub" else "Top")
                elif kind == "pol":
                    item = QtWidgets.QTableWidgetItem("+" if val > 0 else "−")
                elif kind == "float":
                    item = QtWidgets.QTableWidgetItem(f"{val:g}")
                else:
                    item = QtWidgets.QTableWidgetItem(str(val))
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
        self.table.blockSignals(False)
        self._draw_speakers()

    def _table_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
        r, c = item.row(), item.column()
        if r >= len(self.speakers):
            return
        sp, (key, _, kind) = self.speakers[r], COLUMNS[c]
        text = item.text().strip()
        try:
            if kind == "bool":
                sp.enabled = item.checkState() == QtCore.Qt.Checked
            elif kind == "kind":
                sp.kind = "sub" if text.lower().startswith("s") else "top"
            elif kind == "pol":
                sp.polarity = -1 if text in ("-", "−", "-1", "inv", "invertiert") else 1
            elif kind == "float":
                setattr(sp, key, float(text.replace(",", ".")))
            else:
                setattr(sp, key, text)
        except ValueError:
            pass
        self._fill_table()   # Anzeige normalisieren (z. B. „1,5“ → 1.5)
        self.schedule()

    # --- Lautsprecher bearbeiten ---------------------------------------------------------
    def add_speaker(self, kind: str) -> None:
        cx = self.room.width / 2
        sp = rm.Speaker.sub(f"Sub {self._count('sub') + 1}", x=cx, y=0.5) if kind == "sub" else \
            rm.Speaker.top(f"Top {self._count('top') + 1}", x=cx, y=0.5, z=3.0)
        self.speakers.append(sp)
        self._fill_table()
        self.schedule()

    def _count(self, kind: str) -> int:
        return sum(1 for s in self.speakers if s.kind == kind)

    def _selected_rows(self) -> list[int]:
        return sorted({i.row() for i in self.table.selectedIndexes()})

    def duplicate_speaker(self) -> None:
        for r in self._selected_rows():
            sp = copy.deepcopy(self.speakers[r])
            sp.name += " (Kopie)"
            sp.x = min(self.room.width, sp.x + 1.0)
            self.speakers.append(sp)
        self._fill_table()
        self.schedule()

    def remove_speaker(self) -> None:
        for r in reversed(self._selected_rows()):
            del self.speakers[r]
        self._fill_table()
        self.schedule()

    def generate_subs(self) -> None:
        subs = rm.sub_setup(self.cb_sub.currentText(), self.room, count=self.sp_sub_n.value(),
                            spacing=self.sp_sub_d.value(), y=self.sp_sub_y.value(), z=self.sp_sub_z.value(),
                            level=self.sp_sub_lvl.value(), crossover=self.sp_sub_x.value(),
                            design_freq=self.sp_sub_f.value(), arc_deg=self.sp_sub_arc.value())
        self.speakers = [s for s in self.speakers if s.kind != "sub"] + subs
        for s in self.speakers:   # Tops passend trennen
            if s.kind == "top" and s.f_low and s.f_low < self.sp_sub_x.value():
                s.f_low = self.sp_sub_x.value()
        self._fill_table()
        if self.band != "A" and float(self.band) > 200:
            self.cb_band.setCurrentIndex(self.cb_band.findData(63) if self.cb_band.findData(63) >= 0 else 0)
        self.schedule()

    # --- Zeichnen ---------------------------------------------------------------
    def _draw_speakers(self) -> None:
        for it in self.spk_items:
            self.plot.removeItem(it)
        self.spk_items = []
        for i, sp in enumerate(self.speakers):
            color = "#ff7043" if sp.kind == "sub" else "#4fc3f7"
            if not sp.enabled:
                color = "#777"
            t = pg.TargetItem(pos=(sp.x, sp.y), size=13, symbol="s" if sp.kind == "sub" else "t",
                              pen=pg.mkPen("k", width=1.5), brush=pg.mkBrush(color), movable=True,
                              label=sp.name, labelOpts={"color": "#fff", "offset": (8, 4)})
            t.setZValue(30)
            t.sigPositionChangeFinished.connect(lambda item, i=i: self._speaker_moved(i, item))
            self.plot.addItem(t)
            self.spk_items.append(t)
            if sp.kind == "top" or sp.cov_h < 360:
                a = math.radians(sp.azimuth)
                ln = pg.PlotDataItem([sp.x, sp.x + 1.2 * math.sin(a)], [sp.y, sp.y + 1.2 * math.cos(a)],
                                     pen=pg.mkPen(color, width=2))
                ln.setZValue(29)
                self.plot.addItem(ln)
                self.spk_items.append(ln)

    def _speaker_moved(self, i: int, item) -> None:
        if i >= len(self.speakers):
            return
        p = item.pos()
        sp = self.speakers[i]
        sp.x = round(min(max(p.x(), -5), self.room.width + 5), 2)
        sp.y = round(min(max(p.y(), -5), self.room.length + 5), 2)
        self._fill_table()
        self.schedule()

    def _draw_room(self) -> None:
        w, length, sd = self.room.width, self.room.length, self.room.stage_depth
        self.outline.setData([0, w, w, 0, 0], [0, 0, length, length, 0])
        self.stage.setData([0, 0, w, w], [0, -sd, -sd, 0] if sd > 0 else [0, w])
        if (w, length, sd) != getattr(self, "_shown_room", None):    # Ansicht nur bei neuer Raumgröße anpassen
            self._shown_room = (w, length, sd)
            self.plot.setRange(xRange=(-1, w + 1), yRange=(-sd - 1, length + 1), padding=0.02)

    def schedule(self) -> None:
        if hasattr(self, "_recalc"):
            self._recalc.start()

    def compute(self) -> None:
        """Karte im Hintergrund rechnen (bleibt bedienbar, auch bei vielen Lautsprechern)."""
        if self.band is None:
            return
        self._draw_room()
        self._job += 1
        w = _Worker(self._job, self.room, self.speakers, self.band, self.fraction)
        w.done.connect(self._computed)
        w.finished.connect(lambda w=w: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(w)
        w.start()

    def compute_now(self) -> None:
        """Synchron rechnen (Tests, Export)."""
        self._draw_room()
        self._job += 1
        self._computed(self._job, rm.level_map(self.room, self.speakers, self.band, self.fraction))

    def _computed(self, job_id: int, result) -> None:
        if job_id != self._job:
            return                      # veraltet – neuere Berechnung läuft
        if isinstance(result, Exception):
            self.lbl_stats.setText(f"Fehler: {result}")
            return
        self.map = result
        self._redraw_map()

    def _redraw_map(self) -> None:
        if self.map is None:
            return
        xs, ys, lv = self.map
        lv = lv + self.sp_offset.value()
        finite = lv[np.isfinite(lv)]
        if not len(finite):
            self.img.clear()
            self.lbl_stats.setText("Keine aktiven Lautsprecher")
            self._draw_points()
            return
        top = math.ceil(float(finite.max()))
        lo = top - self.sp_range.value()
        self.img.setImage(np.nan_to_num(lv, nan=lo), autoLevels=False, levels=(lo, top))
        dx = xs[1] - xs[0] if len(xs) > 1 else 1
        dy = ys[1] - ys[0] if len(ys) > 1 else 1
        self.img.setRect(QtCore.QRectF(xs[0] - dx / 2, ys[0] - dy / 2, xs[-1] - xs[0] + dx, ys[-1] - ys[0] + dy))
        self.cbar.setLevels((lo, top))
        self.cbar.axis.setLabel("dB(A)" if self.band == "A" else "dB SPL")
        u = rm.uniformity(lv[ys >= 0])               # Statistik nur für das Publikum
        stage = lv[ys < 0]
        stage_txt = (f"<br>Bühne: Median {np.median(stage):.1f} dB "
                     f"({np.median(stage) - u['median']:+.1f} dB zum Publikum)" if stage.size else "")
        self.lbl_stats.setText(
            f"<b>{self.cb_band.currentText()}</b><br>Median {u['median']:.1f} dB · Min {u['min']:.1f} · "
            f"Max {u['max']:.1f}<br>±3 dB um den Median auf <b>{100 * u['within']:.0f} %</b> der Fläche"
            + stage_txt)
        self._draw_points()

    # --- Messpunkte ---------------------------------------------------------------------
    def _place_toggled(self, on: bool) -> None:
        self._placing = on
        self.plot.setCursor(QtCore.Qt.CrossCursor if on else QtCore.Qt.ArrowCursor)

    def _mouse_clicked(self, ev) -> None:
        if not self._placing or ev.button() != QtCore.Qt.LeftButton:
            return
        vb = self.plot.getViewBox()
        if not vb.sceneBoundingRect().contains(ev.scenePos()):
            return
        p = vb.mapSceneToView(ev.scenePos())
        name, ok = QtWidgets.QInputDialog.getText(self, "Messpunkt", "Name der Messposition:",
                                                  text=f"Punkt {len(self.points) + 1}")
        if ok:
            self.add_point(name or f"Punkt {len(self.points) + 1}", p.x(), p.y())
        self.btn_place.setChecked(False)

    def add_point(self, name: str, x: float, y: float) -> rm.MeasPoint:
        pt = rm.MeasPoint(name, round(x, 2), round(y, 2))
        self.points.append(pt)
        self._refresh_points()
        return pt

    def remove_point(self) -> None:
        r = self.list_pts.currentRow()
        if 0 <= r < len(self.points):
            del self.points[r]
            self._refresh_points()

    def predicted_at(self, pt: rm.MeasPoint, band=None) -> float:
        band = self.band if band is None else band
        v = rm.band_level(self.speakers, band, np.array(pt.x), np.array(pt.y),
                          np.array(self.room.listen_height), self.fraction)
        return float(v) + self.sp_offset.value()

    def spectrum_traces(self) -> list[dict]:
        if self.realtime is None:
            return []
        return [t for t in self.realtime.traces.traces if t.get("kind") == "spec"]

    def assign_measurement(self) -> None:
        r = self.list_pts.currentRow()
        if not 0 <= r < len(self.points):
            QtWidgets.QMessageBox.information(self, "Messpunkt", "Bitte zuerst einen Messpunkt in der Liste wählen.")
            return
        pt = self.points[r]
        traces = self.spectrum_traces()
        manual = f"Pegel für {self.cb_band.currentText()} eingeben…"
        names = [t["name"] for t in traces] + [manual]
        choice, ok = QtWidgets.QInputDialog.getItem(
            self, "Messung zuordnen", "Gespeichertes Spektrum (Echtzeit-Modus, möglichst kalibriert):", names, 0, False)
        if not ok:
            return
        if choice == manual:
            val, ok = QtWidgets.QInputDialog.getDouble(self, "Messwert", "Gemessener Pegel [dB]:",
                                                       self.predicted_at(pt), -50, 200, 1)
            if ok:
                pt.measured[self.band_key()] = val
                pt.source = "manuell"
        else:
            self.assign_trace(pt, traces[names.index(choice)])
        self._refresh_points()

    def assign_trace(self, pt: rm.MeasPoint, trace: dict) -> None:
        pt.source = trace.get("name", "Messung")
        for band in ("A", *rm.OCTAVES, *rm.THIRDS):
            v = rm.measured_band_level(trace, band if band == "A" else float(band))
            if v is not None:
                pt.measured[self.band_key(band)] = round(v, 2)

    def align_to_measurements(self) -> None:
        key = self.band_key()
        diffs = [pt.measured[key] - (self.predicted_at(pt) - self.sp_offset.value())
                 for pt in self.points if key in pt.measured]
        if not diffs:
            QtWidgets.QMessageBox.information(self, "Angleichen", "Für diese Frequenz gibt es noch keine Messwerte.")
            return
        self.sp_offset.setValue(round(float(np.mean(diffs)), 1))

    def _refresh_points(self) -> None:
        self.list_pts.clear()
        key = self.band_key()
        for pt in self.points:
            pred = self.predicted_at(pt)
            text = f"{pt.name}  ({pt.x:.1f} / {pt.y:.1f} m) · Vorhersage {pred:.1f} dB"
            if key in pt.measured:
                m = pt.measured[key]
                text += f" · Messung {m:.1f} dB · Δ {m - pred:+.1f} dB"
            self.list_pts.addItem(text)
        self._draw_points()

    def _draw_points(self) -> None:
        for lab in self.pt_labels:
            self.plot.removeItem(lab)
        self.pt_labels = []
        self.pts_item.setData([p.x for p in self.points], [p.y for p in self.points])
        key = self.band_key() if self.band is not None else None
        for pt in self.points:
            pred = self.predicted_at(pt)
            txt = f"{pt.name}\n{pred:.1f} dB"
            if key in pt.measured:
                txt += f" | gem. {pt.measured[key]:.1f} (Δ {pt.measured[key] - pred:+.1f})"
            lab = pg.TextItem(txt, color="#fff", fill=pg.mkBrush(20, 22, 26, 200), anchor=(0, 1.1))
            lab.setPos(pt.x, pt.y)
            lab.setZValue(25)
            self.plot.addItem(lab)
            self.pt_labels.append(lab)
        if self.list_pts.count() != len(self.points):
            self._refresh_points()

    # --- Maus ----------------------------------------------------------------------
    def _mouse_moved(self, pos) -> None:
        vb = self.plot.getViewBox()
        if self.map is None or not vb.sceneBoundingRect().contains(pos):
            self.hover.hide()
            return
        p = vb.mapSceneToView(pos)
        xs, ys, lv = self.map
        if not (xs[0] <= p.x() <= xs[-1] and ys[0] <= p.y() <= ys[-1]):
            self.hover.hide()
            return
        i = int(np.clip(np.searchsorted(ys, p.y()), 0, len(ys) - 1))
        j = int(np.clip(np.searchsorted(xs, p.x()), 0, len(xs) - 1))
        v = lv[i, j] + self.sp_offset.value()
        dist = [(math.dist((p.x(), p.y()), (s.x, s.y)), s.name) for s in self.speakers if s.enabled]
        near = min(dist)[1] if dist else ""
        self.hover.setText(f"x {p.x():.1f} m · y {p.y():.1f} m · <b>{v:.1f} dB</b>"
                           + (f"<br><span style='color:#aaa'>nächster Lautsprecher: {near}</span>" if near else ""))
        self.hover.adjustSize()
        wp = self.plot.mapFromScene(pos)
        self.hover.move(min(int(wp.x()) + 14, self.plot.width() - self.hover.width() - 4), max(0, int(wp.y()) - 30))
        self.hover.show()
        self.hover.raise_()

    # --- Sitzung -----------------------------------------------------------------------
    def get_state(self) -> tuple[dict, dict]:
        return {"model": rm.to_dict(self.room, self.speakers, self.points), "controls": controls_state(self)}, {}

    def set_state(self, meta: dict, arrays: dict) -> None:
        if meta.get("model"):
            self.room, self.speakers, self.points = rm.from_dict(meta["model"])
        else:
            self.room = rm.Room()
            self.speakers, self.points = example_setup(self.room), []
        apply_controls_state(self, meta.get("controls", {}))
        self._fill_room_spins()
        self._fill_table()
        self._refresh_points()
        self.schedule()
