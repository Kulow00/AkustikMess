"""Updates in der Oberfläche: Prüfen im Hintergrund, Hinweis, Patch Notes, Installation.

Grundsatz: Ein Update unterbricht nie eine laufende Messung. Gefundene Updates
erscheinen nur als Hinweis in der Statusleiste; installiert wird ausschließlich
nach ausdrücklicher Bestätigung.

Datenschutz: Automatisch gesucht wird erst, nachdem der Nutzer beim ersten Start
zugestimmt hat. Abgerufen wird nur das öffentliche Release-Verzeichnis; es werden
keine Daten über Nutzer oder Messungen gesendet.
"""

from __future__ import annotations

import time

from PySide6 import QtCore, QtGui, QtWidgets

from .. import APP_NAME, COPYRIGHT, __version__, update
from ..license_config import SITE_URL
from ..update_config import MANIFEST_URL


class _CheckWorker(QtCore.QThread):
    done = QtCore.Signal(object, str)   # Update | None, Fehlermeldung

    def __init__(self, url: str, channel: str):
        super().__init__()
        self.url, self.channel = url, channel

    def run(self) -> None:
        try:
            manifest = update.fetch_manifest(self.url)
            self.done.emit(update.select_update(manifest, __version__, self.channel), "")
        except update.UpdateError as exc:
            self.done.emit(None, str(exc))
        except Exception as exc:  # noqa: BLE001
            self.done.emit(None, f"Unerwarteter Fehler: {exc}")


class _DownloadWorker(QtCore.QThread):
    progress = QtCore.Signal(int, int)
    done = QtCore.Signal(str, str)      # Pfad, Fehlermeldung

    def __init__(self, asset: dict):
        super().__init__()
        self.asset = asset
        self.cancelled = False

    def run(self) -> None:
        try:
            path = update.download(self.asset, progress=self.progress.emit, cancel=lambda: self.cancelled)
            self.done.emit(path, "")
        except update.UpdateError as exc:
            self.done.emit("", str(exc))


