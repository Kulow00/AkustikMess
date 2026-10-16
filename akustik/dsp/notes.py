"""Frequenz ↔ Notenname mit Cent-Abweichung (gleichstufige Stimmung)."""

from __future__ import annotations

import numpy as np

NAMES = {
    "Deutsch (H)": ["C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "B", "H"],
    "International (B)": ["C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B"],
}
DEFAULT_NAMING = "Deutsch (H)"


def midi_from_freq(f: float, a4: float = 440.0) -> float:
    """Gebrochene MIDI-Notennummer (A4 = 69)."""
    return 69 + 12 * np.log2(f / a4)


def freq_from_midi(m: float, a4: float = 440.0) -> float:
    return a4 * 2 ** ((m - 69) / 12)


def note_of(f: float, a4: float = 440.0, naming: str = DEFAULT_NAMING) -> tuple[str, float]:
    """Nächstgelegene Note (z. B. „D♯7“) und Abweichung in Cent (−50 … +50)."""
    if not np.isfinite(f) or f <= 0:
        return "–", float("nan")
    m = midi_from_freq(f, a4)
    n = int(round(m))
    cents = 100 * (m - n)
    names = NAMES.get(naming, NAMES[DEFAULT_NAMING])
    return f"{names[n % 12]}{n // 12 - 1}", float(cents)


def format_note(f: float, a4: float = 440.0, naming: str = DEFAULT_NAMING) -> str:
    name, cents = note_of(f, a4, naming)
    if name == "–":
        return name
    return f"{name} {cents:+.0f} ct"


def format_freq(f: float) -> str:
    """Genaue Frequenzangabe: 0.01 Hz unter 100 Hz, 0.1 Hz bis 1 kHz, sonst 1 Hz."""
    if f < 100:
        return f"{f:.2f} Hz"
    if f < 1000:
        return f"{f:.1f} Hz"
    return f"{f:.0f} Hz"


def a4_from_measured(f: float, a4_guess: float = 440.0) -> float:
    """Kammerton so bestimmen, dass der gemessene Ton exakt auf seiner Note liegt."""
    n = round(midi_from_freq(f, a4_guess))
    return float(f / 2 ** ((n - 69) / 12))
