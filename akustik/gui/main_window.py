"""Hauptfenster: Menü, Symbolleiste (Audio, Generator), Tastenkürzel, Sitzungen."""

from __future__ import annotations

import os

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from .. import APP_NAME, __version__
from ..dsp.generator import GENERATORS, PeriodicPinkNoise, Sine
from .audio_dialog import AudioDialog
from .common import set_channel_count
from .ir_view import ImpulseView
from .realtime_view import RealtimeView
from .remote_panel import RemoteController, RemoteDialog
from .session import EXTENSION, FILE_FILTER, load_session, save_session
from .spl_view import SPLView
from .state import AppState
from .tuning_dialog import TuningDialog
from .update_dialog import AboutDialog, UpdateDialog, UpdateManager, ask_consent

AUTOSAVE_INTERVAL_MS = 60_000

SHORTCUTS = [
    ("Leertaste", "Audio starten / stoppen"),
    ("G", "Generator ein / aus (mit Ein-/Ausblenden)"),
    ("M", "Generator sofort stumm"),
    ("S", "Echtzeit: Übertragungsfunktion speichern (im Spektrum-Modus: Spektrum)"),
    ("Umschalt+S", "Echtzeit: Spektrum speichern"),
    ("D", "Echtzeit: Laufzeit finden"),
    ("R", "Echtzeit: Mittelung zurücksetzen"),
    ("P", "Echtzeit: Spitzenwert halten ein / aus"),
    ("Eingabe", "Impulsantwort: Messung starten"),
    ("N", "SPL: Notiz eingeben"),
    ("1 / 2 / 3", "Echtzeit / Impulsantwort / SPL"),
    ("Strg+N / O / S", "Neue Sitzung / Öffnen / Speichern"),
    ("Strg+Umschalt+S", "Sitzung speichern unter"),
    ("F1", "Diese Übersicht"),
]


class ShortcutFilter(QtCore.QObject):
    """Einzeltasten-Kürzel für das ganze Programm.

    Greift nicht, solange in ein Text- oder Zahlenfeld getippt wird, und nur,
    wenn das Hauptfenster aktiv ist (nicht in Dialogen).
    """

    def __init__(self, window: "MainWindow"):
        super().__init__(window)
        self.win = window

    def eventFilter(self, obj, event) -> bool:
        if event.type() != QtCore.QEvent.KeyPress or event.isAutoRepeat():
            return False
        mods = event.modifiers()
        if mods & (QtCore.Qt.ControlModifier | QtCore.Qt.AltModifier | QtCore.Qt.MetaModifier):
            return False
        if not self.win.isActiveWindow():
            return False
        fw = QtWidgets.QApplication.focusWidget()
        if isinstance(fw, (QtWidgets.QLineEdit, QtWidgets.QAbstractSpinBox, QtWidgets.QTextEdit,
                           QtWidgets.QPlainTextEdit)) or (
                isinstance(fw, QtWidgets.QComboBox) and fw.isEditable()):
            return False
        if isinstance(fw, QtWidgets.QAbstractItemView) and fw.state() == QtWidgets.QAbstractItemView.EditingState:
            return False
        handler = self.win.key_action(event.key(), bool(mods & QtCore.Qt.ShiftModifier))
        if handler is None:
            return False
        handler()
        return True


