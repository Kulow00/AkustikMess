"""Raumakustik für das Raummodell (Stufe 2): Reflexionen, Nachhall, STI, Raummoden, Wellenfeld.

* **Reflexionen 1. Ordnung** über Spiegelquellen an den sechs Raumflächen (Seitenwände, Rückwand hinter der
  Bühne, Wand gegenüber, Boden, Decke). Reflexionsfaktor |R| = √(1 − α).
* **Nachhall** als diffuses Feld (Sabine): L_diff = L_W + 10·lg(4/A), A = Σ S·α + 4·m·V. Nachhallzeit
  gemessen (Impulsantwort-Modus) oder aus den Absorptionsgraden berechnet.
* **STI** nach IEC 60268-16 aus Direkt-/frühem Schall D, Nachhall R und Störgeräusch N je Oktave:
  m(F) = (D + R·m_R(F)) / (D + R + N), m_R(F) = 1/√(1 + (2πF·T/13,8)²).
* **Raummoden** des Rechteckraums: f = c/2 · √((nx/W)² + (ny/L)² + (nz/H)²).
"""

from __future__ import annotations

import copy
import math

import numpy as np

from . import roommodel as rm
from .sti import ALPHA_MALE, BETA_MALE, MOD_FREQS, STI_BANDS
from .weighting import weighting_db

# typischer Verlauf von Hintergrundgeräusch (fällt zu hohen Frequenzen ab), relativ je Oktave 125 Hz … 8 kHz
NOISE_SHAPE_DB = np.array([8.0, 4.0, 0.0, -3.0, -6.0, -9.0, -12.0])


# --- Geometrie ----------------------------------------------------------------------------

def bounds(room: rm.Room) -> dict:
    return {"x": (0.0, room.width), "y": (room.y_min, room.length), "z": (0.0, room.height)}


def surfaces(room: rm.Room) -> dict:
    """Flächen (m²) und Absorptionsgrade."""
    depth = room.length - room.y_min
    return {"floor": (room.width * depth, room.alpha_floor), "ceiling": (room.width * depth, room.alpha_ceiling),
            "walls": (2 * room.height * depth + 2 * room.height * room.width, room.alpha_walls)}


def volume(room: rm.Room) -> float:
    return room.width * (room.length - room.y_min) * room.height


def image_sources(room: rm.Room, speakers: list[rm.Speaker]) -> list[rm.Speaker]:
    """Spiegelquellen 1. Ordnung (Position, Ausrichtung gespiegelt, Pegel um 20·lg|R| gesenkt)."""
    b = bounds(room)
    alpha = {"x": room.alpha_walls, "y": room.alpha_walls, "z": None}
    out = []
    for sp in speakers:
        if not sp.enabled:
            continue
        for axis in ("x", "y", "z"):
            for k, wall in enumerate(b[axis]):
                a = alpha[axis] if axis != "z" else (room.alpha_floor if k == 0 else room.alpha_ceiling)
                r = math.sqrt(max(1.0 - a, 0.0))
                if r <= 0.01:
                    continue
                im = copy.deepcopy(sp)
                im.name = f"{sp.name} ({axis}{'−' if k == 0 else '+'})"
                setattr(im, axis, 2 * wall - getattr(sp, axis))
                if axis == "x":
                    im.azimuth = -sp.azimuth
                elif axis == "y":
                    im.azimuth = 180.0 - sp.azimuth
                else:
                    im.tilt = -sp.tilt
                im.level = sp.level + 20 * math.log10(r)
                out.append(im)
    return out


def active_sources(room: rm.Room, speakers) -> list[rm.Speaker]:
    sp = [s for s in speakers if s.enabled]
    return sp + image_sources(room, sp) if room.reflections else sp


# --- Nachhall ----------------------------------------------------------------------------

def rt60(room: rm.Room, band: float) -> float:
    """Nachhallzeit (s) im Oktavband: gemessen (interpoliert) oder nach Sabine berechnet."""
    if room.rt60:
        f = np.array(sorted(float(k) for k in room.rt60))
        t = np.array([room.rt60[k] for k in sorted(room.rt60, key=float)], float)
        ok = np.isfinite(t) & (t > 0)
        if ok.any():
            return float(np.interp(np.log(band), np.log(f[ok]), t[ok]))
    v = volume(room)
    a = sum(s * al for s, al in surfaces(room).values())
    m = rm.air_db_per_m(band) / (10 * math.log10(math.e))       # Energiedämpfung 1/m
    return 0.161 * v / max(a + 4 * m * v, 1e-6)


