"""Raumakustik im Raummodell: Spiegelquellen, Nachhall, STI, Moden, Wellenfeld, Polardaten."""

import math

import numpy as np
import pytest

from akustik.dsp import polar, roomacoustics as ra, roommodel as rm


def room(**kw):
    base = dict(length=20, width=12, height=6, stage_depth=4)
    base.update(kw)
    return rm.Room(**base)


def test_image_sources_mirror_and_attenuate():
    r = room(alpha_floor=0.36, alpha_walls=0.19, alpha_ceiling=0.75)
    sp = rm.Speaker.top("T", x=3, y=1, z=2.5, azimuth=20, tilt=-10)
    ims = ra.image_sources(r, [sp])
    assert len(ims) == 6
    floor = next(i for i in ims if i.z < 0)
    assert floor.z == pytest.approx(-2.5) and floor.tilt == pytest.approx(10)
    assert floor.level == pytest.approx(sp.level + 20 * math.log10(math.sqrt(1 - 0.36)))
    side = next(i for i in ims if i.x < 0)
    assert side.x == pytest.approx(-3) and side.azimuth == pytest.approx(-20)
    back = next(i for i in ims if i.y < r.y_min)
    assert back.y == pytest.approx(2 * r.y_min - 1) and back.azimuth == pytest.approx(160)


def test_rt60_sabine_and_measured():
    r = room(alpha_floor=0.2, alpha_walls=0.2, alpha_ceiling=0.2)
    v = 12 * 24 * 6
    s = 2 * 12 * 24 + 2 * 6 * 24 + 2 * 6 * 12
    assert ra.rt60(r, 500) == pytest.approx(0.161 * v / (0.2 * s), rel=0.03)
    assert ra.rt60(r, 8000) < ra.rt60(r, 500)                                 # Luftdämpfung
    r.rt60 = {"500": 1.0, "1000": 2.0}
    assert ra.rt60(r, 707) == pytest.approx(1.5, abs=0.01)


def test_reverb_adds_level_far_away():
    dry, wet = room(alpha_floor=0.6, alpha_walls=0.6, alpha_ceiling=0.6), room(alpha_floor=0.03, alpha_walls=0.03,
                                                                               alpha_ceiling=0.03)
    sp = [rm.Speaker.top("T", x=6, y=0.5, z=3)]
    X, Y, Z = np.array([6.0]), np.array([18.0]), np.array([1.2])
    direct = ra.room_band_level(dry, sp, 1000, X, Y, Z, with_room=False)[0]
    assert ra.room_band_level(dry, sp, 1000, X, Y, Z)[0] > direct
    assert ra.room_band_level(wet, sp, 1000, X, Y, Z)[0] > ra.room_band_level(dry, sp, 1000, X, Y, Z)[0] + 6
    wet.reflections = True
    assert len(ra.active_sources(wet, sp)) == 7


def test_sti_prediction_plausible():
    sp = [rm.Speaker.top("T", x=6, y=0.5, z=3, level=110)]
    X, Y, Z = np.array([6.0]), np.array([6.0]), np.array([1.2])
    dry = room(alpha_floor=0.5, alpha_walls=0.6, alpha_ceiling=0.7, noise_dba=30)
    church = room(alpha_floor=0.02, alpha_walls=0.02, alpha_ceiling=0.02, noise_dba=30)
    noisy = room(alpha_floor=0.5, alpha_walls=0.6, alpha_ceiling=0.7, noise_dba=105)
    assert ra.sti_map(dry, sp, X, Y, Z)[0] > 0.7
    assert ra.sti_map(church, sp, X, Y, Z)[0] < 0.45
    assert ra.sti_map(noisy, sp, X, Y, Z)[0] < 0.45


def test_room_modes():
    r = room(length=20, width=12, height=6, stage_depth=0)
    modes = ra.room_modes(r, 60)
    assert modes[0]["f"] == pytest.approx(343 / (2 * 20), abs=0.1) and modes[0]["kind"] == "axial"
    assert all(m["f"] <= 60 for m in modes)
    X, Y, Z = np.array([0.0, 6.0]), np.array([0.0, 0.0]), np.array([0.0, 0.0])
    shape = ra.mode_shape(r, (1, 0, 0), X, Y, Z)
    assert shape[0] > -1 and shape[1] < -40                                    # Wandmitte = Knoten


def test_wave_field_views():
    r = room(resolution=0.5)
    sp = [rm.Speaker.sub("S", x=6, y=0.5)]
    v = ra.compute_view(r, sp, "wave_top", wave_freq=80)
    assert v["data"].shape == v["field"].shape and np.abs(v["data"]).max() <= 1.0
    s = ra.compute_view(r, sp, "wave_section", wave_freq=80)
    assert s["xs"][0] == pytest.approx(r.y_min) and s["ys"][-1] == pytest.approx(r.height)
    sti = ra.compute_view(r, sp, "sti")
    assert 0 <= np.nanmin(sti["data"]) <= np.nanmax(sti["data"]) <= 1


def test_extra_listening_plane():
    r = room()
    plane = rm.Plane("Empore", 0, 14, 12, 20, 4.5)
    sp = [rm.Speaker.top("T", x=6, y=0.5, z=3)]
    v = ra.compute_view(r, sp, "level", band=1000, plane=plane)
    assert v["xs"][0] == 0 and v["ys"][0] == 14 and np.isfinite(v["data"]).all()


POLAR_H = """Hz;0;30;60;90;180
500;95,0;94,0;91,0;88,0;80,0
4000;100;97;88;80;70
"""


def test_polar_import_and_directivity():
    p = polar.make_polar(POLAR_H)
    assert p["h"]["db"][1] == [0.0, -3.0, -12.0, -20.0, -30.0]
    sp = rm.Speaker.top("T", x=0, y=0, z=0, polar=p)
    att = rm.directivity_db(sp, 4000, ang=(np.array([90.0]), np.array([0.0])))
    assert att[0] == pytest.approx(-20.0, abs=0.01)
    mid = rm.directivity_db(sp, math.sqrt(500 * 4000), ang=(np.array([90.0]), np.array([0.0])))
    assert -20 < mid[0] < -7
    with pytest.raises(polar.PolarError):
        polar.parse_polar("nur eine Zeile")
    assert polar.parse_polar("Hz 0 90\n1000 0 -6,5\n")[2] == [[0.0, -6.5]]
