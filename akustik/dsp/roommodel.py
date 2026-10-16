"""Raummodell: Pegelvorhersage von Lautsprechern auf einer Hörfläche (Stufe 1).

Modell
------
* Rechteckraum, Koordinaten in Metern: x = Breite (0 … W, von links nach rechts von der Bühne aus
  gesehen), y = Tiefe (0 = Bühnenkante … L), z = Höhe. Hörfläche in Höhe ``listen_height``.
* Jeder Lautsprecher ist eine Punktquelle mit
  – Pegel (dB SPL in 1 m auf Achse, rosa Rauschen im Arbeitsbereich),
  – Hoch-/Tiefpass als Linkwitz-Riley 4. Ordnung (Betrag **und Phase** → realistische Übergänge),
  – Abstrahlung über Öffnungswinkel horizontal/vertikal (−6 dB an der Kante), zu tiefen Frequenzen
    hin immer breiter bis kugelförmig (Subwoofer: kugelförmig),
  – Ausrichtung (Richtung, Neigung), Delay und Polarität.
* Alle Quellen werden je Frequenz **komplex** addiert (Laufzeit, Delay, Polarität, Filterphase):
  Interferenzen, Power-Alley, Endfire/Cardioid-Wirkung werden sichtbar.
* Bandpegel = Energiemittel über mehrere Frequenzen im Band. Breitband = energetische Summe der
  Oktavbänder mit A-Bewertung.
* Freifeld ohne Reflexionen (Raumwände begrenzen hier nur die Fläche; Reflexionen, Moden und
  Nachhall folgen in Stufe 2), Luftdämpfung nach ISO 9613-1 (20 °C, 50 % r. F., genähert).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import numpy as np

from .weighting import weighting_db

C = 343.0                     # Schallgeschwindigkeit m/s (20 °C)
OCTAVES = (31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)
THIRDS = tuple(round(1000 * 2 ** (k / 3), 1) for k in range(-15, 13))   # 31,5 Hz … 16 kHz
DIR_FREQ = 800.0              # darunter wird die Abstrahlung breiter (vereinfachtes Modell)
MIN_DIST = 0.5                # Nahfeld begrenzen
REAR_FLOOR_DB = -24.0         # stärkste Dämpfung nach hinten
# Luftdämpfung dB/m (ISO 9613-1, 20 °C, 50 % r. F., je Oktave genähert)
_AIR_F = np.array([63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000], float)
_AIR_DB = np.array([0.0001, 0.0004, 0.001, 0.0019, 0.0037, 0.0097, 0.0328, 0.117, 0.40])


@dataclass
class Room:
    length: float = 20.0      # Tiefe (y)
    width: float = 14.0       # Breite (x)
    height: float = 6.0
    listen_height: float = 1.2
    resolution: float = 0.25  # Rasterweite der Karte in m
    stage_depth: float = 5.0  # Bühne hinter y = 0 (mit berechnet: wie laut ist es auf der Bühne?)
    # Raumakustik (Stufe 2)
    reflections: bool = False         # Spiegelquellen 1. Ordnung (Wände, Boden, Decke)
    alpha_floor: float = 0.10         # Absorptionsgrad (breitbandig)
    alpha_walls: float = 0.15
    alpha_ceiling: float = 0.30
    rt60: dict = field(default_factory=dict)   # gemessene Nachhallzeit je Oktave {"125": 1.2, …}
    noise_dba: float = 35.0           # Störgeräusch für die STI-Vorhersage

    @property
    def y_min(self) -> float:
        return -max(self.stage_depth, 0.0)


@dataclass
class Plane:
    """Weitere Hörfläche (z. B. Empore): Rechteck in der Draufsicht, Ohrhöhe über dem Hallenboden."""
    name: str = "Empore"
    x0: float = 0.0
    y0: float = 14.0
    x1: float = 14.0
    y1: float = 20.0
    z: float = 4.5


@dataclass
class Speaker:
    name: str = "Top"
    kind: str = "top"         # "top" | "sub"
    x: float = 7.0
    y: float = 0.5
    z: float = 2.5
    azimuth: float = 0.0      # Grad; 0 = in den Raum (+y), positiv = nach rechts (+x)
    tilt: float = 0.0         # Grad; negativ = nach unten
    level: float = 120.0      # dB SPL @ 1 m auf Achse (Breitband im Arbeitsbereich)
    delay_ms: float = 0.0
    polarity: int = 1         # +1 / −1
    cov_h: float = 90.0       # Öffnungswinkel horizontal (−6 dB, Grad)
    cov_v: float = 60.0       # vertikal
    f_low: float = 80.0       # Hochpass (Hz), 0 = keiner
    f_high: float = 0.0       # Tiefpass (Hz), 0 = keiner
    enabled: bool = True
    polar: dict | None = None  # gemessene Abstrahlung (siehe dsp/polar.py), ersetzt die Öffnungswinkel

    @staticmethod
    def top(name="Top", **kw) -> "Speaker":
        return Speaker(name=name, kind="top", **kw)

    @staticmethod
    def sub(name="Sub", **kw) -> "Speaker":
        base = dict(z=0.4, level=124.0, cov_h=360.0, cov_v=360.0, f_low=30.0, f_high=100.0)
        base.update(kw)
        return Speaker(name=name, kind="sub", **base)


@dataclass
class MeasPoint:
    name: str
    x: float
    y: float
    measured: dict = field(default_factory=dict)   # Band-Schlüssel → gemessener Pegel (dB)
    source: str = ""                                # z. B. Name der gespeicherten Messkurve


# --- Filter und Abstrahlung -----------------------------------------------------------------

def lr4(f: np.ndarray, fc: float, kind: str) -> np.ndarray:
    """Linkwitz-Riley 4. Ordnung (= Butterworth 2. Ordnung quadriert), komplex."""
    if not fc:
        return np.ones_like(f, dtype=complex)
    s = 1j * f / fc
    bw2 = 1 / (s * s + math.sqrt(2) * s + 1)          # Butterworth-Tiefpass 2. Ordnung
    h = bw2 if kind == "low" else bw2 * s * s          # Hochpass: s²/(…)
    return h * h


def response(sp: Speaker, f: np.ndarray) -> np.ndarray:
    return lr4(f, sp.f_low, "high") * lr4(f, sp.f_high, "low")


def axes(sp: Speaker) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Einheitsvektoren (Achse, rechts, oben) des Lautsprechers."""
    az, tl = math.radians(sp.azimuth), math.radians(sp.tilt)
    a = np.array([math.sin(az) * math.cos(tl), math.cos(az) * math.cos(tl), math.sin(tl)])
    r = np.array([math.cos(az), -math.sin(az), 0.0])
    u = np.cross(r, a)
    return a, r, u


