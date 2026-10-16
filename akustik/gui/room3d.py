"""3D-Ansicht des Raummodells (drehen: linke Maustaste, zoomen: Mausrad, verschieben: mittlere Taste).

Die Szene wird zuerst als reine Daten beschrieben (``scene_data``, ohne OpenGL testbar) und dann
von ``Room3DView`` gezeichnet. Fehlt OpenGL (z. B. in virtuellen Maschinen), zeigt die Ansicht einen Hinweis.
"""

from __future__ import annotations

import math

import numpy as np
from PySide6 import QtCore, QtWidgets

from ..dsp import roommodel as rm


def _rgba(cmap, values: np.ndarray, lo: float, hi: float) -> np.ndarray:
    v = np.clip((np.nan_to_num(values, nan=lo) - lo) / max(hi - lo, 1e-9), 0, 1)
    return cmap.map(v, mode="byte")      # (…, 4) uint8


def scene_data(room: rm.Room, speakers: list[rm.Speaker], planes: list[rm.Plane], maps: list[dict],
               points: list[rm.MeasPoint], coverage: bool = True) -> dict:
    """Linien, Lautsprecher, Flächen (mit Farbdaten) und Messpunkte als Arrays."""
    w, l0, l1, h = room.width, room.y_min, room.length, room.height
    c = [(0, l0, 0), (w, l0, 0), (w, l1, 0), (0, l1, 0), (0, l0, h), (w, l0, h), (w, l1, h), (0, l1, h)]
    edges = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)]
    box = np.array([c[i] for e in edges for i in e], float)
    stage = np.array([(0, 0, 0), (w, 0, 0)], float)          # Bühnenkante
    spk = []
    for sp in speakers:
        a = math.radians(sp.azimuth)
        t = math.radians(sp.tilt)
        tip = (sp.x + 1.2 * math.sin(a) * math.cos(t), sp.y + 1.2 * math.cos(a) * math.cos(t), sp.z + 1.2 * math.sin(t))
        spk.append({"name": sp.name, "pos": (sp.x, sp.y, sp.z), "tip": tip, "sub": sp.kind == "sub",
                    "enabled": sp.enabled})
    surfaces = []
    for m in maps:
        xs, ys = m["xs"], m["ys"]
        surfaces.append({"x0": float(xs[0]), "y0": float(ys[0]), "dx": float(xs[1] - xs[0]) if len(xs) > 1 else 1.0,
                         "dy": float(ys[1] - ys[0]) if len(ys) > 1 else 1.0, "z": float(m["z"]),
                         "rgba": m["rgba"]})
    pts = np.array([(p.x, p.y, room.listen_height) for p in points], float).reshape(-1, 3)
    plane_edges = []
    for p in planes:
        plane_edges.append(np.array([(p.x0, p.y0, p.z), (p.x1, p.y0, p.z), (p.x1, p.y0, p.z), (p.x1, p.y1, p.z),
                                     (p.x1, p.y1, p.z), (p.x0, p.y1, p.z), (p.x0, p.y1, p.z), (p.x0, p.y0, p.z)]))
    cov = []
    if coverage:
        for sp in speakers:
            if sp.enabled and sp.kind == "top":
                c = rm.coverage_rays(room, sp, stop_z=room.listen_height)
                cov.append({"name": sp.name, "pos": c["pos"], "axis": c["axis"], "edges": c["edges"],
                            "corners": c["corners"], "cov": c["cov"], "vert": rm.vertical_coverage(room, sp)})
    return {"box": box, "stage": stage, "speakers": spk, "surfaces": surfaces, "points": pts,
            "plane_edges": plane_edges, "coverage": cov, "center": (w / 2, (l0 + l1) / 2, h / 2),
            "size": max(w, l1 - l0, h), "dims": (w, l1 - l0, h)}


