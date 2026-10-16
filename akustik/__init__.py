"""AkustikMess – Messsoftware für Beschallung und Raumakustik."""

import os as _os

# Die Mathe-Bibliothek (OpenBLAS) reserviert sonst je Prozessorkern Puffer – bei 12 Kernen über 700 MB.
# AkustikMess rechnet fast nur FFTs und Elementweises, Mehrkern-Matrixrechnung bringt hier nichts.
for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    _os.environ.setdefault(_var, "1")

__version__ = "0.5.0-beta.5"
RELEASE_DATE = "2026-10-16"  # vom Release-Werkzeug gesetzt (JJJJ-MM-TT)
APP_NAME = "AkustikMess"
COPYRIGHT = "Copyright © 2026 Alex Kulow"
