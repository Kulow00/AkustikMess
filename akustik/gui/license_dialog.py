"""Lizenz in der Oberfläche: Schlüssel eintragen, Status anzeigen, Sperrliste aktualisieren."""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from .. import APP_NAME, RELEASE_DATE, license_config, licensing


class _RevocationWorker(QtCore.QThread):
    done = QtCore.Signal(object)   # set[str] | None

    def run(self) -> None:
        try:
            self.done.emit(licensing.fetch_revocations())
        except Exception:  # noqa: BLE001 – offline o. Ä.: alte Liste behalten
            self.done.emit(None)


class LicenseManager(QtCore.QObject):
    changed = QtCore.Signal(object)   # licensing.Status

    def __init__(self, settings: QtCore.QSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.worker: _RevocationWorker | None = None

    @property
    def enabled(self) -> bool:
        return licensing.enabled()

    @property
    def required(self) -> bool:
        return self.enabled and license_config.ENFORCEMENT == "required"

    @property
    def token(self) -> str:
        return str(self.settings.value("license_token", "") or "")

    @property
    def revoked(self) -> frozenset[str]:
        raw = self.settings.value("license_revoked", "") or ""
        return frozenset(i for i in str(raw).split(",") if i)

    def status(self) -> licensing.Status:
        return licensing.evaluate(self.token, self.revoked, release_date=RELEASE_DATE or None)

    def install(self, token: str) -> licensing.Status:
        token = "".join((token or "").split())
        licensing.parse(token)          # wirft LicenseError mit verständlicher Meldung
        self.settings.setValue("license_token", token)
        st = self.status()
        self.changed.emit(st)
        return st

    def remove(self) -> None:
        self.settings.remove("license_token")
        self.changed.emit(self.status())

    def has(self, feature: str) -> bool:
        """Für spätere kostenpflichtige Funktionen: ``if self.licenses.has("pro"): …``"""
        return not self.enabled or feature in self.status().features

    def refresh_revocations(self) -> None:
        """Nur aufrufen, wenn der Nutzer Netzwerkzugriffe (Update-Suche) erlaubt hat."""
        if not self.enabled or not self.token or (self.worker is not None and self.worker.isRunning()):
            return
        self.worker = _RevocationWorker()
        self.worker.done.connect(self._revocations)
        self.worker.start()

    def _revocations(self, ids) -> None:
        if ids is None:
            return
        self.settings.setValue("license_revoked", ",".join(sorted(ids)))
        self.changed.emit(self.status())


STATE_COLORS = {"valid": "#3ec46d", "none": "#ffaa33"}


class LicenseDialog(QtWidgets.QDialog):
    def __init__(self, manager: LicenseManager, parent=None):
        super().__init__(parent)
        self.mgr = manager
        self.setWindowTitle("Lizenz")
        self.setMinimumWidth(560)
        lay = QtWidgets.QVBoxLayout(self)
        self.lbl_status = QtWidgets.QLabel()
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        lay.addWidget(self.lbl_status)

        lay.addWidget(QtWidgets.QLabel("Lizenzschlüssel einfügen (aus der E-Mail bzw. von der Webseite):"))
        self.edit = QtWidgets.QPlainTextEdit()
        self.edit.setPlaceholderText("AKM1.…")
        self.edit.setFixedHeight(90)
        lay.addWidget(self.edit)
        self.lbl_error = QtWidgets.QLabel()
        self.lbl_error.setStyleSheet("color: #ff5555;")
        self.lbl_error.setWordWrap(True)
        lay.addWidget(self.lbl_error)

        row = QtWidgets.QHBoxLayout()
        self.btn_apply = QtWidgets.QPushButton("Übernehmen")
        self.btn_apply.clicked.connect(self.apply)
        btn_file = QtWidgets.QPushButton("Aus Datei laden…")
        btn_file.clicked.connect(self.load_file)
        self.btn_register = QtWidgets.QPushButton("Kostenlos registrieren…")
        self.btn_register.clicked.connect(
            lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl(license_config.REGISTER_URL)))
        self.btn_remove = QtWidgets.QPushButton("Lizenz entfernen")
        self.btn_remove.clicked.connect(self._remove)
        for b in (self.btn_apply, btn_file, self.btn_register):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self.btn_remove)
        lay.addLayout(row)

        info = QtWidgets.QLabel(
            "Die Lizenz wird nur auf diesem Rechner geprüft, es werden keine Daten gesendet. "
            "Gesperrte Lizenzen erkennt das Programm über die Update-Suche, falls du sie erlaubt hast.")
        info.setWordWrap(True)
        info.setStyleSheet("color: gray;")
        lay.addWidget(info)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.refresh()

    def refresh(self) -> None:
        st = self.mgr.status()
        color = STATE_COLORS.get(st.state, "#ff5555")
        text = f'<b style="color:{color}">{st.message}</b>'
        if st.license:
            lic = st.license
            text += (f"<br>Lizenziert für: {lic.name} &lt;{lic.email}&gt;<br>Plan: {lic.plan_label} · "
                     f"Lizenz-ID: {lic.id} · ausgestellt am {lic.issued}")
        elif st.state == "none":
            text += (f"<br>{APP_NAME} ist kostenlos. Mit einer Registrierung bekommst du einen persönlichen "
                     "Lizenzschlüssel und hilfst bei der Weiterentwicklung.")
        self.lbl_status.setText(text)
        self.btn_remove.setVisible(bool(self.mgr.token))
        self.btn_register.setVisible(st.state != "valid")

    def apply(self) -> None:
        try:
            st = self.mgr.install(self.edit.toPlainText())
        except licensing.LicenseError as exc:
            self.lbl_error.setText(str(exc))
            return
        self.lbl_error.setText("" if st.valid else st.message)
        self.edit.clear()
        self.refresh()

    def load_file(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Lizenzdatei laden", "",
                                                        "AkustikMess-Lizenz (*.akmlic *.txt);;Alle Dateien (*)")
        if path:
            with open(path, encoding="utf-8", errors="replace") as fh:
                self.edit.setPlainText(fh.read(8192))
            self.apply()

    def _remove(self) -> None:
        if QtWidgets.QMessageBox.question(self, "Lizenz entfernen",
                                          "Lizenz von diesem Rechner entfernen?") == QtWidgets.QMessageBox.Yes:
            self.mgr.remove()
            self.refresh()
