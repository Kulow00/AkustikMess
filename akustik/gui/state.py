"""Gemeinsamer Programmzustand: Audio-Engine, Kalibrierung, Einstellungen."""

from __future__ import annotations

import json

from PySide6 import QtCore

from ..audio.engine import AudioConfig, BaseEngine, create_engine
from ..dsp.notes import DEFAULT_NAMING


class AppState(QtCore.QObject):
    engine_changed = QtCore.Signal(object)       # BaseEngine | None
    calibration_changed = QtCore.Signal()
    tuning_changed = QtCore.Signal()
    generator_settings_changed = QtCore.Signal()

    def __init__(self, settings: QtCore.QSettings | None = None):
        super().__init__()
        self.settings = settings or QtCore.QSettings("AkustikMess", "AkustikMess")
        self.engine: BaseEngine | None = None
        self.config = self._load_config()
        self.calibration: dict[str, float] = json.loads(self.settings.value("calibration", "{}"))
        self.a4 = float(self.settings.value("a4", 440.0))
        self.note_naming = str(self.settings.value("note_naming", DEFAULT_NAMING))
        self.level_limit_db = float(self.settings.value("level_limit_db", -6.0))
        self.fade_s = float(self.settings.value("fade_s", 0.5))

    # --- Generator-Sicherheit ------------------------------------------------
    def set_generator_settings(self, level_limit_db: float, fade_s: float) -> None:
        self.level_limit_db, self.fade_s = float(level_limit_db), float(fade_s)
        self.settings.setValue("level_limit_db", self.level_limit_db)
        self.settings.setValue("fade_s", self.fade_s)
        if self.engine is not None:
            self.engine.fade_s = self.fade_s
        self.generator_settings_changed.emit()

    # --- Kammerton -----------------------------------------------------------
    def set_tuning(self, a4: float, naming: str) -> None:
        self.a4, self.note_naming = float(a4), naming
        self.settings.setValue("a4", self.a4)
        self.settings.setValue("note_naming", naming)
        self.tuning_changed.emit()

    # --- Audio -------------------------------------------------------------
    def _load_config(self) -> AudioConfig:
        raw = self.settings.value("audio_config", "")
        try:
            return AudioConfig(**json.loads(raw)) if raw else AudioConfig()
        except (TypeError, ValueError):
            return AudioConfig()

    def save_config(self, config: AudioConfig) -> None:
        self.config = config
        self.settings.setValue("audio_config", json.dumps(config.__dict__))

    def start(self) -> None:
        self.stop()
        engine = create_engine(AudioConfig(**self.config.__dict__))
        engine.fade_s = self.fade_s
        engine.start()
        self.engine = engine
        self.engine_changed.emit(engine)

    def stop(self) -> None:
        if self.engine is not None:
            self.engine.stop()
            self.engine = None
            self.engine_changed.emit(None)

    @property
    def fs(self) -> int:
        return self.engine.fs if self.engine else self.config.samplerate

    @property
    def input_channels(self) -> int:
        return self.engine.config.input_channels if self.engine else self.config.input_channels

    @property
    def output_channels(self) -> int:
        return self.engine.config.output_channels if self.engine else self.config.output_channels

    # --- Kalibrierung (dB SPL bei Effektivwert 1.0) je Gerät und Kanal --------
    def _cal_key(self, channel: int) -> str:
        return f"{self.config.input_device}|{channel}"

    def calibration_for(self, channel: int) -> float | None:
        if self.config.input_device.startswith("Simulation"):
            return self.calibration.get(self._cal_key(channel), 120.0)
        return self.calibration.get(self._cal_key(channel))

    def set_calibration(self, channel: int, value: float | None) -> None:
        key = self._cal_key(channel)
        if value is None:
            self.calibration.pop(key, None)
        else:
            self.calibration[key] = float(value)
        self.settings.setValue("calibration", json.dumps(self.calibration))
        self.calibration_changed.emit()