class UpdateManager(QtCore.QObject):
    """Einstellungen und Hintergrundprüfung (eine Instanz pro Hauptfenster)."""

    checked = QtCore.Signal(object, str)

    def __init__(self, settings: QtCore.QSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.worker: _CheckWorker | None = None
        self.last: update.Update | None = None

    @property
    def url(self) -> str:
        return str(self.settings.value("update_url", "") or MANIFEST_URL)

    @url.setter
    def url(self, value: str) -> None:
        self.settings.setValue("update_url", "" if value.strip() == MANIFEST_URL else value.strip())

    @property
    def channel(self) -> str:
        ch = str(self.settings.value("update_channel", "beta" if update.is_prerelease(__version__) else "stable"))
        return ch if ch in update.CHANNELS else "stable"

    @channel.setter
    def channel(self, value: str) -> None:
        self.settings.setValue("update_channel", value)

    @property
    def auto(self) -> bool:
        return self.settings.value("update_auto", False, type=bool)

    @property
    def consent_asked(self) -> bool:
        return self.settings.contains("update_auto")

    @auto.setter
    def auto(self, value: bool) -> None:
        self.settings.setValue("update_auto", bool(value))

    @property
    def skipped(self) -> str:
        return str(self.settings.value("update_skip", ""))

    def skip(self, version: str) -> None:
        self.settings.setValue("update_skip", version)

    def check(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        if not self.url:
            self.checked.emit(None, "Keine Update-Adresse eingestellt.")
            return
        self.worker = _CheckWorker(self.url, self.channel)
        self.worker.done.connect(self._done)
        self.worker.start()

    def _done(self, upd, err: str) -> None:
        self.last = upd
        self.settings.setValue("update_last_check", time.time())
        self.checked.emit(upd, err)


def ask_consent(manager: UpdateManager, parent=None) -> bool:
    """Einmalige Frage beim ersten Start, ob automatisch nach Updates gesucht werden darf."""
    host = QtCore.QUrl(manager.url).host() or manager.url
    box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Question, "Automatische Updates",
                                f"Soll {APP_NAME} beim Start automatisch nach neuen Versionen suchen?",
                                parent=parent)
    box.setInformativeText(f"Dazu wird nur das öffentliche Release-Verzeichnis von {host} abgerufen. "
                           "Es werden keine Daten über dich oder deine Messungen gesendet. Installiert wird "
                           "nie ohne Rückfrage.\n\nÄndern jederzeit unter Hilfe → Nach Updates suchen…")
    yes = box.addButton("Ja, automatisch suchen", QtWidgets.QMessageBox.YesRole)
    box.addButton("Nein", QtWidgets.QMessageBox.NoRole)
    box.setDefaultButton(yes)
    box.exec()
    manager.auto = box.clickedButton() is yes
    return manager.auto


class UpdateDialog(QtWidgets.QDialog):
    def __init__(self, manager: UpdateManager, main_window, parent=None):
        super().__init__(parent or main_window)
        self.mgr, self.win = manager, main_window
        self.setWindowTitle("Updates")
        self.setMinimumSize(560, 520)
        self.upd: update.Update | None = None
        self.dl: _DownloadWorker | None = None
        lay = QtWidgets.QVBoxLayout(self)

        installed = "Installierte Fassung" if update.is_installed_build() else "Entwicklerfassung (Quelltext)"
        head = QtWidgets.QLabel(f"<b>{APP_NAME} {__version__}</b> · {installed} · "
                                f"{update.PLATFORM_LABELS[update.current_platform()]}")
        lay.addWidget(head)
        form = QtWidgets.QFormLayout()
        self.cb_channel = QtWidgets.QComboBox()
        for ch in update.CHANNELS:
            self.cb_channel.addItem(update.CHANNEL_LABELS[ch], ch)
        self.cb_channel.setCurrentIndex(self.cb_channel.findData(manager.channel))
        self.cb_channel.currentIndexChanged.connect(self._channel_changed)
        form.addRow("Update-Kanal", self.cb_channel)
        self.lbl_beta = QtWidgets.QLabel("Beta: neue Funktionen früher, aber noch nicht vollständig erprobt. "
                                         "Für wichtige Veranstaltungen den stabilen Kanal verwenden.")
        self.lbl_beta.setWordWrap(True)
        self.lbl_beta.setStyleSheet("color: #ffaa33;")
        form.addRow(self.lbl_beta)
        self.chk_auto = QtWidgets.QCheckBox("Beim Start automatisch nach Updates suchen")
        self.chk_auto.setChecked(manager.auto)
        self.chk_auto.toggled.connect(lambda on: setattr(manager, "auto", on))
        form.addRow(self.chk_auto)
        self.ed_url = QtWidgets.QLineEdit(manager.url, placeholderText="https://…/releases.json")
        self.ed_url.setToolTip("Adresse des Release-Verzeichnisses (eigener Server oder Dropbox-Link)")
        self.ed_url.editingFinished.connect(lambda: setattr(manager, "url", self.ed_url.text()))
        form.addRow("Update-Adresse", self.ed_url)
        lay.addLayout(form)

        row = QtWidgets.QHBoxLayout()
        self.btn_check = QtWidgets.QPushButton("Jetzt prüfen")
        self.btn_check.clicked.connect(self.check)
        self.lbl_status = QtWidgets.QLabel("")
        self.lbl_status.setWordWrap(True)
        row.addWidget(self.btn_check)
        row.addWidget(self.lbl_status, 1)
        lay.addLayout(row)
        self.notes = QtWidgets.QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        lay.addWidget(self.notes, 1)
        self.progress = QtWidgets.QProgressBar()
        self.progress.setVisible(False)
        lay.addWidget(self.progress)
        row = QtWidgets.QHBoxLayout()
        self.btn_skip = QtWidgets.QPushButton("Diese Version überspringen")
        self.btn_skip.clicked.connect(self._skip)
        self.btn_install = QtWidgets.QPushButton("Herunterladen und installieren")
        self.btn_install.setStyleSheet("font-weight: bold; padding: 6px 12px;")
        self.btn_install.clicked.connect(self.install)
        row.addWidget(self.btn_skip)
        row.addStretch(1)
        row.addWidget(self.btn_install)
        lay.addLayout(row)
        self._show(None, "")
        self._channel_changed()
        manager.checked.connect(self._checked)
        if manager.last is not None:
            self._show(manager.last, "")

    # --- Prüfen ---------------------------------------------------------------------
    def _channel_changed(self) -> None:
        self.mgr.channel = self.cb_channel.currentData()
        self.lbl_beta.setVisible(self.mgr.channel == "beta")

    def check(self) -> None:
        self.mgr.url = self.ed_url.text()
        self.lbl_status.setText("Prüfe …")
        self.btn_check.setEnabled(False)
        self.mgr.check()

    def _checked(self, upd, err: str) -> None:
        self.btn_check.setEnabled(True)
        self._show(upd, err)

    def _show(self, upd, err: str) -> None:
        self.upd = upd
        has = upd is not None
        self.btn_install.setVisible(has)
        self.btn_skip.setVisible(has)
        if err:
            self.lbl_status.setText(f"<span style='color:#ff6666'>{err}</span>")
            self.notes.clear()
            return
        if not has:
            if self.lbl_status.text() == "Prüfe …":
                self.lbl_status.setText("<span style='color:#66dd66'>Sie verwenden die neueste Version.</span>")
            self.notes.setMarkdown("")
            return
        size = upd.asset.get("size", 0) / 1e6
        beta = " (Beta)" if upd.channel == "beta" else ""
        self.lbl_status.setText(f"<b>Version {upd.version}{beta} verfügbar</b> · {upd.date} · {size:.0f} MB")
        md = "\n\n".join(f"### {v}{' (Beta)' if update.is_prerelease(v) else ''} – {d}\n\n{n}"
                         for v, d, n in upd.notes)
        self.notes.setMarkdown(md)
        if not update.is_installed_build():
            self.btn_install.setText("Installer herunterladen (Browser)")

    def _skip(self) -> None:
        if self.upd is not None:
            self.mgr.skip(self.upd.version)
            self.win.show_update_hint(None)
            self.accept()

    # --- Installieren -----------------------------------------------------------------
    def install(self) -> None:
        if self.upd is None:
            return
        if not update.is_installed_build():
            # Quelltext-Fassung: nichts überschreiben, Installer im Browser laden
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(update.direct_url(self.upd.asset["url"])))
            return
        if self.win.state.engine is not None:
            ans = QtWidgets.QMessageBox.question(
                self, "Update installieren",
                "Für die Installation wird AkustikMess beendet (Audio stoppt, die Sitzung wird "
                "automatisch gesichert) und danach neu gestartet.\n\nJetzt fortfahren?")
            if ans != QtWidgets.QMessageBox.Yes:
                return
        self.btn_install.setEnabled(False)
        self.btn_check.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, max(1, int(self.upd.asset.get("size") or 0)))
        self.dl = _DownloadWorker(self.upd.asset)
        self.dl.progress.connect(lambda d, t: self.progress.setValue(d))
        self.dl.done.connect(self._downloaded)
        self.dl.start()

    def _downloaded(self, path: str, err: str) -> None:
        if err:
            self.progress.setVisible(False)
            self.btn_install.setEnabled(True)
            self.btn_check.setEnabled(True)
            self.lbl_status.setText(f"<span style='color:#ff6666'>{err}</span>")
            return
        self.lbl_status.setText("Prüfsumme in Ordnung – Installation startet …")
        update.launch_installer(path)
        QtCore.QTimer.singleShot(300, self.win.close)  # sichert die Sitzung und gibt die Dateien frei

    def reject(self) -> None:
        if self.dl is not None and self.dl.isRunning():
            self.dl.cancelled = True
            self.dl.wait(2000)
        super().reject()