def coverage_text(cov: list[dict]) -> str:
    """Kurzfassung: wo die Tops die Hörhöhe treffen."""
    lines = []
    for c in cov:
        v = c["vert"]
        fmt = lambda d: f"{d:.1f} m" if d is not None else "– (darüber)"  # noqa: E731
        lines.append(f"<b>{c['name']}</b> ({c['cov'][0]:.0f}° × {c['cov'][1]:.0f}°): Achse trifft Hörhöhe nach "
                     f"{fmt(v['axis'])}, −6-dB-Bereich {fmt(v['near'])} bis {fmt(v['far'])}")
    return "<br>".join(lines) or "Keine aktiven Tops."


# Kamera-Vorgaben: (Name, Höhenwinkel, Azimut, Sichtfeld) – kleines Sichtfeld + große Entfernung ≈ Parallelprojektion
VIEWS_3D = {"Perspektive": (32, 65, 60), "Seitenansicht": (0, 0, 6), "Draufsicht": (90, -90, 6),
            "Von hinten (Publikum)": (8, 90, 40), "Von der Bühne": (12, -90, 40)}


class Room3DView(QtWidgets.QWidget):
    coverage_toggled = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._last: dict | None = None
        self.lay = lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.view = None
        self.gl = None
        self._tried = False        # OpenGL wird erst beim ersten Gebrauch geladen (schnellerer Programmstart)
        self.items: list = []
        self._camera_set = False
        bar = QtWidgets.QHBoxLayout()
        bar.addWidget(QtWidgets.QLabel("Ansicht:"))
        for name in VIEWS_3D:
            b = QtWidgets.QPushButton(name)
            b.clicked.connect(lambda _=False, n=name: self.set_camera(n))
            bar.addWidget(b)
        self.chk_cov = QtWidgets.QCheckBox("Abstrahlung der Tops (−6 dB) zeigen")
        self.chk_cov.setChecked(True)
        self.chk_cov.toggled.connect(lambda _: self.coverage_toggled.emit())
        bar.addWidget(self.chk_cov)
        bar.addStretch(1)
        lay.addLayout(bar)
        self.slot = QtWidgets.QVBoxLayout()           # hier kommt das 3D-Bild hinein
        lay.addLayout(self.slot, 1)
        self.info = QtWidgets.QLabel()
        self.info.setWordWrap(True)
        self.info.setMaximumHeight(90)
        self.info.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        lay.addWidget(self.info)
        hint = QtWidgets.QLabel("Drehen: linke Maustaste · Zoomen: Mausrad · Verschieben: mittlere Maustaste "
                                "oder Strg + linke Maustaste. Seitenansicht: Blick quer durch den Raum – "
                                "zeigt, wie hoch die Tops strahlen und wo die −6-dB-Kanten die Hörhöhe treffen.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        lay.addWidget(hint)

    def _ensure_gl(self) -> None:
        if self._tried:
            return
        self._tried = True
        try:
            import pyqtgraph.opengl as gl  # noqa: PLC0415
            self.gl = gl
            self.view = gl.GLViewWidget()
            self.view.setBackgroundColor((15, 17, 20))
            self.slot.addWidget(self.view, 1)
        except Exception as exc:  # noqa: BLE001 – kein OpenGL verfügbar
            self.gl, self.view = None, None
            msg = QtWidgets.QLabel(f"3D-Ansicht nicht verfügbar (OpenGL fehlt):\n{exc}")
            msg.setAlignment(QtCore.Qt.AlignCenter)
            self.slot.addWidget(msg, 1)

    def showEvent(self, event) -> None:  # noqa: N802
        self._ensure_gl()
        super().showEvent(event)

    @property
    def available(self) -> bool:
        self._ensure_gl()
        return self.view is not None

    def show_scene(self, data: dict) -> None:
        if not self.available:
            return
        gl, v = self.gl, self.view
        for it in self.items:
            v.removeItem(it)
        self.items = []

        def add(item):
            v.addItem(item)
            self.items.append(item)

        add(gl.GLLinePlotItem(pos=data["box"], mode="lines", color=(0.85, 0.85, 0.85, 1), width=1.5))
        add(gl.GLLinePlotItem(pos=data["stage"], mode="lines", color=(1.0, 0.8, 0.2, 1), width=3))
        for pe in data["plane_edges"]:
            add(gl.GLLinePlotItem(pos=pe, mode="lines", color=(0.6, 0.8, 1.0, 1), width=1.5))
        for s in data["surfaces"]:
            img = gl.GLImageItem(np.ascontiguousarray(np.transpose(s["rgba"], (1, 0, 2))), smooth=True)
            img.scale(s["dx"], s["dy"], 1)
            img.translate(s["x0"] - s["dx"] / 2, s["y0"] - s["dy"] / 2, s["z"])
            add(img)
        for sp in data["speakers"]:
            col = (1.0, 0.44, 0.26, 1) if sp["sub"] else (0.31, 0.76, 0.97, 1)
            if not sp["enabled"]:
                col = (0.5, 0.5, 0.5, 1)
            add(gl.GLScatterPlotItem(pos=np.array([sp["pos"]]), color=col, size=14 if sp["sub"] else 11))
            add(gl.GLLinePlotItem(pos=np.array([sp["pos"], sp["tip"]]), color=col, width=2))
            if hasattr(gl, "GLTextItem"):
                add(gl.GLTextItem(pos=np.array(sp["pos"]) + np.array([0, 0, 0.35]), text=sp["name"],
                                  color=(255, 255, 255, 255)))
        if len(data["points"]):
            add(gl.GLScatterPlotItem(pos=data["points"], color=(1, 1, 1, 1), size=9))
        for c in data.get("coverage", []):
            p0 = c["pos"]
            add(gl.GLLinePlotItem(pos=np.array([p0, c["axis"]]), color=(1.0, 1.0, 1.0, 0.9), width=2))
            seg = []
            for e in c["edges"].values():
                seg += [p0, e]
            add(gl.GLLinePlotItem(pos=np.array(seg), mode="lines", color=(0.31, 0.76, 0.97, 0.9), width=1.5))
            cn = c["corners"]
            ring = [cn[0], cn[1], cn[1], cn[2], cn[2], cn[3], cn[3], cn[0]] + [x for k in cn for x in (p0, k)]
            add(gl.GLLinePlotItem(pos=np.array(ring), mode="lines", color=(0.31, 0.76, 0.97, 0.35), width=1))
            verts = np.array([p0, *cn])
            faces = np.array([[0, 1, 2], [0, 2, 3], [0, 3, 4], [0, 4, 1]])
            add(gl.GLMeshItem(vertexes=verts, faces=faces, color=(0.31, 0.76, 0.97, 0.10), smooth=False,
                              drawEdges=False, glOptions="translucent"))
        self.info.setText(coverage_text(data.get("coverage", [])) if data.get("coverage") else "")
        self._last = data
        if not self._camera_set:
            self.set_camera("Perspektive")
            self._camera_set = True

    def set_camera(self, name: str) -> None:
        if not self.available or self._last is None:
            return
        from pyqtgraph import Vector  # noqa: PLC0415
        elev, azim, fov = VIEWS_3D[name]
        cx, cy, cz = self._last["center"]
        size = self._last["size"]
        w, depth, h = self._last.get("dims", (size, size, size))
        # sichtbare Ausdehnung (waagrecht, senkrecht) je Ansicht – so wählen, dass beides ins Bild passt
        ext = {"Seitenansicht": (depth, h), "Draufsicht": (w, depth), "Von hinten (Publikum)": (w, h * 1.6),
               "Von der Bühne": (w, h * 1.6)}.get(name, (size * 1.3, size))
        aspect = max(self.view.width(), 1) / max(self.view.height(), 1)
        half = 0.58 * max(ext[0], ext[1] * aspect)                      # fov gilt waagrecht
        dist = half / math.tan(math.radians(fov / 2))
        self.view.opts["fov"] = fov
        self.view.setCameraPosition(pos=Vector(cx, cy, cz), distance=dist, elevation=elev, azimuth=azim)
        self.current_camera = name
