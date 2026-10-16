"""Raum-Modus: Lautsprecher im Raum, Pegel-/STI-Karten, Wellenbild, Raummoden, 3D, Messpunkte.

Stufe 1: Raum, Lautsprecher (Öffnungswinkel), Pegelkarte mit phasenrichtiger Summe, Sub-Setups, Messpunkte.
Stufe 2: Wellenbild (Draufsicht/Längsschnitt, animiert), Raummoden, Reflexionen 1. Ordnung, Nachhall
         (gemessen oder berechnet), STI-Karte.
Stufe 3: 3D-Ansicht, Polardaten-Import (gemessene Abstrahlung), mehrere Hörflächen (z. B. Empore).
"""

from __future__ import annotations

import copy
import math

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

from ..dsp import polar as polar_mod
from ..dsp import roomacoustics as ra
from ..dsp import roommodel as rm
from ..dsp.sti import rating as sti_rating
from .room3d import Room3DView, _rgba, scene_data
from .session import apply_controls_state, controls_state, name_controls
from .state import AppState

# Farbskala ähnlich üblicher Planungsprogramme: leise blau → laut rot
CMAP = pg.ColorMap(np.array([0.0, 0.2, 0.4, 0.6, 0.8, 1.0]),
                   np.array([(20, 30, 110), (30, 110, 230), (40, 200, 200), (90, 210, 60),
                             (250, 220, 40), (230, 40, 30)], dtype=np.ubyte))
# STI: schlecht rot → gut grün
CMAP_STI = pg.ColorMap(np.array([0.0, 0.3, 0.45, 0.6, 0.75, 1.0]),
                       np.array([(150, 20, 20), (220, 60, 40), (240, 160, 40), (230, 220, 60),
                                 (90, 200, 80), (20, 140, 70)], dtype=np.ubyte))
# Wellenbild: Unterdruck blau, Überdruck rot
CMAP_WAVE = pg.ColorMap(np.array([0.0, 0.5, 1.0]),
                        np.array([(30, 80, 220), (240, 240, 240), (220, 40, 30)], dtype=np.ubyte))
BAND_A = "Breitband (A-bewertet)"
VIEWS = {"Pegel": "level", "STI (Sprachverständlichkeit)": "sti", "Wellenbild – Draufsicht": "wave_top",
         "Wellenbild – Längsschnitt": "wave_section", "Raummode": "mode"}
MAIN_PLANE = "Hauptfläche (Parkett)"

# Spalten der Lautsprecher-Tabelle: (Attribut, Überschrift, Art)
COLUMNS = [("enabled", "An", "bool"), ("name", "Name", "str"), ("kind", "Typ", "kind"),
           ("x", "X [m]", "float"), ("y", "Y [m]", "float"), ("z", "Höhe [m]", "float"),
           ("azimuth", "Richtung [°]", "float"), ("tilt", "Neigung [°]", "float"),
           ("level", "Pegel @1 m [dB]", "float"), ("delay_ms", "Delay [ms]", "float"),
           ("polarity", "Polarität", "pol"), ("cov_h", "Öffnung H [°]", "float"),
           ("cov_v", "Öffnung V [°]", "float"), ("f_low", "Hochpass [Hz]", "float"),
           ("f_high", "Tiefpass [Hz]", "float"), ("polar", "Abstrahlung", "polar")]


def example_setup(room: rm.Room) -> list[rm.Speaker]:
    w = room.width
    return [rm.Speaker.top("Top L", x=1.5, y=0.5, z=3.0, azimuth=12, tilt=-5, f_low=100),
            rm.Speaker.top("Top R", x=w - 1.5, y=0.5, z=3.0, azimuth=-12, tilt=-5, f_low=100),
            *rm.sub_setup("L/R-Stacks", room, count=2, y=0.5)]


class _Worker(QtCore.QThread):
    done = QtCore.Signal(int, object)

    def __init__(self, job_id, fn):
        super().__init__()
        self.job_id, self.fn = job_id, fn

    def run(self) -> None:
        try:
            self.done.emit(self.job_id, self.fn())
        except Exception as exc:  # noqa: BLE001
            self.done.emit(self.job_id, exc)


