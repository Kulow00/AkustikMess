# Third-party components / Fremdkomponenten

The AkustikMess installers bundle the following open-source components. Each remains under its own
license; the license texts are included in the respective package folders inside the installation
(`_internal/…dist-info/`) and at the linked project pages.

| Component | License | Project |
|---|---|---|
| Python | PSF License | https://www.python.org |
| Qt / PySide6 | LGPL-3.0 (dynamically linked, replaceable DLLs) | https://www.qt.io, https://pyside.org |
| NumPy | BSD-3-Clause (bundled OpenBLAS: BSD-3-Clause) | https://numpy.org |
| SciPy | BSD-3-Clause (bundled libraries: BSD/MIT, libgfortran: GPL-3.0 with GCC Runtime Library Exception) | https://scipy.org |
| pyqtgraph | MIT | https://www.pyqtgraph.org |
| python-sounddevice | MIT | https://github.com/spatialaudio/python-sounddevice |
| PortAudio | MIT | https://www.portaudio.com |
| qrcode | BSD-3-Clause | https://github.com/lincolnloop/python-qrcode |
| cryptography | Apache-2.0 or BSD-3-Clause | https://cryptography.io |
| PyInstaller bootloader | GPL-2.0 with bootloader exception | https://pyinstaller.org |
| Inno Setup (Windows installer) | Inno Setup License | https://jrsoftware.org/isinfo.php |

**Qt/PySide6 (LGPL-3.0):** The Qt libraries are shipped as separate, unmodified DLLs in the `_internal`
folder and can be replaced by the user with compatible versions. The source code of Qt and PySide6 is
available at https://download.qt.io/official_releases/.
