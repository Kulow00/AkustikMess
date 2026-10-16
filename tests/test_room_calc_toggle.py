"""Raum-Modus: Berechnung nur auf Knopfdruck, Seitenansicht und Abstrahlung der Tops."""

import pytest

from akustik.dsp import roommodel as rm
from akustik.gui.room3d import coverage_text, scene_data
from conftest import make_window, wait


@pytest.fixture
def room(tmp_path):
    app, w = make_window(tmp_path, start=False)
    w.tabs.setCurrentWidget(w.room)
    wait(app, 0.4)
    yield app, w, w.room
    w.close()


def test_no_calculation_until_switched_on(room):
    app, w, r = room
    assert not r.btn_calc.isChecked() and "starten" in r.btn_calc.text()
    assert r.result is None and r.paused.isVisible()
    job = r._job
    r.add_speaker("top")
    r.sp_wid.setValue(16)
    wait(app, 0.4)
    assert r._job == job and r.result is None and not r._workers                 # nichts gerechnet
    assert r.outline.getData()[0].max() == pytest.approx(16)                     # Geometrie trotzdem aktuell
    r.btn_calc.setChecked(True)
    for _ in range(60):
        wait(app, 0.1)
        if r.result is not None:
            break
    assert r.result is not None and not r.paused.isVisible() and "EIN" in r.btn_calc.text()
    r.btn_calc.setChecked(False)
    r.add_speaker("sub")
    assert r.paused.isVisible() and r.img.opacity() < 0.5                       # alte Karte abgeblendet


def test_side_view_and_coverage(room):
    app, w, r = room
    r.speakers[0].z, r.speakers[0].tilt, r.speakers[0].cov_v = 6.0, -15.0, 70.0
    d = scene_data(r.room, r.speakers, [], [], [])
    tops = [c for c in d["coverage"] if c["name"] == r.speakers[0].name]
    assert tops and tops[0]["vert"]["near"] == pytest.approx(4.8 / __import__("math").tan(__import__("math").radians(50)),
                                                              abs=0.05)
    assert "Achse trifft Hörhöhe" in coverage_text(d["coverage"])
    r.view_tabs.setCurrentWidget(r.view3d)
    wait(app, 0.1)
    if r.view3d.available:
        assert "−6-dB-Bereich" in r.view3d.info.text()
        r.view3d.set_camera("Seitenansicht")
        assert r.view3d.view.opts["fov"] == 6 and r.view3d.view.opts["elevation"] == 0
        r.view3d.chk_cov.setChecked(False)
        assert r.view3d.info.text() == ""
    # 2D-Längsschnitt zeigt die vertikale Abdeckung der Tops
    r.view_tabs.setCurrentWidget(r.plot)
    r.cb_view.setCurrentText("Wellenbild – Längsschnitt")
    r._draw_room()
    n_tops = sum(1 for s in r.speakers if s.kind == "top" and s.enabled)
    lines = [it for it in r.spk_items if it.__class__.__name__ == "PlotDataItem"]
    assert len(lines) >= 3 * n_tops


def test_polar_coverage_angles():
    from akustik.dsp import polar
    p = polar.make_polar("Hz;0;30;45;60;90\n2000;0;-3;-6;-10;-20\n")
    sp = rm.Speaker.top("T", polar=p)
    h, v = rm.coverage_angles(sp)
    assert h == pytest.approx(90, abs=1) and v == pytest.approx(90, abs=1)
