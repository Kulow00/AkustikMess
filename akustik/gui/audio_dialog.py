"""Dialog zur Auswahl von Audio-Interface, Abtastrate und Kanälen."""

from __future__ import annotations

from PySide6 import QtWidgets

from ..audio.engine import SIMULATION, AudioConfig, list_devices

RATES = [44100, 48000, 88200, 96000, 192000]
BLOCKS = [256, 512, 1024, 2048, 4096]


class AudioDialog(QtWidgets.QDialog):
    def __init__(self, config: AudioConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Audio-Einstellungen")
        self.setMinimumWidth(520)
        try:
            self.apis, self.devices = list_devices()
        except Exception as exc:  # noqa: BLE001 – PortAudio nicht verfügbar
            self.apis, self.devices = [], []
            QtWidgets.QMessageBox.warning(self, "Audio", f"Audio-Geräte nicht abrufbar:\n{exc}")
        f = QtWidgets.QFormLayout(self)
        self.cb_api = QtWidgets.QComboBox()
        self.cb_api.addItem(SIMULATION)
        for a in self.apis:
            self.cb_api.addItem(a)
        hint = QtWidgets.QLabel("Windows: ASIO (falls vom Interface-Treiber angeboten) oder WASAPI "
                                "für geringste Latenz und alle Kanäle. macOS: Core Audio.")
        hint.setWordWrap(True)
        self.cb_in = QtWidgets.QComboBox()
        self.cb_out = QtWidgets.QComboBox()
        self.cb_rate = QtWidgets.QComboBox()
        for r in RATES:
            self.cb_rate.addItem(f"{r} Hz", r)
        self.cb_block = QtWidgets.QComboBox()
        for b in BLOCKS:
            self.cb_block.addItem(str(b), b)
        self.sp_in = QtWidgets.QSpinBox(minimum=1, maximum=64)
        self.sp_out = QtWidgets.QSpinBox(minimum=1, maximum=64)
        f.addRow("Treiber / Host-API", self.cb_api)
        f.addRow(hint)
        f.addRow("Eingangsgerät", self.cb_in)
        f.addRow("Ausgangsgerät", self.cb_out)
        f.addRow("Abtastrate", self.cb_rate)
        f.addRow("Blockgröße", self.cb_block)
        f.addRow("Eingangskanäle", self.sp_in)
        f.addRow("Ausgangskanäle", self.sp_out)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

        self.cb_api.currentIndexChanged.connect(self._api_changed)
        self.cb_in.currentIndexChanged.connect(self._limits)
        self.cb_out.currentIndexChanged.connect(self._limits)
        api = SIMULATION if config.input_device == SIMULATION else config.host_api
        self.cb_api.setCurrentIndex(max(0, self.cb_api.findText(api)))
        self._api_changed()
        self._select(self.cb_in, config.input_device)
        if not self._select(self.cb_out, config.output_device):
            self._default_output()
        self.cb_rate.setCurrentIndex(max(0, self.cb_rate.findData(config.samplerate)))
        self.cb_block.setCurrentIndex(max(0, self.cb_block.findData(config.blocksize)))
        self.sp_in.setValue(config.input_channels)
        self.sp_out.setValue(config.output_channels)

    @staticmethod
    def _select(cb: QtWidgets.QComboBox, name) -> bool:
        i = cb.findData(name) if name is not None else -1
        if i >= 0:
            cb.setCurrentIndex(i)
        return i >= 0

    def _default_output(self) -> None:
        """Ausgang vorschlagen: gleiches Gerät wie der Eingang, sonst der Standard-Ausgang des Systems.

        Ohne Ausgang spielt der Generator nichts ab – das soll nie unbemerkt passieren.
        """
        if self.cb_api.currentText() == SIMULATION:
            return
        if self._select(self.cb_out, self.cb_in.currentData()):
            return
        try:
            import sounddevice as sd  # noqa: PLC0415
            name = sd.query_devices(kind="output")["name"]
        except Exception:  # noqa: BLE001
            name = None
        if not self._select(self.cb_out, name) and self.cb_out.count() > 1:
            self.cb_out.setCurrentIndex(1)  # erstes echtes Ausgabegerät

    def _api_changed(self) -> None:
        api = self.cb_api.currentText()
        sim = api == SIMULATION
        self.cb_in.clear()
        self.cb_out.clear()
        if sim:
            self.cb_in.addItem("Virtueller Raum (Mikrofon = Eingang 1, Loopback = Eingang 2)", SIMULATION)
            self.cb_out.addItem("Virtueller Lautsprecher (Ausgang 1)", SIMULATION)
        else:
            self.cb_out.addItem("– kein Ausgang –", None)
            for d in self.devices:
                if d["hostapi"] != api:
                    continue
                if d["inputs"]:
                    self.cb_in.addItem(f"{d['name']}  ({d['inputs']} Eingänge)", d["name"])
                if d["outputs"]:
                    self.cb_out.addItem(f"{d['name']}  ({d['outputs']} Ausgänge)", d["name"])
            self._default_output()
        for w in (self.cb_in, self.cb_out, self.sp_in, self.sp_out, self.cb_block):
            w.setEnabled(not sim)
        self._limits()

    def _device(self, name, kind):
        api = self.cb_api.currentText()
        for d in self.devices:
            if d["name"] == name and d["hostapi"] == api and d[kind]:
                return d
        return None

    def _limits(self) -> None:
        if self.cb_api.currentText() == SIMULATION:
            self.sp_in.setValue(2)
            self.sp_out.setValue(2)
            return
        d_in = self._device(self.cb_in.currentData(), "inputs")
        d_out = self._device(self.cb_out.currentData(), "outputs")
        if d_in:
            self.sp_in.setMaximum(d_in["inputs"])
            self.sp_in.setValue(d_in["inputs"])
        if d_out:
            self.sp_out.setMaximum(d_out["outputs"])
            self.sp_out.setValue(min(d_out["outputs"], 8))
        self.sp_out.setEnabled(d_out is not None)

    def result_config(self) -> AudioConfig:
        sim = self.cb_api.currentText() == SIMULATION
        return AudioConfig(
            input_device=SIMULATION if sim else self.cb_in.currentData(),
            output_device=SIMULATION if sim else self.cb_out.currentData(),
            host_api="" if sim else self.cb_api.currentText(),
            samplerate=self.cb_rate.currentData(),
            blocksize=self.cb_block.currentData(),
            input_channels=self.sp_in.value(),
            output_channels=self.sp_out.value(),
        )