def license_line(main_window) -> str:
    mgr = getattr(main_window, "licenses", None)
    if mgr is None or not mgr.enabled:
        return ""
    st = mgr.status()
    return f"Lizenz: {st.message}" + (f" – {st.license.name}" if st.valid else "")


class AboutDialog(QtWidgets.QMessageBox):
    def __init__(self, manager: UpdateManager, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Über {APP_NAME}")
        self.setText(
            f"<h3>{APP_NAME} {__version__}</h3>"
            f"Update-Kanal: {update.CHANNEL_LABELS[manager.channel]}<br>"
            f"System: {update.PLATFORM_LABELS[update.current_platform()]} · "
            f"{'installierte Fassung' if update.is_installed_build() else 'Entwicklerfassung'}<br>"
            f"{license_line(parent)}<br>"
            "Messsoftware für Beschallung und Raumakustik.<br>"
            "Bibliotheken: Qt (PySide6), NumPy, SciPy, pyqtgraph, PortAudio (sounddevice), qrcode, cryptography.<br><br>"
            f"{COPYRIGHT}<br>"
            "Alle Rechte vorbehalten. Kostenlos nutzbar gemäß den "
            f'<a href="{SITE_URL}/nutzungsbedingungen.html">Nutzungsbedingungen</a>. '
            "Enthält Fremdkomponenten unter eigenen Lizenzen (u. a. Qt unter LGPL 3.0).")
        self.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)  # Link anklickbar