class GeneratorSettingsDialog(QtWidgets.QDialog):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.setWindowTitle("Generator-Einstellungen")
        f = QtWidgets.QFormLayout(self)
        info = QtWidgets.QLabel("Die Pegelgrenze schützt Lautsprecher: Generator und Mess-Sweep "
                                "können nicht lauter eingestellt werden.")
        info.setWordWrap(True)
        f.addRow(info)
        self.sp_limit = QtWidgets.QDoubleSpinBox(minimum=-60, maximum=0, decimals=1,
                                                 value=state.level_limit_db, suffix=" dBFS")
        self.sp_fade = QtWidgets.QDoubleSpinBox(minimum=0.0, maximum=5.0, decimals=2, singleStep=0.1,
                                                value=state.fade_s, suffix=" s")
        f.addRow("Pegelgrenze", self.sp_limit)
        f.addRow("Ein-/Ausblendzeit", self.sp_fade)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def _ok(self) -> None:
        self.state.set_generator_settings(self.sp_limit.value(), self.sp_fade.value())
        self.accept()


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, settings: QtCore.QSettings | None = None, autosave_path: str | None = None,
                 recovery: bool = True, check_updates: bool = True):
        super().__init__()
        self.state = AppState(settings)
        self.updates = UpdateManager(self.state.settings, self)
        self.updates.checked.connect(self._background_update_result)
        self.session_path: str | None = None
        self.autosave_path = autosave_path or os.path.join(
            QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.AppDataLocation),
            "autosave" + EXTENSION)
        self.resize(1400, 900)

        self.tabs = QtWidgets.QTabWidget()
        self.realtime = RealtimeView(self.state)
        self.impulse = ImpulseView(self.state)
        self.spl = SPLView(self.state)
        self.tabs.addTab(self.realtime, "Echtzeit")
        self.tabs.addTab(self.impulse, "Impulsantwort")
        self.tabs.addTab(self.spl, "SPL")
        self.setCentralWidget(self.tabs)
        self.remote = RemoteController(self)
        self._build_menu()
        self._build_toolbar()
        self._build_statusbar()
        self.state.engine_changed.connect(self._engine_changed)
        self.state.generator_settings_changed.connect(self._apply_level_limit)
        self.realtime.cb_tf_fft.currentIndexChanged.connect(self._fft_changed)
        self._engine_changed(None)
        self._apply_level_limit()
        self._update_title()

        self.shortcut_filter = ShortcutFilter(self)
        QtWidgets.QApplication.instance().installEventFilter(self.shortcut_filter)
        self.autosave_timer = QtCore.QTimer(self, interval=AUTOSAVE_INTERVAL_MS, timeout=self.autosave)
        self.autosave_timer.start()
        if recovery:
            QtCore.QTimer.singleShot(300, self._check_recovery)
        if check_updates and self.updates.url:
            QtCore.QTimer.singleShot(4000, self._startup_update_check)

    # --- Updates ------------------------------------------------------------------------
    def _startup_update_check(self) -> None:
        if not self.updates.consent_asked:
            ask_consent(self.updates, self)   # Netzwerkzugriff nur nach Zustimmung
        if self.updates.auto:
            self.updates.check()  # im Hintergrund, stört keine Messung

    def open_updates(self) -> None:
        UpdateDialog(self.updates, self).exec()

    def _background_update_result(self, upd, err: str) -> None:
        if upd is not None and upd.version != self.updates.skipped:
            self.show_update_hint(upd)

    def show_update_hint(self, upd) -> None:
        if upd is None:
            self.btn_update.hide()
            return
        beta = " (Beta)" if upd.channel == "beta" else ""
        self.btn_update.setText(f"⬆ Update {upd.version}{beta} verfügbar")
        self.btn_update.show()

    # --- Menü und Symbolleiste -------------------------------------------------
    def _build_menu(self) -> None:
        m = self.menuBar().addMenu("&Datei")
        for text, key, slot in (
            ("Neue Sitzung", QtGui.QKeySequence.New, self.new_session),
            ("Sitzung öffnen…", QtGui.QKeySequence.Open, self.open_session),
            ("Sitzung speichern", QtGui.QKeySequence.Save, self.save_session),
            ("Sitzung speichern unter…", QtGui.QKeySequence("Ctrl+Shift+S"), self.save_session_as),
        ):
            a = QtGui.QAction(text, self, shortcut=key, triggered=slot)
            m.addAction(a)
        m.addSeparator()
        m.addAction(QtGui.QAction("Beenden", self, triggered=self.close))
        m = self.menuBar().addMenu("&Generator")
        m.addAction(QtGui.QAction("Einstellungen (Pegelgrenze, Blende)…", self,
                                  triggered=lambda: GeneratorSettingsDialog(self.state, self).exec()))
        m = self.menuBar().addMenu("&Hilfe")
        m.addAction(QtGui.QAction("Tastenkürzel", self, shortcut=QtGui.QKeySequence("F1"),
                                  triggered=self.show_shortcuts))
        m.addSeparator()
        m.addAction(QtGui.QAction("Nach Updates suchen…", self, triggered=self.open_updates))
        m.addAction(QtGui.QAction(f"Über {APP_NAME}", self,
                                  triggered=lambda: AboutDialog(self.updates, self).exec()))

    def _build_toolbar(self) -> None:
        tb = self.addToolBar("Audio")
        tb.setMovable(False)
        a_cfg = QtGui.QAction("Audio-Einstellungen…", self, triggered=self.configure_audio)
        self.a_run = QtGui.QAction("▶ Audio starten", self, checkable=True, toggled=self.toggle_audio)
        self.a_run.setToolTip("Audio starten/stoppen (Leertaste)")
        tb.addAction(a_cfg)
        tb.addAction(self.a_run)
        tb.addSeparator()
        tb.addWidget(QtWidgets.QLabel(" Generator: "))
        self.cb_gen = QtWidgets.QComboBox()
        self.cb_gen.addItems(list(GENERATORS))
        self.cb_gen.setCurrentText("Rosa Rauschen (periodisch)")
        self.cb_gen.setToolTip("Periodisches rosa Rauschen passt sich der FFT-Größe der "
                               "Übertragungsfunktion an und liefert sofort ruhige Kurven.")
        tb.addWidget(self.cb_gen)
        self.sp_gen_level = QtWidgets.QDoubleSpinBox(minimum=-80, maximum=0, value=-18, suffix=" dBFS")
        tb.addWidget(self.sp_gen_level)
        self.sp_gen_freq = QtWidgets.QDoubleSpinBox(minimum=10, maximum=24000, value=1000, suffix=" Hz")
        tb.addWidget(self.sp_gen_freq)
        tb.addWidget(QtWidgets.QLabel(" an "))
        self.cb_gen_out = QtWidgets.QComboBox()
        tb.addWidget(self.cb_gen_out)
        self.a_gen = QtGui.QAction("Generator EIN", self, checkable=True, toggled=self.update_generator)
        self.a_gen.setToolTip("Generator ein/aus mit Ein-/Ausblenden (G)")
        tb.addAction(self.a_gen)
        self.a_mute = QtGui.QAction("STUMM", self, triggered=self.mute)
        self.a_mute.setToolTip("Generator sofort stummschalten (M)")
        tb.addAction(self.a_mute)
        self.mute_button = tb.widgetForAction(self.a_mute)
        for w in (self.cb_gen, self.cb_gen_out):
            w.currentIndexChanged.connect(lambda _: self.update_generator(self.a_gen.isChecked()))
        for w in (self.sp_gen_level, self.sp_gen_freq):
            w.valueChanged.connect(self._generator_params)
        tb.addSeparator()
        self.a_remote = QtGui.QAction("📱 Fernbedienung…", self, triggered=self.configure_remote)
        self.a_remote.setToolTip("Mit Handy/Tablet im selben WLAN messen und steuern")
        tb.addAction(self.a_remote)
        self.a_tuning = QtGui.QAction(self, triggered=self.configure_tuning)
        self.a_tuning.setToolTip("Kammerton (Bezugston A4) für die Notenanzeige einstellen oder messen")
        tb.addAction(self.a_tuning)
        self.state.tuning_changed.connect(self._tuning_changed)
        self._tuning_changed()
        self._style_mute(False)

    def configure_tuning(self) -> None:
        TuningDialog(self.state, self).exec()

    def configure_remote(self) -> None:
        RemoteDialog(self.remote, self).exec()

    def _remote_status(self) -> None:
        if not self.remote.running:
            self.lbl_remote.setText("")
            return
        n = self.remote.clients()
        self.lbl_remote.setText(f"📱 Fernbedienung an · {n} Gerät{'e' if n != 1 else ''} verbunden")

    def _tuning_changed(self) -> None:
        self.a_tuning.setText(f"♪ Kammerton A4 = {self.state.a4:g} Hz…")

    def _build_statusbar(self) -> None:
        sb = self.statusBar()
        self.lbl_device = QtWidgets.QLabel()
        self.lbl_levels = QtWidgets.QLabel()
        self.lbl_levels.setStyleSheet("font-family: Consolas, Menlo, monospace;")
        sb.addWidget(self.lbl_device, 1)
        self.btn_update = QtWidgets.QPushButton()
        self.btn_update.setFlat(True)
        self.btn_update.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_update.setStyleSheet("color: #4c97ff; font-weight: bold;")
        self.btn_update.clicked.connect(self.open_updates)
        self.btn_update.hide()
        sb.addPermanentWidget(self.btn_update)
        self.lbl_remote = QtWidgets.QLabel()
        self.lbl_remote.setStyleSheet("color: #66dd66;")
        sb.addPermanentWidget(self.lbl_remote)
        sb.addPermanentWidget(self.lbl_levels)
        self.meter_timer = QtCore.QTimer(self, interval=150, timeout=self._update_levels)
        self.meter_timer.start()

    def show_shortcuts(self) -> None:
        rows = "".join(f"<tr><td style='padding:3px 14px 3px 0'><b>{k}</b></td><td>{v}</td></tr>"
                       for k, v in SHORTCUTS)
        QtWidgets.QMessageBox.information(self, "Tastenkürzel", f"<table>{rows}</table>"
                                          "<p>Einzeltasten wirken nicht, solange in ein Eingabefeld "
                                          "getippt wird.</p>")

    # --- Tastenkürzel ------------------------------------------------------------------
    def key_action(self, key: int, shift: bool):
        K = QtCore.Qt.Key
        tab = self.tabs.currentWidget()
        rt = self.realtime
        table = {
            (K.Key_Space, False): self.a_run.toggle,
            (K.Key_G, False): self.a_gen.toggle,
            (K.Key_M, False): self.mute,
            (K.Key_1, False): lambda: self.tabs.setCurrentWidget(self.realtime),
            (K.Key_2, False): lambda: self.tabs.setCurrentWidget(self.impulse),
            (K.Key_3, False): lambda: self.tabs.setCurrentWidget(self.spl),
        }
        if tab is rt:
            table.update({
                (K.Key_S, False): rt.capture_current,
                (K.Key_S, True): rt.capture_spec,
                (K.Key_D, False): rt.find_delay,
                (K.Key_R, False): rt.reset_averages,
                (K.Key_P, False): rt.chk_peak.toggle,
            })
        elif tab is self.impulse:
            table.update({(K.Key_Return, False): self.impulse.measure,
                          (K.Key_Enter, False): self.impulse.measure})
        elif tab is self.spl:
            table[(K.Key_N, False)] = self.spl.ed_note.setFocus
        return table.get((key, shift))

    # --- Audio -----------------------------------------------------------------
    def configure_audio(self) -> None:
        dlg = AudioDialog(self.state.config, self)
        if dlg.exec():
            was_running = self.state.engine is not None
            self.state.save_config(dlg.result_config())
            if was_running:
                self.toggle_audio(True)
            else:
                self._engine_changed(None)

    def toggle_audio(self, on: bool) -> None:
        if on:
            try:
                self.state.start()
            except Exception as exc:  # noqa: BLE001 – Gerätefehler anzeigen
                self.a_run.blockSignals(True)
                self.a_run.setChecked(False)
                self.a_run.blockSignals(False)
                QtWidgets.QMessageBox.critical(
                    self, "Audio", f"Audio-Gerät konnte nicht gestartet werden:\n\n{exc}\n\n"
                    "Abtastrate, Kanalzahl und ob das Gerät von einem anderen Programm belegt ist prüfen.")
                return
            self.update_generator(self.a_gen.isChecked())
        else:
            self.state.stop()

    def _engine_changed(self, engine) -> None:
        cfg = self.state.config
        running = engine is not None
        self.a_run.blockSignals(True)
        self.a_run.setChecked(running)
        self.a_run.setText("■ Audio stoppen" if running else "▶ Audio starten")
        self.a_run.blockSignals(False)
        set_channel_count(self.cb_gen_out, self.state.output_channels, "Ausgang")
        dev = cfg.input_device if cfg.input_device == cfg.output_device or not cfg.output_device \
            else f"{cfg.input_device} → {cfg.output_device}"
        api = f" [{cfg.host_api}]" if cfg.host_api else ""
        self.lbl_device.setText(f"{'● Läuft' if running else '○ Gestoppt'} · {dev}{api} · "
                                f"{self.state.fs} Hz")

    # --- Generator -----------------------------------------------------------------
    def update_generator(self, on: bool) -> None:
        eng = self.state.engine
        self.a_gen.setText("Generator AUS" if on else "Generator EIN")
        self._style_mute(on)
        if eng is None:
            return
        name = self.cb_gen.currentText()
        if not on or name == "Aus":
            eng.set_generator(None, [])
            return
        cls = GENERATORS[name]
        level = min(self.sp_gen_level.value(), self.state.level_limit_db)
        if cls is PeriodicPinkNoise:
            gen = cls(eng.fs, level, length=self.realtime.tf_period())
        else:
            gen = cls(eng.fs, level)
        if isinstance(gen, Sine):
            gen.freq = self.sp_gen_freq.value()
        eng.set_generator(gen, [self.cb_gen_out.currentData() or 0])

    def mute(self) -> None:
        if self.state.engine is not None:
            self.state.engine.mute()
        self.a_gen.blockSignals(True)
        self.a_gen.setChecked(False)
        self.a_gen.blockSignals(False)
        self.a_gen.setText("Generator EIN")
        self._style_mute(False)

    def _style_mute(self, active: bool) -> None:
        if self.mute_button is not None:
            self.mute_button.setStyleSheet(
                "QToolButton { background: #c62828; color: white; font-weight: bold; padding: 2px 10px; }"
                if active else "QToolButton { color: #888; padding: 2px 10px; }")

    def _fft_changed(self) -> None:
        """Periodisches Rauschen muss zur FFT-Größe der Übertragungsfunktion passen."""
        eng = self.state.engine
        if eng is not None and isinstance(eng.generator, PeriodicPinkNoise) and self.a_gen.isChecked():
            self.update_generator(True)

    def _generator_params(self) -> None:
        eng = self.state.engine
        if eng is not None and eng.generator is not None:
            eng.generator.level_db = min(self.sp_gen_level.value(), self.state.level_limit_db)
            if isinstance(eng.generator, Sine):
                eng.generator.freq = self.sp_gen_freq.value()

    def _apply_level_limit(self) -> None:
        self.sp_gen_level.setMaximum(self.state.level_limit_db)
        self.sp_gen_level.setToolTip(f"Pegelgrenze: {self.state.level_limit_db:g} dBFS "
                                     "(Menü Generator → Einstellungen)")
        self._generator_params()

    def _update_levels(self) -> None:
        self._remote_status()
        eng = self.state.engine
        if eng is None:
            self.lbl_levels.setText("")
            return
        parts = []
        for i, p in enumerate(eng.peak[:8]):
            db = 20 * np.log10(p + 1e-12)
            mark = "  ÜBERSTEUERT" if db > -0.5 else ""
            parts.append(f"E{i + 1}: {max(db, -99):5.1f} dBFS{mark}")
        self.lbl_levels.setText("   ".join(parts))

    # --- Sitzungen ------------------------------------------------------------------
    def collect_session(self) -> tuple[dict, dict]:
        meta = {"app_version": __version__, "a4": self.state.a4, "note_naming": self.state.note_naming,
                "tab": self.tabs.currentIndex(),
                "generator": {"name": self.cb_gen.currentText(), "level": self.sp_gen_level.value(),
                              "freq": self.sp_gen_freq.value()}}
        arrays: dict = {}
        for key, view in (("realtime", self.realtime), ("impulse", self.impulse), ("spl", self.spl)):
            m, a = view.get_state()
            meta[key] = m
            arrays.update(a)
        return meta, arrays

    def apply_session(self, meta: dict, arrays: dict) -> None:
        self.state.set_tuning(meta.get("a4", self.state.a4), meta.get("note_naming", self.state.note_naming))
        gen = meta.get("generator", {})
        if gen.get("name") in GENERATORS:
            self.cb_gen.setCurrentText(gen["name"])
        self.sp_gen_level.setValue(gen.get("level", self.sp_gen_level.value()))
        self.sp_gen_freq.setValue(gen.get("freq", self.sp_gen_freq.value()))
        self.realtime.set_state(meta.get("realtime", {}), arrays)
        self.impulse.set_state(meta.get("impulse", {}), arrays)
        self.spl.set_state(meta.get("spl", {}), arrays)
        self.tabs.setCurrentIndex(int(meta.get("tab", 0)))

    def _update_title(self) -> None:
        name = os.path.basename(self.session_path) if self.session_path else "Neue Sitzung"
        self.setWindowTitle(f"{name} – {APP_NAME} {__version__}")

    def new_session(self) -> None:
        if QtWidgets.QMessageBox.question(
                self, "Neue Sitzung", "Alle gespeicherten Kurven, die Impulsantwort und die "
                "SPL-Notizen verwerfen?") != QtWidgets.QMessageBox.Yes:
            return
        self.realtime.set_state({}, {})
        self.impulse.set_state({}, {})
        self.spl.reset()
        self.spl.set_state({}, {})
        self.session_path = None
        self._update_title()

    def open_session(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Sitzung öffnen", "", FILE_FILTER)
        if path:
            self.load_from(path)

    def load_from(self, path: str) -> bool:
        try:
            meta, arrays = load_session(path)
        except (OSError, ValueError, KeyError) as exc:
            QtWidgets.QMessageBox.warning(self, "Sitzung", f"Sitzung konnte nicht geladen werden:\n{exc}")
            return False
        self.apply_session(meta, arrays)
        if path != self.autosave_path:
            self.session_path = path
        self._update_title()
        self.statusBar().showMessage(f"Sitzung geladen: {path}", 5000)
        return True

    def save_session(self) -> None:
        if self.session_path is None:
            self.save_session_as()
        else:
            self.save_to(self.session_path)

    def save_session_as(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Sitzung speichern",
                                                        self.session_path or "messung" + EXTENSION,
                                                        FILE_FILTER)
        if path:
            if not path.lower().endswith(EXTENSION):
                path += EXTENSION
            self.save_to(path)

    def save_to(self, path: str) -> bool:
        try:
            save_session(path, *self.collect_session())
        except OSError as exc:
            QtWidgets.QMessageBox.warning(self, "Sitzung", f"Speichern fehlgeschlagen:\n{exc}")
            return False
        self.session_path = path
        self._update_title()
        self.statusBar().showMessage(f"Sitzung gespeichert: {path}", 5000)
        return True

    def autosave(self) -> None:
        try:
            save_session(self.autosave_path, *self.collect_session())
        except OSError:
            pass  # automatische Sicherung darf den Messbetrieb nie stören

    def _check_recovery(self) -> None:
        crashed = not self.state.settings.value("clean_exit", True, type=bool)
        self.state.settings.setValue("clean_exit", False)
        if crashed and os.path.exists(self.autosave_path):
            if QtWidgets.QMessageBox.question(
                    self, "Wiederherstellen",
                    "Das Programm wurde zuletzt nicht regulär beendet.\n"
                    "Die automatisch gesicherte Sitzung (Kurven, Impulsantwort, SPL-Verlauf und "
                    "Notizen) wiederherstellen?") == QtWidgets.QMessageBox.Yes:
                self.load_from(self.autosave_path)

    def closeEvent(self, event) -> None:
        self.remote.stop()
        self.spl.toggle_log(False)
        self.autosave()
        self.state.settings.setValue("clean_exit", True)
        QtWidgets.QApplication.instance().removeEventFilter(self.shortcut_filter)
        self.state.stop()
        super().closeEvent(event)