def absorption_area(room: rm.Room, band: float) -> float:
    return 0.161 * volume(room) / max(rt60(room, band), 0.05)


def q_factor(sp: rm.Speaker, f: float) -> float:
    """Bündelungsgrad aus den Öffnungswinkeln (Kugel = 1)."""
    widen = max(1.0, rm.DIR_FREQ / f)
    h, v = min(360.0, sp.cov_h * widen), min(360.0, sp.cov_v * widen)
    if sp.kind == "sub" and h >= 360:
        return 1.0
    return float(np.clip(41253.0 / (min(h, 180) * min(v, 180)), 1.0, 60.0))


def source_band_level(sp: rm.Speaker, band: float) -> float:
    """Pegel in 1 m auf Achse im Oktavband (wie in der Direktschallrechnung)."""
    freqs = rm._band_freqs(band, 1)  # noqa: SLF001
    h2 = float(np.mean(np.abs(rm.response(sp, freqs)) ** 2))
    return sp.level + 10 * math.log10(rm._band_norm(sp)) + 10 * math.log10(max(h2, 1e-12))  # noqa: SLF001


def reverb_level(room: rm.Room, speakers, band: float) -> float:
    """Pegel des diffusen Nachhallfelds (dB), überall im Raum gleich."""
    a = absorption_area(room, band)
    e = 0.0
    for sp in speakers:
        if sp.enabled:
            lw = source_band_level(sp, band) + 10 * math.log10(4 * math.pi) - 10 * math.log10(q_factor(sp, band))
            e += 10 ** (lw / 10)
    return 10 * math.log10(e * 4 / a + 1e-30) if e else -np.inf


def noise_band_levels(noise_dba: float) -> np.ndarray:
    """Störgeräusch je Oktave 125 Hz … 8 kHz aus einem dB(A)-Wert (typischer Verlauf)."""
    a = weighting_db(np.array(STI_BANDS, float), "A")
    total = 10 * math.log10(np.sum(10 ** ((NOISE_SHAPE_DB + a) / 10)))
    return NOISE_SHAPE_DB + (noise_dba - total)


# --- Karten ----------------------------------------------------------------------------

def plane_points(room: rm.Room, plane: rm.Plane | None):
    if plane is None:
        xs, ys = rm.grid(room)
        z = room.listen_height
    else:
        xs, ys = rm.plane_grid(plane, room.resolution)
        z = plane.z
    X, Y = np.meshgrid(xs, ys)
    return xs, ys, X, Y, np.full_like(X, z)


def room_band_level(room, speakers, band, X, Y, Z, fraction=1, with_room=True) -> np.ndarray:
    """Pegel inkl. Reflexionen und Nachhall (with_room) bzw. nur Direktschall."""
    srcs = active_sources(room, speakers) if with_room else [s for s in speakers if s.enabled]
    if band == "A":
        e = 0.0
        for fc in rm.OCTAVES:
            e = e + 10 ** ((room_band_level(room, speakers, fc, X, Y, Z, 1, with_room)
                            + float(weighting_db(fc, "A"))) / 10)
        return 10 * np.log10(e + 1e-30)
    direct = rm.band_level(srcs, band, X, Y, Z, fraction)
    if not with_room:
        return direct
    rev = reverb_level(room, speakers, float(band)) - (10 * math.log10(fraction) if fraction > 1 else 0)
    return 10 * np.log10(10 ** (direct / 10) + 10 ** (rev / 10))


def sti_map(room, speakers, X, Y, Z) -> np.ndarray:
    """STI-Vorhersage (männliche Sprache) an allen Punkten."""
    srcs = active_sources(room, speakers)
    noise = noise_band_levels(room.noise_dba)
    F = np.array(MOD_FREQS)[:, None, None]
    mti = []
    for k, band in enumerate(STI_BANDS):
        d = 10 ** (rm.band_level(srcs, band, X, Y, Z, 1) / 10)
        r = 10 ** (reverb_level(room, speakers, band) / 10)
        n = 10 ** (noise[k] / 10)
        t = rt60(room, band)
        m_r = 1 / np.sqrt(1 + (2 * np.pi * F * t / 13.8) ** 2)
        m = (d + r * m_r) / (d + r + n)
        m = np.clip(m, 1e-6, 1 - 1e-6)
        snr = np.clip(10 * np.log10(m / (1 - m)), -15, 15)
        mti.append(np.mean((snr + 15) / 30, axis=0))
    mti = np.array(mti)
    sti = np.tensordot(ALPHA_MALE, mti, axes=1) - np.tensordot(BETA_MALE, np.sqrt(mti[:-1] * mti[1:]), axes=1)
    return np.clip(sti, 0, 1)


