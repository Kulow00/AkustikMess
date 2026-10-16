"""Raum-Modus in der Oberfläche: Karte, Tabelle, Sub-Setups, Messpunkte, Sitzung."""

import re

import numpy as np
import pytest
from PySide6 import QtCore

from akustik.dsp import roommodel as rm
from conftest import make_window, wait


@pytest.fixture
def room(tmp_path):
    app, w = make_window(tmp_path, start=False)
    w.tabs.setCurrentWidget(w.room)
    yield app, w, w.room
    w.close()


def test_map_and_table_editing(room):
    app, w, r = room
    r.compute_now()
    xs, ys, lv = r.map
    assert lv.shape == (len(ys), len(xs)) and ys[0] < 0 < ys[-1]          # Bühne + Publikum
    assert "der Fläche" in r.lbl_stats.text() and "Bühne" in r.lbl_stats.text()
    n = len(r.speakers)
    r.add_speaker("top")
    assert len(r.speakers) == n + 1 and r.table.rowCount() == n + 1
    from akustik.gui.room_view import COLUMNS
    col = [c[0] for c in COLUMNS].index("delay_ms")
    r.table.item(n, col).setText("2,5")                                    # Komma wird akzeptiert
    assert r.speakers[n].delay_ms == 2.5 and r.table.item(n, col).text() == "2.5"
    r.table.selectRow(n)
    r.remove_speaker()
    assert len(r.speakers) == n


def test_cardioid_quiet_on_stage(room):
    app, w, r = room
    r.cb_sub.setCurrentText("Cardioid (Gradient)")
    r.sp_sub_n.setValue(4)
    r.sp_sub_y.setValue(1.0)
    r.generate_subs()
    assert sum(s.kind == "sub" for s in r.speakers) == 4 and any(s.polarity == -1 for s in r.speakers)
    assert r.band == 63.0
    for s in r.speakers:                                                   # nur die Subs betrachten
        s.enabled = s.kind == "sub"
    r.compute_now()
    diff = float(re.search(r"\(([-+]\d+\.\d) dB zum Publikum\)", r.lbl_stats.text()).group(1))
    assert diff < -6, r.lbl_stats.text()


def test_measurement_points_and_alignment(room):
    app, w, r = room
    r.cb_band.setCurrentIndex(r.cb_band.findData(1000))
    r.compute_now()
    pt = r.add_point("Reihe 10", 7.0, 10.0)
    pred = r.predicted_at(pt)
    # gespeichertes Spektrum (Terzen, kalibriert): 6 dB lauter als vorhergesagt
    trace = {"name": "Reihe 10 – Spektrum", "kind": "spec", "freqs": np.array([707.1, 1414.2]),
             "mag": np.array([pred + 6.0]), "stepped": True}
    r.assign_trace(pt, trace)
    assert pt.measured["1000"] == pytest.approx(pred + 6.0, abs=0.01) and pt.source.startswith("Reihe 10")
    r._refresh_points()
    assert "Δ +6.0 dB" in r.list_pts.item(0).text()
    r.align_to_measurements()
    assert r.sp_offset.value() == pytest.approx(6.0, abs=0.05)
    r._refresh_points()
    assert "Δ +0.0 dB" in r.list_pts.item(0).text() or "Δ -0.0 dB" in r.list_pts.item(0).text()


def test_session_roundtrip(room):
    app, w, r = room
    r.sp_wid.setValue(18.0)
    r.cb_sub.setCurrentText("Endfire")
    r.generate_subs()
    r.add_point("FOH", 9.0, 15.0).measured["A"] = 98.0
    meta, arrays = w.collect_session()
    w.room.set_state({}, {})                                               # neue Sitzung
    assert len(w.room.points) == 0 and w.room.room.width == rm.Room().width
    w.apply_session(meta, arrays)
    assert w.room.room.width == 18.0 and w.room.sp_wid.value() == 18.0
    assert any(s.delay_ms > 0 for s in w.room.speakers if s.kind == "sub")
    assert w.room.points[0].name == "FOH" and w.room.points[0].measured["A"] == 98.0


def test_hover_and_place_point(room, monkeypatch):
    app, w, r = room
    r.compute_now()
    w.resize(1500, 950)
    wait(app, 0.1)
    vb = r.plot.getViewBox()
    pos = vb.mapViewToScene(QtCore.QPointF(7.0, 10.0))
    r._mouse_moved(pos)
    assert r.hover.isVisible() and "dB" in r.hover.text()
    from PySide6 import QtWidgets
    monkeypatch.setattr(QtWidgets.QInputDialog, "getText", lambda *a, **k: ("Mitte", True))
    r.btn_place.setChecked(True)

    class Ev:
        def button(self):
            return QtCore.Qt.LeftButton

        def scenePos(self):
            return pos
    r._mouse_clicked(Ev())
    assert r.points[-1].name == "Mitte" and r.points[-1].x == pytest.approx(7.0, abs=0.1)
    assert not r.btn_place.isChecked()
