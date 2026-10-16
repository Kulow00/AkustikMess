"""Raum-Modus Stufe 2/3: STI, Wellenbild, Raummoden, Raumakustik, Hörflächen, Polardaten, 3D, Sitzung."""

import types

import numpy as np
import pytest

from akustik.dsp import roommodel as rm
from akustik.gui.room3d import scene_data
from conftest import make_window, wait


@pytest.fixture
def room(tmp_path):
    app, w = make_window(tmp_path, start=False)
    w.tabs.setCurrentWidget(w.room)
    yield app, w, w.room
    w.close()


def view(r, name):
    r.cb_view.setCurrentText(name)
    r.compute_now()
    return r.result


def test_sti_map(room):
    app, w, r = room
    res = view(r, "STI (Sprachverständlichkeit)")
    assert res["kind"] == "sti" and 0 <= np.nanmin(res["data"]) <= np.nanmax(res["data"]) <= 1
    assert "STI-Vorhersage" in r.lbl_stats.text() and "% der Fläche" in r.lbl_stats.text().replace("</b>", "")
    assert not r.f_view.isRowVisible(r.cb_band) and r.f_view.isRowVisible(r.cb_plane)


def test_wave_views_animate(room):
    app, w, r = room
    r.sp_wave.setValue(80)
    res = view(r, "Wellenbild – Draufsicht")
    assert res["kind"] == "wave_top" and "Wellenlänge 4.29 m" in r.lbl_stats.text()
    assert r._anim.isActive()
    before = r.img.image.copy()
    for _ in range(3):
        r._animate()
    assert not np.allclose(before, r.img.image)                     # Welle bewegt sich
    res = view(r, "Wellenbild – Längsschnitt")
    assert res["kind"] == "wave_section" and res["ys"][-1] == pytest.approx(r.room.height)
    assert "Höhe z" in r.plot.getPlotItem().getAxis("left").labelText
    view(r, "Pegel")
    assert not r._anim.isActive()


def test_room_modes_view(room):
    app, w, r = room
    assert r.cb_mode.count() > 5 and "Hz" in r.cb_mode.itemText(0)
    first = r._modes[0]
    assert first["f"] == pytest.approx(343 / (2 * (r.room.length + r.room.stage_depth)), abs=0.2)
    res = view(r, "Raummode")
    assert res["kind"] == "mode" and "Raummode" in r.lbl_stats.text()


def test_room_acoustics_raise_level_and_rt_from_measurement(room):
    app, w, r = room
    r.cb_band.setCurrentIndex(r.cb_band.findData(1000))
    pt = r.add_point("hinten", 7.0, 18.0)
    view(r, "Pegel")
    dry = r.predicted_at(pt)
    r.chk_refl.setChecked(True)
    assert r.chk_room.isChecked() and r.room.reflections
    r.compute_now()
    assert r.predicted_at(pt) > dry + 1
    assert "mit Raum" in r.lbl_stats.text() and "berechnet" in r.lbl_rt.text()
    res = types.SimpleNamespace(center=1000.0, t30=2.5, t20=2.4)
    r.impulse.results = [res, types.SimpleNamespace(center=500.0, t30=float("nan"), t20=2.0)]
    r.take_measured_rt()
    assert r.room.rt60 == {"1000": 2.5, "500": 2.0} and "gemessen" in r.lbl_rt.text()
    loud = r.predicted_at(pt)
    r.use_computed_rt()
    assert r.room.rt60 == {} and r.predicted_at(pt) < loud


def test_extra_plane_polar_and_session(room):
    app, w, r = room
    r.add_plane(rm.Plane("Empore", 0, 14, 14, 20, 4.5))
    assert r.cb_plane.count() == 2 and "Empore" in r.list_planes.item(0).text()
    r.cb_plane.setCurrentText("Empore")
    res = view(r, "Pegel")
    assert res["ys"][0] == pytest.approx(14) and res["xs"][-1] == pytest.approx(14)
    r.apply_polar([0], "Hz;0;45;90\n1000;0;-6;-15\n")
    assert r.speakers[0].polar and r.table.item(0, 15).text() == "Polardaten"
    r.room.rt60 = {"1000": 1.7}
    meta, arrays = w.collect_session()
    r.set_state({}, {})
    assert not r.planes and r.speakers[0].polar is None
    w.apply_session(meta, arrays)
    assert w.room.planes[0].name == "Empore" and w.room.speakers[0].polar["h"]["db"] == [[0.0, -6.0, -15.0]]
    assert w.room.room.rt60 == {"1000": 1.7}


def test_3d_scene(room):
    app, w, r = room
    r.add_plane(rm.Plane("Empore", 0, 14, 14, 20, 4.5))
    r.add_point("FOH", 7, 15)
    r.view_tabs.setCurrentWidget(r.view3d)
    r.compute_now()
    assert len(r.result.get("extra", [])) == 1                         # Parkett + Empore
    rgba = np.zeros((3, 4, 4), np.uint8)
    d = scene_data(r.room, r.speakers, r.planes, [{"xs": np.arange(4.0), "ys": np.arange(3.0), "z": 1.2,
                                                   "rgba": rgba}], r.points)
    assert d["box"].shape == (24, 3) and len(d["speakers"]) == len(r.speakers)
    assert d["points"].shape == (1, 3) and len(d["plane_edges"]) == 1 and d["surfaces"][0]["dx"] == 1.0
    if r.view3d.available:
        assert len(r.view3d.items) > 5