def angles(sp: Speaker, dx, dy, dz) -> tuple[np.ndarray, np.ndarray]:
    """Winkel (Grad) horizontal/vertikal zur Achse für Richtungsvektoren (dx, dy, dz)."""
    a, r, u = axes(sp)
    da = dx * a[0] + dy * a[1] + dz * a[2]
    dr = dx * r[0] + dy * r[1] + dz * r[2]
    du = dx * u[0] + dy * u[1] + dz * u[2]
    return np.degrees(np.arctan2(dr, da)), np.degrees(np.arctan2(du, np.hypot(da, dr)))


def directivity_db(sp: Speaker, f: float, dx=None, dy=None, dz=None, ang=None) -> np.ndarray:
    """Dämpfung (dB ≤ 0) in Richtung (dx, dy, dz) bzw. für vorberechnete Winkel bei Frequenz f."""
    widen = max(1.0, DIR_FREQ / f) if f > 0 else 8.0
    h = min(360.0, sp.cov_h * widen)
    v = min(360.0, sp.cov_v * widen)
    th, tv = ang if ang is not None else angles(sp, dx, dy, dz)
    if sp.polar:
        from .polar import polar_att_db  # noqa: PLC0415
        return polar_att_db(sp.polar, f, th, tv)
    if h >= 360 and v >= 360 and sp.kind == "sub":
        return np.zeros(np.shape(th))
    att = -6.0 * ((th / (h / 2)) ** 2 + (tv / (v / 2)) ** 2)
    return np.maximum(att, REAR_FLOOR_DB)


def air_db_per_m(f: float) -> float:
    return float(np.interp(np.log10(max(f, 20)), np.log10(_AIR_F), _AIR_DB))


def _band_freqs(fc: float, fraction: int) -> np.ndarray:
    n = 7 if fraction == 1 else 3
    return fc * 2 ** (np.linspace(-0.5, 0.5, n + 2)[1:-1] / fraction)


def _band_norm(sp: Speaker) -> float:
    """Pegelverteilung: ``level`` ist der Breitbandpegel (rosa) im Arbeitsbereich des Lautsprechers."""
    e = sum(float(np.mean(np.abs(response(sp, _band_freqs(fc, 1))) ** 2)) for fc in OCTAVES)
    return 1.0 / max(e, 1e-9)


# --- Berechnung -----------------------------------------------------------------------------

def geometry(speakers: list[Speaker], px, py, pz) -> list:
    """Je aktivem Lautsprecher: (Lautsprecher, Abstand, Winkel, Pegelnorm) – einmal je Karte rechnen."""
    out = []
    for sp in speakers:
        if not sp.enabled:
            continue
        dx, dy, dz = px - sp.x, py - sp.y, pz - sp.z
        r = np.maximum(np.sqrt(dx * dx + dy * dy + dz * dz), MIN_DIST)
        out.append((sp, r, angles(sp, dx / r, dy / r, dz / r), 10 * math.log10(_band_norm(sp))))
    return out


