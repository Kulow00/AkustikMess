"""Raummodell: Abstandsgesetz, Interferenz, Abstrahlung, Übergänge, Sub-Setups."""

import math

import numpy as np
import pytest

from akustik.dsp import roommodel as rm

ROOM = rm.Room(length=30, width=20, height=8, listen_height=1.2)


def at(speakers, band, x, y, z=None, fraction=1):
    return float(rm.band_level(speakers, band, np.array(x, float), np.array(y, float),
                               np.array(ROOM.listen_height if z is None else z, float), fraction))


def test_inverse_square_law_and_air():
    sp = rm.Speaker.top("T", x=10, y=0, z=1.2, cov_h=360, cov_v=360, f_low=0)
    l4, l8 = at([sp], 1000, 10, 4), at([sp], 1000, 10, 8)
    assert l4 - l8 == pytest.approx(6.02, abs=0.1)            # −6 dB je Abstandsverdopplung
    # Luftdämpfung bei 8 kHz auf 25 m messbar
    l8k_near, l8k_far = at([sp], 8000, 10, 1), at([sp], 8000, 10, 25)
    assert (l8k_near - l8k_far) - 20 * math.log10(25) > 2.0


def test_coherent_sum_and_cancellation():
    a = rm.Speaker.sub("A", x=9.0, y=0, z=1.2)
    b = rm.Speaker.sub("B", x=11.0, y=0, z=1.2)
    single = at([a], 63, 10, 10)
    assert at([a, b], 63, 10, 10) - single == pytest.approx(6.0, abs=0.3)   # gleich weit: +6 dB
    b.polarity = -1
    assert at([a, b], 63, 10, 10) - single < -20                            # gegenphasig: Auslöschung


def test_directivity_minus_6_at_edge():
    sp = rm.Speaker.top("T", x=10, y=0, z=1.2, cov_h=90, cov_v=90, f_low=0)
    on = at([sp], 4000, 10, 10)
    edge = at([sp], 4000, 10 + 10 * math.tan(math.radians(45)), 10)         # 45° = halber Öffnungswinkel
    r_on, r_edge = 10, 10 / math.cos(math.radians(45))
    assert (on - edge) - 20 * math.log10(r_edge / r_on) == pytest.approx(6.0, abs=0.5)
    behind = at([sp], 4000, 10, -5, 1.2)
    assert on - behind > 15


def test_lr4_crossover_sums_flat():
    f = np.array([50.0, 100.0, 200.0])
    total = rm.lr4(f, 100, "low") + rm.lr4(f, 100, "high")
    assert np.allclose(np.abs(total), 1.0, atol=1e-6)                       # Linkwitz-Riley: flach


def test_endfire_and_cardioid_reject_rear():
    for kind in ("Endfire", "Cardioid (Gradient)"):
        subs = rm.sub_setup(kind, ROOM, count=4, spacing=1.36, y=5, design_freq=63)
        front = at(subs, 63, 10, 15)
        rear = at(subs, 63, 10, 0.0)
        assert front - rear > 10, kind
    single = rm.sub_setup("Mitte (Stack)", ROOM, count=1, y=5)
    # einzelner Sub: nur Abstandsgesetz (vorn 10 m, hinten 5 m entfernt)
    assert at(single, 63, 10, 15) - at(single, 63, 10, 0.0) == pytest.approx(20 * math.log10(5 / 10), abs=0.5)


def test_lr_stacks_power_alley_and_arc_is_wider():
    lr = rm.sub_setup("L/R-Stacks", ROOM, count=2, y=0.5)
    assert len(lr) == 2 and lr[0].x < 5 and lr[1].x > 15
    line = rm.sub_setup("Linie (Broadside)", ROOM, count=6, spacing=1.5, y=0.5)
    arc = rm.sub_setup("Bogen per Delay (Arc)", ROOM, count=6, spacing=1.5, y=0.5, arc_deg=90)
    assert arc[0].delay_ms > 0 and arc[0].delay_ms == arc[-1].delay_ms and arc[2].delay_ms < arc[0].delay_ms
    # Bogen: seitlich (60° vom Zentrum) weniger Abfall als die gerade Linie
    def spread(subs):
        return at(subs, 80, 10, 12) - at(subs, 80, 10 + 9, 0.5 + 5)
    assert spread(arc) < spread(line)


def test_level_map_and_uniformity():
    sp = [rm.Speaker.top("L", x=3, y=0.5, z=3, azimuth=15), rm.Speaker.top("R", x=17, y=0.5, z=3, azimuth=-15)]
    xs, ys, lv = rm.level_map(ROOM, sp, "A")
    assert lv.shape == (len(ys), len(xs)) and np.isfinite(lv).all()
    u = rm.uniformity(lv)
    assert u["max"] > u["median"] > u["min"] and 0 < u["within"] <= 1


def test_roundtrip_and_measured_band():
    room = rm.Room(length=12)
    sp = [rm.Speaker.top("T", x=1)]
    pts = [rm.MeasPoint("Reihe 5", 3, 4, {"1000": 95.0}, "Kurve 1")]
    r2, s2, p2 = rm.from_dict(rm.to_dict(room, sp, pts))
    assert r2.length == 12 and s2[0].x == 1 and p2[0].measured["1000"] == 95.0
    edges = np.array([707.0, 1414.0, 2828.0])
    trace = {"freqs": edges, "mag": np.array([90.0, 80.0]), "stepped": True}
    assert rm.measured_band_level(trace, 1000) == pytest.approx(90.0, abs=0.01)