def room_modes(room: rm.Room, fmax: float = 300.0, max_order: int = 8) -> list[dict]:
    """Raummoden des Rechteckraums (inkl. Bühne) bis fmax, sortiert."""
    w, d, h = room.width, room.length - room.y_min, room.height
    out = []
    for nx in range(max_order + 1):
        for ny in range(max_order + 1):
            for nz in range(max_order + 1):
                if nx == ny == nz == 0:
                    continue
                f = rm.C / 2 * math.sqrt((nx / w) ** 2 + (ny / d) ** 2 + (nz / h) ** 2)
                if f <= fmax:
                    kind = {1: "axial", 2: "tangential", 3: "oblique"}[sum(1 for n in (nx, ny, nz) if n)]
                    out.append({"f": round(f, 1), "n": (nx, ny, nz), "kind": kind})
    return sorted(out, key=lambda m: m["f"])


def mode_shape(room: rm.Room, n: tuple, X, Y, Z) -> np.ndarray:
    """Relativer Schalldruck der Mode (0 = Knoten, 1 = Bauch) als Pegel in dB."""
    nx, ny, nz = n
    p = (np.cos(nx * np.pi * X / room.width) * np.cos(ny * np.pi * (Y - room.y_min) / (room.length - room.y_min))
         * np.cos(nz * np.pi * Z / room.height))
    return 20 * np.log10(np.abs(p) + 1e-3)


def wave_field(room, speakers, f: float, view: str = "top", x_section: float | None = None, with_room=False):
    """Komplexes Schallfeld bei Frequenz f: Draufsicht (Hörhöhe) oder Längsschnitt (x = x_section)."""
    srcs = active_sources(room, speakers) if with_room else [s for s in speakers if s.enabled]
    if view == "top":
        xs, ys = rm.grid(room)
        A, B = np.meshgrid(xs, ys)
        P = rm.pressure(srcs, f, A, B, np.full_like(A, room.listen_height))
        return xs, ys, P
    xc = room.width / 2 if x_section is None else x_section
    ys = rm.grid(room)[1]
    nz = max(2, int(round(room.height / room.resolution)) + 1)
    zs = np.linspace(0, room.height, nz)
    Ya, Za = np.meshgrid(ys, zs)
    P = rm.pressure(srcs, f, np.full_like(Ya, xc), Ya, Za)
    return ys, zs, P


def wave_frame(P: np.ndarray, phase: float, gamma: float = 0.35) -> np.ndarray:
    """Momentaufnahme Re{p·e^{jφ}} mit Dynamikkompression (sonst dominiert das Nahfeld), −1 … 1."""
    a = np.abs(P)
    peak = np.percentile(a, 99) if a.size else 1.0
    v = np.real(P * np.exp(1j * phase)) / (peak + 1e-30)
    return np.sign(v) * np.minimum(np.abs(v), 1.0) ** gamma


# --- Gesamtauswertung für die Oberfläche --------------------------------------------------------

def compute_view(room, speakers, kind: str, band=None, fraction: int = 1, plane=None, wave_freq: float = 100.0,
                 x_section=None, mode=None, with_room: bool = True) -> dict:
    """Eine Darstellung berechnen. kind: level | sti | wave_top | wave_section | mode."""
    if kind == "level":
        xs, ys, X, Y, Z = plane_points(room, plane)
        return {"kind": kind, "xs": xs, "ys": ys,
                "data": room_band_level(room, speakers, band, X, Y, Z, fraction, with_room)}
    if kind == "sti":
        xs, ys, X, Y, Z = plane_points(room, plane)
        return {"kind": kind, "xs": xs, "ys": ys, "data": sti_map(room, speakers, X, Y, Z)}
    if kind in ("wave_top", "wave_section"):
        a, b, P = wave_field(room, speakers, wave_freq, "top" if kind == "wave_top" else "section", x_section,
                             with_room)
        return {"kind": kind, "xs": a, "ys": b, "field": P, "data": wave_frame(P, 0.0)}
    if kind == "mode":
        xs, ys, X, Y, Z = plane_points(room, plane)
        return {"kind": kind, "xs": xs, "ys": ys, "data": mode_shape(room, tuple(mode["n"]), X, Y, Z)}
    raise ValueError(kind)
