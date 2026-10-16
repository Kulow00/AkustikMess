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
               points: list[rm.MeasPoint]) -> dict:
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
    return {"box": box, "stage": stage, "speakers": spk, "surfaces": surfaces, "points": pts,
            "plane_edges": plane_edges, "center": (w / 2, (l0 + l1) / 2, h / 3), "size": max(w, l1 - l0, h)}


class Room3DView(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.view = None
        self.items: list = []
        self._camera_set = False
        try:
            import pyqtgraph.opengl as gl  # noqa: PLC0415
            self.gl = gl
            self.view = gl.GLViewWidget()
            self.view.setBackgroundColor((15, 17, 20))
            lay.addWidget(self.view)
            hint = QtWidgets.QLabel("Drehen: linke Maustaste · Zoomen: Mausrad · Verschieben: mittlere Maustaste "
                                    "oder Strg + linke Maustaste")
            hint.setStyleSheet("color: gray;")
            lay.addWidget(hint)
        except Exception as exc:  # noqa: BLE001 – kein OpenGL verfügbar
            self.gl = None
            msg = QtWidgets.QLabel(f"3D-Ansicht nicht verfügbar (OpenGL fehlt):\n{exc}")
            msg.setAlignment(QtCore.Qt.AlignCenter)
            lay.addWidget(msg)

    @property
    def available(self) -> bool:
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
        if not self._camera_set:
            cx, cy, cz = data["center"]
            from pyqtgraph import Vector  # noqa: PLC0415
            # Blick von hinten aus dem Publikum schräg auf die Bühne, ganzer Raum im Bild
            v.setCameraPosition(pos=Vector(cx, cy, cz), distance=data["size"] * 2.3, elevation=32, azimuth=65)
            self._camera_set = True
