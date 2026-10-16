"""Zielkurven (Soll-Frequenzgang) für die Übertragungsfunktion."""

from __future__ import annotations

import re

import numpy as np

# Stützstellen (Hz, dB). Die Haus- und Sprachkurven sind Beispiele – an die
# eigene Klangvorstellung anpassen und als Datei speichern.
PRESETS: dict[str, list[tuple[float, float]]] = {
    "Flach": [(20, 0), (20000, 0)],
    "Live-Hauskurve (Beispiel)": [(20, 6), (60, 6), (150, 2), (1000, 0), (4000, -2),
                                  (10000, -4), (20000, -6)],
    "Sprache (Beispiel)": [(20, -12), (100, -3), (200, 0), (4000, 0), (10000, -4), (20000, -10)],
    "X-Kurve (Kino, ISO 2969)": [(20, 0), (2000, 0), (4000, -3), (8000, -6), (16000, -9),
                                 (20000, -9.97)],
}


def target_db(points: list[tuple[float, float]], f: np.ndarray) -> np.ndarray:
    """Zielkurve bei Frequenzen f (lineare Interpolation über log f, außen konstant)."""
    pts = sorted(points)
    fx = np.log10([p[0] for p in pts])
    fy = [p[1] for p in pts]
    return np.interp(np.log10(np.asarray(f, float)), fx, fy)


def parse_target(text: str) -> list[tuple[float, float]]:
    """Liest „Frequenz  dB“-Zeilen (Trenner: Leerzeichen, Tab, ; oder ,).

    Kommentare (# oder *) und Kopfzeilen werden übersprungen; Dezimalkomma wird
    erkannt, wenn ; oder Tab als Trenner dienen. Weitere Spalten (z. B. Phase)
    werden ignoriert – damit lassen sich auch .frd/.txt-Dateien laden.
    """
    pts = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line[0] in "#*\"'":
            continue
        if ";" in line or "\t" in line:
            parts = [p.strip().replace(",", ".") for p in re.split(r"[;\t]+", line)]
        else:
            parts = re.split(r"[\s,]+", line)
        try:
            f, db = float(parts[0]), float(parts[1])
        except (ValueError, IndexError):
            continue
        if f > 0:
            pts.append((f, db))
    if len(pts) < 2:
        raise ValueError("Mindestens zwei Zeilen „Frequenz dB“ erforderlich")
    return sorted(pts)


def auto_offset(f: np.ndarray, measured_db: np.ndarray, target_values: np.ndarray,
                f_lo: float = 200.0, f_hi: float = 5000.0) -> float:
    """Pegelversatz, der die Zielkurve im Kernbereich auf die Messung legt."""
    sel = (f >= f_lo) & (f <= f_hi) & np.isfinite(measured_db)
    if not np.any(sel):
        return 0.0
    return float(np.median(measured_db[sel] - target_values[sel]))