class PlaneDialog(QtWidgets.QDialog):
    def __init__(self, room: rm.Room, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Hörfläche hinzufügen")
        f = QtWidgets.QFormLayout(self)
        self.name = QtWidgets.QLineEdit("Empore")

        def sp(v, lo=-50, hi=300):
            s = QtWidgets.QDoubleSpinBox(minimum=lo, maximum=hi, value=v, decimals=2, singleStep=0.5, suffix=" m")
            return s
        self.x0, self.x1 = sp(0), sp(room.width)
        self.y0, self.y1 = sp(round(room.length * 0.7, 1)), sp(room.length)
        self.z = sp(4.5, 0, 60)
        f.addRow("Name", self.name)
        f.addRow("x von", self.x0)
        f.addRow("x bis", self.x1)
        f.addRow("y von", self.y0)
        f.addRow("y bis", self.y1)
        f.addRow("Ohrhöhe über Hallenboden", self.z)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def plane(self) -> rm.Plane:
        return rm.Plane(self.name.text() or "Empore", self.x0.value(), self.y0.value(), self.x1.value(),
                        self.y1.value(), self.z.value())


class RoomView(QtWidgets.QWidget):
    def __init__(self, state: AppState, realtime=None, impulse=None, parent=None):
        super().__init__(parent)
        self.state, self.realtime, self.impulse = state, realtime, impulse
        self.room = rm.Room()
        self.speakers: list[rm.Speaker] = example_setup(self.room)
        self.points: list[rm.MeasPoint] = []
        self.planes: list[rm.Plane] = []
        self.map = None                 # (xs, ys, Werte) der aktuellen Karte
        self.result: dict | None = None
        self._job = 0
        self._workers: list[_Worker] = []
        self._placing = False
        self._phase = 0.0
        self._modes: list[dict] = []
        self._build()
        self._recalc = QtCore.QTimer(self, singleShot=True, interval=150, timeout=self.compute)
        self._anim = QtCore.QTimer(self, interval=40, timeout=self._animate)
        self._fill_room_spins()
        self._fill_table()
        self._fill_planes()
        self._fill_modes()
        self._update_rt_label()
        self._view_changed()

    # --- Aufbau -------------------------------------------------------------------
    def _build(self) -> None:
        lay = QtWidgets.QHBoxLayout(self)
        left = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self.view_tabs = QtWidgets.QTabWidget()
        self.plot = pg.PlotWidget()
        self.plot.setAspectLocked(True)
        self.plot.showGrid(x=True, y=True, alpha=0.15)
        self.img = pg.ImageItem(axisOrder="row-major")
        self.img.setZValue(-10)
        self.plot.addItem(self.img)
        self.cbar = pg.ColorBarItem(values=(70, 100), colorMap=CMAP, interactive=False, label="dB SPL")
        self.cbar.setImageItem(self.img, insert_in=self.plot.getPlotItem())
        self.outline = pg.PlotDataItem(pen=pg.mkPen("#ddd", width=2))
        self.stage = pg.PlotDataItem(pen=pg.mkPen("#ffcc33", width=3, style=QtCore.Qt.DashLine))
        self.plane_outline = pg.PlotDataItem(pen=pg.mkPen("#9fd0ff", width=1.5, style=QtCore.Qt.DotLine),
                                             connect="pairs")
        for it in (self.outline, self.stage, self.plane_outline):
            self.plot.addItem(it)
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
        self.view_tabs.addTab(self.plot, "Karte")
        self.view3d = Room3DView()
        self.view_tabs.addTab(self.view3d, "3D")
        self.view_tabs.currentChanged.connect(lambda _: self._update_3d())
        left.addWidget(self.view_tabs)

        box = QtWidgets.QWidget()
        bl = QtWidgets.QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        row = QtWidgets.QHBoxLayout()
        for text, slot in (("+ Top", lambda: self.add_speaker("top")), ("+ Sub", lambda: self.add_speaker("sub")),
                           ("Duplizieren", self.duplicate_speaker), ("Entfernen", self.remove_speaker),
                           ("Abstrahlung importieren…", self.import_polar),
                           ("Öffnungswinkel verwenden", self.clear_polar)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        bl.addLayout(row)
        self.table = QtWidgets.QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([c[1] for c in COLUMNS])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.itemChanged.connect(self._table_changed)
        bl.addWidget(self.table)
        left.addWidget(box)
        left.setSizes([620, 230])
        left.setStretchFactor(0, 3)   # Karte/3D bekommt den meisten Platz
        left.setStretchFactor(1, 1)
        lay.addWidget(left, 1)

        panel = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(panel)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        scroll.setFixedWidth(330)
        lay.addWidget(scroll)

        def spin(lo, hi, val, suffix, step=0.5, dec=2):
            s = QtWidgets.QDoubleSpinBox(minimum=lo, maximum=hi, value=val, decimals=dec, singleStep=step,
                                         suffix=suffix)
            s.setKeyboardTracking(False)
            return s

        # Darstellung
        g = QtWidgets.QGroupBox("Darstellung")
        self.f_view = f = QtWidgets.QFormLayout(g)
        self.cb_view = QtWidgets.QComboBox()
        self.cb_view.addItems(list(VIEWS))
        self.cb_plane = QtWidgets.QComboBox()
        self.chk_room = QtWidgets.QCheckBox("Raumakustik einrechnen (Reflexionen, Nachhall)")
        self.cb_res = QtWidgets.QComboBox()
        self.cb_res.addItems(["Oktaven", "Terzen"])
        self.cb_band = QtWidgets.QComboBox()
        self.sp_range = spin(6, 60, 24, " dB", 3, 0)
        self.sp_offset = spin(-60, 60, 0, " dB", 0.5, 1)
        self.sp_offset.setToolTip("Korrektur aller vorhergesagten Pegel (z. B. nach „An Messung angleichen“)")
        self.sp_wave = spin(10, 2000, 63, " Hz", 1, 1)
        self.chk_anim = QtWidgets.QCheckBox("Animation")
        self.chk_anim.setChecked(True)
        self.sp_section = spin(-50, 300, 7, " m", 0.5)
        self.cb_mode = QtWidgets.QComboBox()
        f.addRow("Ansicht", self.cb_view)
        f.addRow("Hörfläche", self.cb_plane)
        f.addRow(self.chk_room)
        f.addRow("Auflösung", self.cb_res)
        f.addRow("Frequenz", self.cb_band)
        f.addRow("Farbbereich", self.sp_range)
        f.addRow("Pegelkorrektur", self.sp_offset)
        f.addRow("Frequenz Welle", self.sp_wave)
        f.addRow(self.chk_anim)
        f.addRow("Schnitt bei x", self.sp_section)
        f.addRow("Mode", self.cb_mode)
        self.lbl_stats = QtWidgets.QLabel("–")
        self.lbl_stats.setWordWrap(True)
        f.addRow(self.lbl_stats)
        self.cb_view.currentIndexChanged.connect(self._view_changed)
        self.cb_plane.currentIndexChanged.connect(self.schedule)
        self.chk_room.toggled.connect(self.schedule)
        self.cb_res.currentIndexChanged.connect(self._fill_bands)
        self.cb_band.currentIndexChanged.connect(self.schedule)
        for s in (self.sp_wave, self.sp_section):
            s.valueChanged.connect(self.schedule)
        self.cb_mode.currentIndexChanged.connect(self.schedule)
        self.chk_anim.toggled.connect(self._anim_toggled)
        self.sp_range.valueChanged.connect(self._redraw_map)
        self.sp_offset.valueChanged.connect(self._redraw_map)
        pl.addWidget(g)
        self._fill_bands()

        # Raum
        g = QtWidgets.QGroupBox("Raum")
        f = QtWidgets.QFormLayout(g)
        self.sp_len = spin(2, 300, 20, " m")
        self.sp_wid = spin(2, 300, 14, " m")
        self.sp_hei = spin(2, 60, 6, " m")
        self.sp_lis = spin(0, 20, 1.2, " m", 0.1)
        self.sp_stage = spin(0, 30, 5, " m", 0.5)
        self.sp_stage.setToolTip("Bühnenbereich hinter der Bühnenkante – zeigt, wie viel Pegel auf der Bühne ankommt")
        self.sp_res = spin(0.1, 2, 0.25, " m", 0.05)
        f.addRow("Länge (Tiefe)", self.sp_len)
        f.addRow("Breite", self.sp_wid)
        f.addRow("Höhe", self.sp_hei)
        f.addRow("Hörhöhe", self.sp_lis)
        f.addRow("Bühnentiefe", self.sp_stage)
        f.addRow("Raster", self.sp_res)
        for s in (self.sp_len, self.sp_wid, self.sp_hei, self.sp_lis, self.sp_res, self.sp_stage):
            s.valueChanged.connect(self._room_changed)
        pl.addWidget(g)

        # Raumakustik
        g = QtWidgets.QGroupBox("Raumakustik")
        f = QtWidgets.QFormLayout(g)
        self.chk_refl = QtWidgets.QCheckBox("Reflexionen 1. Ordnung (Wände, Boden, Decke)")
        self.sp_a_floor = spin(0, 1, 0.10, "", 0.05)
        self.sp_a_walls = spin(0, 1, 0.15, "", 0.05)
        self.sp_a_ceil = spin(0, 1, 0.30, "", 0.05)
        for s in (self.sp_a_floor, self.sp_a_walls, self.sp_a_ceil):
            s.setToolTip("Absorptionsgrad α: 0 = schallhart (Beton, Glas), 0,3 = Publikum/Teppich, "
                         "0,7+ = Akustikdecke/Absorber")
        self.sp_noise = spin(0, 110, 35, " dB(A)", 1, 0)
        self.sp_noise.setToolTip("Hintergrundgeräusch im Raum (Lüftung, Publikum) – geht in die STI-Vorhersage ein")
        f.addRow(self.chk_refl)
        f.addRow("α Boden", self.sp_a_floor)
        f.addRow("α Wände", self.sp_a_walls)
        f.addRow("α Decke", self.sp_a_ceil)
        f.addRow("Störgeräusch", self.sp_noise)
        self.lbl_rt = QtWidgets.QLabel()
        self.lbl_rt.setWordWrap(True)
        f.addRow(self.lbl_rt)
        row = QtWidgets.QHBoxLayout()
        b1 = QtWidgets.QPushButton("Aus Messung übernehmen")
        b1.setToolTip("Nachhallzeit (T30, sonst T20) der letzten Messung im Modus Impulsantwort übernehmen")
        b1.clicked.connect(self.take_measured_rt)
        b2 = QtWidgets.QPushButton("Berechnen")
        b2.setToolTip("Nachhallzeit nach Sabine aus Raumgröße und Absorptionsgraden")
        b2.clicked.connect(self.use_computed_rt)
        row.addWidget(b1)
        row.addWidget(b2)
        f.addRow(row)
        self.chk_refl.toggled.connect(self._room_changed)
        for s in (self.sp_a_floor, self.sp_a_walls, self.sp_a_ceil, self.sp_noise):
            s.valueChanged.connect(self._room_changed)
        pl.addWidget(g)

        # Hörflächen
        g = QtWidgets.QGroupBox("Weitere Hörflächen (z. B. Empore)")
        v = QtWidgets.QVBoxLayout(g)
        self.list_planes = QtWidgets.QListWidget()
        self.list_planes.setMaximumHeight(80)
        v.addWidget(self.list_planes)
        row = QtWidgets.QHBoxLayout()
        b1 = QtWidgets.QPushButton("Hinzufügen…")
        b1.clicked.connect(self.add_plane_dialog)
        b2 = QtWidgets.QPushButton("Entfernen")
        b2.clicked.connect(self.remove_plane)
        row.addWidget(b1)
        row.addWidget(b2)
        v.addLayout(row)
        pl.addWidget(g)

        # Subwoofer-Setup
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

        # Messpunkte
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

        info = QtWidgets.QLabel("Vorhersage mit Punktquellen, Spiegelquellen 1. Ordnung und statistischem Nachhall "
                                "im Rechteckraum – für Planung und Einmessung, kein Ersatz für eine zertifizierte "
                                "Simulation.")
        info.setWordWrap(True)
        info.setStyleSheet("color: gray;")
        pl.addWidget(info)
        pl.addStretch(1)
        name_controls(self)

    # --- Daten ↔ Bedienelemente -------------------------------------------------------
    def _fill_room_spins(self) -> None:
        r = self.room
        for s, v in ((self.sp_len, r.length), (self.sp_wid, r.width), (self.sp_hei, r.height),
                     (self.sp_lis, r.listen_height), (self.sp_res, r.resolution), (self.sp_stage, r.stage_depth),
                     (self.sp_a_floor, r.alpha_floor), (self.sp_a_walls, r.alpha_walls),
                     (self.sp_a_ceil, r.alpha_ceiling), (self.sp_noise, r.noise_dba)):
            s.blockSignals(True)
            s.setValue(v)
            s.blockSignals(False)
        self.chk_refl.blockSignals(True)
        self.chk_refl.setChecked(r.reflections)
        self.chk_refl.blockSignals(False)

    def _room_changed(self) -> None:
        self.room = rm.Room(length=self.sp_len.value(), width=self.sp_wid.value(), height=self.sp_hei.value(),
                            listen_height=self.sp_lis.value(), resolution=self.sp_res.value(),
                            stage_depth=self.sp_stage.value(), reflections=self.chk_refl.isChecked(),
                            alpha_floor=self.sp_a_floor.value(), alpha_walls=self.sp_a_walls.value(),
                            alpha_ceiling=self.sp_a_ceil.value(), rt60=dict(self.room.rt60),
                            noise_dba=self.sp_noise.value())
        if self.chk_refl.isChecked() and not self.chk_room.isChecked():
            self.chk_room.setChecked(True)
        self._fill_modes()
        self._update_rt_label()
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

    def _fill_modes(self) -> None:
        cur = self.cb_mode.currentText()
        self._modes = ra.room_modes(self.room, 250.0)
        self.cb_mode.blockSignals(True)
        self.cb_mode.clear()
        names = {"axial": "axial", "tangential": "tangential", "oblique": "schräg"}
        for m in self._modes:
            self.cb_mode.addItem(f"{m['f']:.1f} Hz – {m['n'][0]},{m['n'][1]},{m['n'][2]} ({names[m['kind']]})")
        i = self.cb_mode.findText(cur)
        self.cb_mode.setCurrentIndex(max(i, 0))
        self.cb_mode.blockSignals(False)

    def _fill_planes(self) -> None:
        cur = self.cb_plane.currentText()
        self.cb_plane.blockSignals(True)
        self.cb_plane.clear()
        self.cb_plane.addItem(MAIN_PLANE)
        for p in self.planes:
            self.cb_plane.addItem(p.name)
        i = self.cb_plane.findText(cur)
        self.cb_plane.setCurrentIndex(max(i, 0))
        self.cb_plane.blockSignals(False)
        self.list_planes.clear()
        for p in self.planes:
            self.list_planes.addItem(f"{p.name}: x {p.x0:g}–{p.x1:g} m, y {p.y0:g}–{p.y1:g} m, Ohrhöhe {p.z:g} m")

    def _update_rt_label(self) -> None:
        src = "gemessen" if self.room.rt60 else "berechnet (Sabine)"
        vals = " · ".join(f"{b if b < 1000 else b // 1000}{'k' if b >= 1000 else ''}: {ra.rt60(self.room, b):.2f}"
                          for b in (125, 250, 500, 1000, 2000, 4000))
        self.lbl_rt.setText(f"<b>Nachhallzeit T60 [s]</b> ({src})<br>{vals}")

    @property
    def band(self):
        return self.cb_band.currentData() if hasattr(self, "cb_band") and self.cb_band.count() else None

    @property
    def fraction(self) -> int:
        return 1 if self.cb_res.currentText() == "Oktaven" else 3

    @property
    def view_kind(self) -> str:
        return VIEWS[self.cb_view.currentText()]

    @property
    def plane(self) -> rm.Plane | None:
        i = self.cb_plane.currentIndex() - 1
        return self.planes[i] if 0 <= i < len(self.planes) else None

    def band_key(self, band=None) -> str:
        band = self.band if band is None else band
        return "A" if band == "A" else f"{float(band):g}"

    def _view_changed(self) -> None:
        kind = self.view_kind
        rows = {self.cb_plane: kind in ("level", "sti", "mode"), self.chk_room: kind in ("level", "wave_top",
                                                                                        "wave_section"),
                self.cb_res: kind == "level", self.cb_band: kind == "level", self.sp_range: kind == "level",
                self.sp_offset: kind == "level", self.sp_wave: kind.startswith("wave"),
                self.chk_anim: kind.startswith("wave"), self.sp_section: kind == "wave_section",
                self.cb_mode: kind == "mode"}
        for w, vis in rows.items():
            self.f_view.setRowVisible(w, vis)
        if kind == "sti" and not self.chk_room.isChecked():
            pass  # STI rechnet immer mit Raum
        self._anim_toggled(self.chk_anim.isChecked())
        self.schedule()

    def _anim_toggled(self, on: bool) -> None:
        if on and self.view_kind.startswith("wave") and self.isVisible():
            self._anim.start()
        else:
            self._anim.stop()

    # --- Lautsprecher-Tabelle ---------------------------------------------------------
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
                elif kind == "polar":
                    item = QtWidgets.QTableWidgetItem("Polardaten" if val else "Öffnungswinkel")
                    item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
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
            elif kind == "str":
                setattr(sp, key, text)
        except ValueError:
            pass
        self._fill_table()   # Anzeige normalisieren (z. B. „1,5“ → 1.5)
        self.schedule()

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

    def import_polar(self) -> None:
        rows = self._selected_rows()
        if not rows:
            QtWidgets.QMessageBox.information(self, "Abstrahlung", "Bitte zuerst Lautsprecher in der Tabelle wählen.")
            return
        h_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Horizontale Polardaten (Frequenz × Winkel)", "", "Polardaten (*.csv *.txt *.tsv);;Alle Dateien (*)")
        if not h_path:
            return
        v_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Vertikale Polardaten (optional – Abbrechen = wie horizontal)", "",
            "Polardaten (*.csv *.txt *.tsv);;Alle Dateien (*)")
        try:
            self.apply_polar(rows, self._read(h_path), self._read(v_path) if v_path else None)
        except (OSError, polar_mod.PolarError) as exc:
            QtWidgets.QMessageBox.warning(self, "Abstrahlung", f"Datei nicht lesbar:\n{exc}")

    @staticmethod
    def _read(path: str) -> str:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read(2_000_000)

    def apply_polar(self, rows: list[int], h_text: str, v_text: str | None = None) -> None:
        data = polar_mod.make_polar(h_text, v_text)
        for r in rows:
            self.speakers[r].polar = copy.deepcopy(data)
        self._fill_table()
        self.schedule()

    def clear_polar(self) -> None:
        for r in self._selected_rows():
            self.speakers[r].polar = None
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

    # --- Hörflächen und Nachhall ----------------------------------------------------------
    def add_plane_dialog(self) -> None:
        dlg = PlaneDialog(self.room, self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self.add_plane(dlg.plane())

    def add_plane(self, plane: rm.Plane) -> None:
        self.planes.append(plane)
        self._fill_planes()
        self.schedule()

    def remove_plane(self) -> None:
        r = self.list_planes.currentRow()
        if 0 <= r < len(self.planes):
            del self.planes[r]
            self._fill_planes()
            self.schedule()

    def take_measured_rt(self) -> None:
        results = getattr(self.impulse, "results", None) or []
        rt = {}
        for res in results:
            t = res.t30 if res.t30 and np.isfinite(res.t30) else res.t20
            if res.center and t and np.isfinite(t) and t > 0:
                rt[f"{res.center:g}"] = round(float(t), 3)
        if not rt:
            QtWidgets.QMessageBox.information(self, "Nachhallzeit", "Noch keine Impulsantwort gemessen "
                                              "(Modus Impulsantwort → Messen).")
            return
        self.room.rt60 = rt
        self._update_rt_label()
        self.schedule()

    def use_computed_rt(self) -> None:
        self.room.rt60 = {}
        self._update_rt_label()
        self.schedule()

    # --- Rechnen ---------------------------------------------------------------------
    def schedule(self) -> None:
        """Neu rechnen – aber nur, wenn der Raum-Modus sichtbar ist (spart Rechenzeit beim Messen)."""
        if not hasattr(self, "_recalc"):
            return
        if not self.isVisible():
            self._dirty = True
            return
        self._recalc.start()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if getattr(self, "_dirty", True):
            self._dirty = False
            self._recalc.start()

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        self._anim.stop()

    def _job_fn(self):
        room, speakers, plane = copy.deepcopy(self.room), copy.deepcopy(self.speakers), copy.deepcopy(self.plane)
        kind, band, fraction = self.view_kind, self.band, self.fraction
        mode = self._modes[self.cb_mode.currentIndex()] if self._modes and self.cb_mode.currentIndex() >= 0 else None
        if kind == "mode" and mode is None:
            kind = "level"
        with_room = self.chk_room.isChecked()
        wave_f, xsec = self.sp_wave.value(), self.sp_section.value()
        planes = copy.deepcopy(self.planes)
        show_3d = self.view_tabs.currentWidget() is self.view3d

        def fn():
            res = ra.compute_view(room, speakers, kind, band=band, fraction=fraction, plane=plane,
                                  wave_freq=wave_f, x_section=xsec, mode=mode, with_room=with_room)
            if show_3d and kind in ("level", "sti"):     # alle Hörflächen für die 3D-Ansicht
                res["extra"] = [(p, ra.compute_view(room, speakers, kind, band=band, fraction=fraction, plane=p,
                                                    with_room=with_room)) for p in [None, *planes] if p is not plane]
            return res
        return fn

    def compute(self) -> None:
        """Im Hintergrund rechnen (bleibt bedienbar, auch bei vielen Lautsprechern)."""
        if self.band is None:
            return
        self._draw_room()
        self._job += 1
        w = _Worker(self._job, self._job_fn())
        w.done.connect(self._computed)
        w.finished.connect(lambda w=w: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(w)
        w.start()

    def compute_now(self) -> None:
        """Synchron rechnen (Tests, Export)."""
        self._draw_room()
        self._job += 1
        self._computed(self._job, self._job_fn()())

    def _computed(self, job_id: int, result) -> None:
        if job_id != self._job:
            return                      # veraltet – neuere Berechnung läuft
        if isinstance(result, Exception):
            self.lbl_stats.setText(f"Fehler: {result}")
            return
        self.result = result
        self.map = (result["xs"], result["ys"], result["data"])
        self._phase = 0.0
        self._redraw_map()
        self._update_3d()
        self._anim_toggled(self.chk_anim.isChecked())

    # --- Zeichnen ---------------------------------------------------------------
    def _set_axes(self, section: bool) -> None:
        vb = self.plot.getViewBox()
        vb.invertY(not section)
        self.plot.setLabel("bottom", "Tiefe y [m] (0 = Bühnenkante)" if section else "Breite x [m]")
        self.plot.setLabel("left", "Höhe z [m]" if section else "Tiefe y [m] (0 = Bühnenkante)")

    def _draw_room(self) -> None:
        r = self.room
        w, length, sd = r.width, r.length, r.stage_depth
        section = self.view_kind == "wave_section"
        self._set_axes(section)
        if section:
            self.outline.setData([r.y_min, length, length, r.y_min, r.y_min], [0, 0, r.height, r.height, 0])
            self.stage.setData([r.y_min, length], [r.listen_height, r.listen_height])
            self.plane_outline.setData([], [])
            key = ("section", w, length, sd, r.height)
            rng = dict(xRange=(r.y_min - 1, length + 1), yRange=(-0.5, r.height + 0.5))
        else:
            self.outline.setData([0, w, w, 0, 0], [0, 0, length, length, 0])
            self.stage.setData([0, 0, w, w], [0, -sd, -sd, 0] if sd > 0 else [0, w])
            px, py = [], []
            for p in self.planes:
                px += [p.x0, p.x1, p.x1, p.x1, p.x1, p.x0, p.x0, p.x0]
                py += [p.y0, p.y0, p.y0, p.y1, p.y1, p.y1, p.y1, p.y0]
            self.plane_outline.setData(px, py)
            key = ("top", w, length, sd)
            rng = dict(xRange=(-1, w + 1), yRange=(-sd - 1, length + 1))
        if key != getattr(self, "_shown_room", None):    # Ansicht nur bei neuer Geometrie anpassen
            self._shown_room = key
            self.plot.setRange(padding=0.02, **rng)
        self._draw_speakers()

    def _draw_speakers(self) -> None:
        for it in self.spk_items:
            self.plot.removeItem(it)
        self.spk_items = []
        section = getattr(self, "cb_view", None) is not None and self.view_kind == "wave_section"
        for i, sp in enumerate(self.speakers):
            color = "#ff7043" if sp.kind == "sub" else "#4fc3f7"
            if not sp.enabled:
                color = "#777"
            pos = (sp.y, sp.z) if section else (sp.x, sp.y)
            t = pg.TargetItem(pos=pos, size=13, symbol="s" if sp.kind == "sub" else "t",
                              pen=pg.mkPen("k", width=1.5), brush=pg.mkBrush(color), movable=not section,
                              label=sp.name, labelOpts={"color": "#fff", "offset": (8, 4)})
            t.setZValue(30)
            if not section:
                t.sigPositionChangeFinished.connect(lambda item, i=i: self._speaker_moved(i, item))
            self.plot.addItem(t)
            self.spk_items.append(t)
            if sp.kind == "top" or sp.cov_h < 360:
                a, tl = math.radians(sp.azimuth), math.radians(sp.tilt)
                if section:
                    xs_, ys_ = [sp.y, sp.y + 1.2 * math.cos(tl)], [sp.z, sp.z + 1.2 * math.sin(tl)]
                else:
                    xs_, ys_ = [sp.x, sp.x + 1.2 * math.sin(a)], [sp.y, sp.y + 1.2 * math.cos(a)]
                ln = pg.PlotDataItem(xs_, ys_, pen=pg.mkPen(color, width=2))
                ln.setZValue(29)
                self.plot.addItem(ln)
                self.spk_items.append(ln)

    def _speaker_moved(self, i: int, item) -> None:
        if i >= len(self.speakers):
            return
        p = item.pos()
        sp = self.speakers[i]
        sp.x = round(min(max(p.x(), -5), self.room.width + 5), 2)
        sp.y = round(min(max(p.y(), self.room.y_min - 5), self.room.length + 5), 2)
        self._fill_table()
        self.schedule()

    def _set_image(self, data, levels, cmap, label) -> None:
        xs, ys = self.result["xs"], self.result["ys"]
        self.img.setImage(np.nan_to_num(data, nan=levels[0]), autoLevels=False, levels=levels)
        dx = xs[1] - xs[0] if len(xs) > 1 else 1
        dy = ys[1] - ys[0] if len(ys) > 1 else 1
        self.img.setRect(QtCore.QRectF(xs[0] - dx / 2, ys[0] - dy / 2, xs[-1] - xs[0] + dx, ys[-1] - ys[0] + dy))
        self.cbar.setColorMap(cmap)
        self.img.setColorMap(cmap)
        self.cbar.setLevels(levels)
        self.cbar.axis.setLabel(label)

    def _redraw_map(self) -> None:
        if self.result is None:
            return
        kind, data = self.result["kind"], self.result["data"]
        ys = self.result["ys"]
        if kind == "level":
            lv = data + self.sp_offset.value()
            finite = lv[np.isfinite(lv)]
            if not len(finite):
                self.img.clear()
                self.lbl_stats.setText("Keine aktiven Lautsprecher")
                self._draw_points()
                return
            top = math.ceil(float(finite.max()))
            self._set_image(lv, (top - self.sp_range.value(), top), CMAP, "dB(A)" if self.band == "A" else "dB SPL")
            aud = lv[ys >= 0] if self.plane is None else lv
            u = rm.uniformity(aud)
            stage = lv[ys < 0] if self.plane is None else np.array([])
            stage_txt = (f"<br>Bühne: Median {np.median(stage):.1f} dB "
                         f"({np.median(stage) - u['median']:+.1f} dB zum Publikum)" if stage.size else "")
            room_txt = " · mit Raum" if self.chk_room.isChecked() else " · Direktschall"
            self.lbl_stats.setText(
                f"<b>{self.cb_band.currentText()}</b>{room_txt}<br>Median {u['median']:.1f} dB · Min {u['min']:.1f} · "
                f"Max {u['max']:.1f}<br>±3 dB um den Median auf <b>{100 * u['within']:.0f} %</b> der Fläche"
                + stage_txt)
        elif kind == "sti":
            self._set_image(data, (0.0, 1.0), CMAP_STI, "STI")
            aud = data[ys >= 0] if self.plane is None else data
            aud = aud[np.isfinite(aud)]
            mean = float(np.mean(aud)) if aud.size else float("nan")
            self.lbl_stats.setText(
                f"<b>STI-Vorhersage</b> (männliche Sprache, Störgeräusch {self.room.noise_dba:.0f} dB(A))<br>"
                f"Mittel {mean:.2f} ({sti_rating(mean)}) · Min {aud.min():.2f} · Max {aud.max():.2f}<br>"
                f"STI ≥ 0,50 auf <b>{100 * np.mean(aud >= 0.5):.0f} %</b> der Fläche "
                f"(Ziel Sprachalarmanlage: Mittel ≥ 0,50)")
        elif kind.startswith("wave"):
            self._set_image(ra.wave_frame(self.result["field"], self._phase), (-1.0, 1.0), CMAP_WAVE, "Schalldruck")
            lam = rm.C / max(self.sp_wave.value(), 1)
            self.lbl_stats.setText(f"<b>Wellenbild {self.sp_wave.value():g} Hz</b> · Wellenlänge {lam:.2f} m<br>"
                                   "Rot = Überdruck, Blau = Unterdruck. Weiße Bereiche ohne Bewegung = Auslöschung.")
        elif kind == "mode":
            self._set_image(data, (-30.0, 0.0), CMAP, "dB rel. Maximum")
            m = self._modes[self.cb_mode.currentIndex()] if self._modes else None
            if m:
                self.lbl_stats.setText(
                    f"<b>Raummode {m['f']:.1f} Hz</b> (Ordnung {m['n'][0]},{m['n'][1]},{m['n'][2]})<br>Rot = Druckbauch "
                    "(Überhöhung), Blau = Knoten (Loch). Erste Moden: "
                    + ", ".join(f"{x['f']:.0f}" for x in self._modes[:6]) + " Hz")
        self._draw_points()

    def _animate(self) -> None:
        if self.result is None or not self.result["kind"].startswith("wave") or not self.isVisible():
            return
        self._phase = (self._phase + 2 * math.pi / 30) % (2 * math.pi)
        self.img.setImage(ra.wave_frame(self.result["field"], self._phase), autoLevels=False, levels=(-1, 1))

    def _update_3d(self) -> None:
        if self.view_tabs.currentWidget() is not self.view3d or not self.view3d.available or self.result is None:
            if self.view_tabs.currentWidget() is self.view3d and self.result is not None and "extra" not in self.result \
                    and self.result["kind"] in ("level", "sti"):
                self.schedule()   # 3D braucht alle Hörflächen
            return
        maps = []
        kind = self.result["kind"]
        if kind in ("level", "sti"):
            entries = [(self.plane, self.result)] + list(self.result.get("extra", []))
            if kind == "level":
                allv = np.concatenate([e[1]["data"].ravel() for e in entries]) + self.sp_offset.value()
                hi = math.ceil(float(np.nanmax(allv)))
                lo, cmap = hi - self.sp_range.value(), CMAP
            else:
                lo, hi, cmap = 0.0, 1.0, CMAP_STI
            for p, res in entries:
                d = res["data"] + (self.sp_offset.value() if kind == "level" else 0)
                maps.append({"xs": res["xs"], "ys": res["ys"], "z": self.room.listen_height if p is None else p.z,
                             "rgba": _rgba(cmap, d, lo, hi)})
        self.view3d.show_scene(scene_data(self.room, self.speakers, self.planes, maps, self.points))

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
        v = ra.room_band_level(self.room, self.speakers, band, np.array(pt.x), np.array(pt.y),
                               np.array(self.room.listen_height), self.fraction, self.chk_room.isChecked())
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
        show = self.result is None or (self.result["kind"] in ("level", "sti", "mode") and self.plane is None) \
            or self.result["kind"] == "wave_top"
        pts = self.points if show else []
        self.pts_item.setData([p.x for p in pts], [p.y for p in pts])
        level_view = self.result is None or self.result["kind"] == "level"
        key = self.band_key() if self.band is not None else None
        for pt in pts:
            if level_view:
                pred = self.predicted_at(pt)
                txt = f"{pt.name}\n{pred:.1f} dB"
                if key in pt.measured:
                    txt += f" | gem. {pt.measured[key]:.1f} (Δ {pt.measured[key] - pred:+.1f})"
            else:
                txt = pt.name
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
        if self.result is None or not vb.sceneBoundingRect().contains(pos):
            self.hover.hide()
            return
        p = vb.mapSceneToView(pos)
        xs, ys, data = self.result["xs"], self.result["ys"], self.result["data"]
        if not (xs[0] <= p.x() <= xs[-1] and ys[0] <= p.y() <= ys[-1]):
            self.hover.hide()
            return
        i = int(np.clip(np.searchsorted(ys, p.y()), 0, len(ys) - 1))
        j = int(np.clip(np.searchsorted(xs, p.x()), 0, len(xs) - 1))
        kind = self.result["kind"]
        if kind == "level":
            val = f"<b>{data[i, j] + self.sp_offset.value():.1f} dB</b>"
        elif kind == "sti":
            val = f"<b>STI {data[i, j]:.2f}</b> ({sti_rating(float(data[i, j]))})"
        elif kind.startswith("wave"):
            val = f"<b>{20 * np.log10(abs(self.result['field'][i, j]) + 1e-12):.1f} dB</b>"
        else:
            val = f"<b>{data[i, j]:.1f} dB</b> rel."
        coords = (f"y {p.x():.1f} m · z {p.y():.1f} m" if kind == "wave_section"
                  else f"x {p.x():.1f} m · y {p.y():.1f} m")
        self.hover.setText(f"{coords} · {val}")
        self.hover.adjustSize()
        wp = self.plot.mapFromScene(pos)
        self.hover.move(min(int(wp.x()) + 14, self.plot.width() - self.hover.width() - 4), max(0, int(wp.y()) - 30))
        self.hover.show()
        self.hover.raise_()

    # --- Sitzung -----------------------------------------------------------------------
    def get_state(self) -> tuple[dict, dict]:
        return {"model": rm.to_dict(self.room, self.speakers, self.points, self.planes),
                "controls": controls_state(self)}, {}

    def set_state(self, meta: dict, arrays: dict) -> None:
        if meta.get("model"):
            self.room, self.speakers, self.points = rm.from_dict(meta["model"])
            self.planes = rm.planes_from_dict(meta["model"])
        else:
            self.room = rm.Room()
            self.speakers, self.points, self.planes = example_setup(self.room), [], []
        room = copy.deepcopy(self.room)
        apply_controls_state(self, meta.get("controls", {}))
        self.room = room                       # Modell hat Vorrang vor den gespeicherten Feldern
        self._fill_room_spins()
        self._fill_planes()
        self._fill_modes()
        self._update_rt_label()
        self._fill_table()
        self._refresh_points()
        self._view_changed()