def pressure(speakers: list[Speaker], f: float, px=None, py=None, pz=None, geo=None) -> np.ndarray:
    """Komplexer Schalldruck (Pa-proportional) aller Lautsprecher bei Frequenz f an Punkten p."""
    geo = geo if geo is not None else geometry(speakers, px, py, pz)
    k = 2 * math.pi * f / C
    total = None
    for sp, r, ang, norm in geo:
        h = response(sp, np.array([f]))[0] * sp.polarity
        lvl = sp.level + norm + directivity_db(sp, f, ang=ang)
        amp = 10 ** ((lvl - air_db_per_m(f) * r) / 20) / r
        term = amp * h * np.exp(-1j * (k * r + 2 * math.pi * f * sp.delay_ms * 1e-3))
        total = term if total is None else total + term
    if total is None:
        return np.zeros(np.broadcast(px, py, pz).shape if px is not None else (), complex)
    return total


def band_level(speakers, band, px, py, pz, fraction: int = 1, geo=None) -> np.ndarray:
    """Pegel (dB SPL) im Band ``band`` (Mittenfrequenz) oder Breitband A (``band="A"``)."""
    geo = geo if geo is not None else geometry(speakers, px, py, pz)
    if not geo:
        return np.full(np.broadcast(px, py, pz).shape, np.nan)
    if band == "A":
        e = 0.0
        for fc in OCTAVES:
            e = e + 10 ** ((band_level(speakers, fc, px, py, pz, 1, geo) + float(weighting_db(fc, "A"))) / 10)
        return 10 * np.log10(e + 1e-30)
    e = 0.0
    freqs = _band_freqs(float(band), fraction)
    for f in freqs:
        e = e + np.abs(pressure(speakers, f, geo=geo)) ** 2
    # Leistung des Bandes: Mittel über die Stützfrequenzen × Bandanteil (1/n der Oktave)
    return 10 * np.log10(e / len(freqs) / (1 if fraction == 1 else fraction) + 1e-30)


def plane_grid(plane: Plane, resolution: float) -> tuple[np.ndarray, np.ndarray]:
    w, d = abs(plane.x1 - plane.x0), abs(plane.y1 - plane.y0)
    nx = max(2, int(round(w / resolution)) + 1)
    ny = max(2, int(round(d / resolution)) + 1)
    if nx * ny > 60000:
        s = math.sqrt(nx * ny / 60000)
        nx, ny = max(2, int(nx / s)), max(2, int(ny / s))
    return (np.linspace(min(plane.x0, plane.x1), max(plane.x0, plane.x1), nx),
            np.linspace(min(plane.y0, plane.y1), max(plane.y0, plane.y1), ny))


def grid(room: Room) -> tuple[np.ndarray, np.ndarray]:
    depth = room.length + max(room.stage_depth, 0.0)
    nx = max(2, int(round(room.width / room.resolution)) + 1)
    ny = max(2, int(round(depth / room.resolution)) + 1)
    if nx * ny > 60000:   # Rechenzeit begrenzen
        s = math.sqrt(nx * ny / 60000)
        nx, ny = max(2, int(nx / s)), max(2, int(ny / s))
    return np.linspace(0, room.width, nx), np.linspace(-max(room.stage_depth, 0.0), room.length, ny)


