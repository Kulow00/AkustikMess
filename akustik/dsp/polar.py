"""Gemessene Abstrahlung (Polardaten) für das Raummodell.

Format der Importdatei (CSV/Text, Trennzeichen ``;`` ``,`` oder Tab, Dezimalkomma erlaubt)::

    Hz;0;10;20;30;…;180
    125;0;-0,1;-0,3;…
    250;0;-0,2;-0,8;…
    …

Erste Zeile: Winkel in Grad (0 = Achse, symmetrisch angenommen), erste Spalte: Frequenz in Hz,
Werte: Pegel in dB (relativ oder absolut – es wird auf die Achse normiert). Eine Datei für die
horizontale, optional eine zweite für die vertikale Ebene. Solche Tabellen exportieren Messprogramme
(z. B. ARTA, REW, VituixCAD) oder sie lassen sich aus Datenblättern übernehmen.
"""

from __future__ import annotations

import re

import numpy as np

MIN_DB = -40.0


class PolarError(ValueError):
    pass


def _num(s: str) -> float:
    return float(s.strip().replace(",", "."))


def parse_polar(text: str) -> tuple[list[float], list[float], list[list[float]]]:
    """(Frequenzen, Winkel, dB-Matrix[Frequenz][Winkel]) – auf die Achse (0°) normiert."""
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "//")):
            continue
        if ";" in line:
            parts = line.split(";")
        elif "\t" in line:
            parts = line.split("\t")
        elif re.search(r"\s", line) and re.search(r"\d,\d", line):
            parts = line.split()                       # Leerzeichen getrennt, Dezimalkomma
        else:
            parts = re.split(r"[\s,]+", line)          # Komma oder Leerzeichen getrennt, Dezimalpunkt
        rows.append([p for p in parts if p.strip() != ""])
    if len(rows) < 2:
        raise PolarError("Zu wenige Zeilen – erwartet: Kopfzeile mit Winkeln, dann je Frequenz eine Zeile")
    try:
        angles = [_num(a) for a in rows[0][1:]]
        freqs, values = [], []
        for r in rows[1:]:
            freqs.append(_num(r[0]))
            vals = [_num(v) for v in r[1:]]
            if len(vals) != len(angles):
                raise PolarError(f"Zeile {r[0]} Hz hat {len(vals)} Werte, erwartet {len(angles)}")
            values.append(vals)
    except ValueError as exc:
        raise PolarError(f"Ungültige Zahl in der Polardatei ({exc})") from exc
    if not angles or min(angles) > 0.5:
        raise PolarError("Die Winkel müssen bei 0° (Achse) beginnen")
    order = np.argsort(angles)
    angles = list(np.abs(np.array(angles)[order]))
    m = np.array(values)[:, order]
    fo = np.argsort(freqs)
    freqs, m = list(np.array(freqs)[fo]), m[fo]
    if min(freqs) <= 0:
        raise PolarError("Frequenzen müssen größer als 0 Hz sein")
    on_axis = m[:, [int(np.argmin(np.abs(np.array(angles))))]]
    m = np.maximum(m - on_axis, MIN_DB)
    return [float(f) for f in freqs], [float(a) for a in angles], m.round(2).tolist()


def make_polar(h_text: str, v_text: str | None = None) -> dict:
    fh, ah, mh = parse_polar(h_text)
    if v_text:
        fv, av, mv = parse_polar(v_text)
    else:
        fv, av, mv = fh, ah, mh
    return {"h": {"freqs": fh, "angles": ah, "db": mh}, "v": {"freqs": fv, "angles": av, "db": mv}}


def _plane_att(data: dict, f: float, theta) -> np.ndarray:
    freqs = np.array(data["freqs"])
    angles = np.array(data["angles"])
    m = np.array(data["db"])
    lf = np.log(np.clip(f, freqs[0], freqs[-1]))
    i = int(np.clip(np.searchsorted(np.log(freqs), lf) - 1, 0, max(len(freqs) - 2, 0)))
    if len(freqs) == 1:
        row = m[0]
    else:
        w = (lf - np.log(freqs[i])) / (np.log(freqs[i + 1]) - np.log(freqs[i]))
        row = m[i] * (1 - w) + m[i + 1] * w
    th = np.minimum(np.abs(theta), angles[-1])
    return np.interp(th, angles, row)


def polar_att_db(polar: dict, f: float, th, tv) -> np.ndarray:
    """Dämpfung (dB ≤ 0) aus horizontalen und vertikalen Polardaten (getrennt angesetzt, summiert)."""
    return np.maximum(_plane_att(polar["h"], f, th) + _plane_att(polar["v"], f, tv), MIN_DB)