def level_map(room: Room, speakers, band, fraction: int = 1) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(x-Achse, y-Achse, Pegel[y, x]) auf der Hörfläche."""
    xs, ys = grid(room)
    X, Y = np.meshgrid(xs, ys)
    return xs, ys, band_level(speakers, band, X, Y, np.full_like(X, room.listen_height), fraction)


def uniformity(levels: np.ndarray, tol: float = 3.0) -> dict:
    v = levels[np.isfinite(levels)]
    if not len(v):
        return {}
    med = float(np.median(v))
    return {"median": med, "min": float(v.min()), "max": float(v.max()),
            "within": float(np.mean(np.abs(v - med) <= tol)), "std": float(v.std())}


# --- Sub-Setups ---------------------------------------------------------------------------

SUB_SETUPS = ("L/R-Stacks", "Mitte (Stack)", "Linie (Broadside)", "Bogen per Delay (Arc)",
              "Endfire", "Cardioid (Gradient)")


def sub_setup(kind: str, room: Room, count: int = 4, spacing: float = 1.2, y: float = 0.5, z: float = 0.4,
              level: float = 124.0, crossover: float = 100.0, design_freq: float = 63.0,
              arc_deg: float = 60.0) -> list[Speaker]:
    """Erzeugt Subwoofer nach gängigen Mustern (Bühnenkante bei y, Raummitte bei x = W/2)."""
    cx = room.width / 2
    mk = lambda name, **kw: Speaker.sub(name, z=z, level=level, f_high=crossover, **kw)  # noqa: E731
    count = max(1, int(count))
    if kind == "L/R-Stacks":
        half = max(1, count // 2)
        xl, xr = min(1.5, room.width * 0.15), room.width - min(1.5, room.width * 0.15)
        return ([mk(f"Sub L{i + 1}", x=xl, y=y) for i in range(half)]
                + [mk(f"Sub R{i + 1}", x=xr, y=y) for i in range(half)])
    if kind == "Mitte (Stack)":
        return [mk(f"Sub {i + 1}", x=cx, y=y) for i in range(count)]
    if kind in ("Linie (Broadside)", "Bogen per Delay (Arc)"):
        xs = cx + (np.arange(count) - (count - 1) / 2) * spacing
        subs = [mk(f"Sub {i + 1}", x=float(xi), y=y) for i, xi in enumerate(xs)]
        if kind.startswith("Bogen") and count > 1 and arc_deg > 0:
            # virtueller Bogen (zum Publikum gewölbt): äußere Subs so verzögert, als stünden sie auf
            # einem Kreisbogen weiter hinten → breitere, gleichmäßigere Abdeckung statt schmaler Keule
            half_w = (count - 1) / 2 * spacing
            radius = half_w / math.sin(math.radians(min(arc_deg, 179) / 2))
            for sp in subs:
                dx = sp.x - cx
                sag = radius - math.sqrt(max(radius ** 2 - dx ** 2, 0))
                sp.delay_ms = round(sag / C * 1000, 2)
        return subs
    if kind == "Endfire":
        # Reihe in Abstrahlrichtung; vordere Subs um den Laufweg verzögert → Addition nach vorn
        # Sub 1 steht hinten (an der Bühnenkante), jeder weiter vorn stehende um den Laufweg verzögert
        return [mk(f"Sub {i + 1}", x=cx, y=round(y + i * spacing, 3), delay_ms=round(i * spacing / C * 1000, 2))
                for i in range(count)]
    if kind == "Cardioid (Gradient)":
        # Paare: vorne normal, dahinter (Abstand = λ/4 bei design_freq) invertiert + Laufzeit
        d = round(C / design_freq / 4, 2)
        pairs = max(1, count // 2)
        xs = cx + (np.arange(pairs) - (pairs - 1) / 2) * spacing
        subs = []
        for i, xi in enumerate(xs):
            subs.append(mk(f"Sub {i + 1} vorn", x=float(xi), y=y + d))
            subs.append(mk(f"Sub {i + 1} hinten", x=float(xi), y=y, polarity=-1,
                           delay_ms=round(d / C * 1000, 2)))
        return subs
    raise ValueError(f"Unbekanntes Sub-Setup: {kind}")


def to_dict(room: Room, speakers: list[Speaker], points: list[MeasPoint], planes: list[Plane] = ()) -> dict:
    return {"room": asdict(room), "speakers": [asdict(s) for s in speakers], "points": [asdict(p) for p in points],
            "planes": [asdict(p) for p in planes]}


def _pick(cls, data):
    names = cls.__dataclass_fields__
    return cls(**{k: v for k, v in (data or {}).items() if k in names})


def from_dict(d: dict) -> tuple[Room, list[Speaker], list[MeasPoint]]:
    return (_pick(Room, d.get("room")), [_pick(Speaker, s) for s in d.get("speakers", [])],
            [_pick(MeasPoint, p) for p in d.get("points", [])])


def planes_from_dict(d: dict) -> list[Plane]:
    return [_pick(Plane, p) for p in d.get("planes", [])]


# --- Messwerte aus gespeicherten Kurven ------------------------------------------------------

def measured_band_level(trace: dict, band) -> float | None:
    """Bandpegel aus einer gespeicherten Spektrum-Kurve (Schmalband oder Bänder)."""
    x, lv = np.asarray(trace["freqs"], float), np.asarray(trace["mag"], float)
    if trace.get("stepped"):                         # Bandkanten → Bandmitten
        centers = np.sqrt(x[:-1] * x[1:])
    else:
        centers = x
    power = 10 ** (lv[: len(centers)] / 10)
    if band == "A":
        p = power * 10 ** (weighting_db(centers, "A") / 10)
        return float(10 * np.log10(p.sum() + 1e-30))
    fc = float(band)
    sel = (centers >= fc / 2 ** 0.5) & (centers < fc * 2 ** 0.5)
    if not sel.any():
        return None
    return float(10 * np.log10(power[sel].sum() + 1e-30))
