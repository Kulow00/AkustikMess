"""Fernbedienung: Brücke zwischen Webserver und Oberfläche, Dialog mit QR-Code."""

from __future__ import annotations

import re
import secrets
import time

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from ..dsp import room
from ..remote.server import RemoteServer
from .common import log_decimate

DEFAULT_PORT = 8765
PLOT_POINTS = 300


def jlist(a, nd: int = 2) -> list:
    """Array → JSON-Liste; NaN/±∞ werden zu null (JSON kennt kein NaN)."""
    return [round(float(v), nd) if np.isfinite(v) else None for v in np.asarray(a, float)]


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).replace("&nbsp;", " ").strip()


class RemoteController(QtCore.QObject):
    status_changed = QtCore.Signal()

    def __init__(self, window):
        super().__init__(window)
        self.win = window
        self.settings = window.state.settings
        self.server: RemoteServer | None = None
        self.cmd_timer = QtCore.QTimer(self, interval=40, timeout=self._drain)
        self.snap_timer = QtCore.QTimer(self, interval=250, timeout=self._publish)

    # --- Start/Stopp -----------------------------------------------------------------
    @property
    def token(self) -> str:
        tok = str(self.settings.value("remote_token", ""))
        if not tok:
            tok = self.new_token()
        return tok

    def new_token(self) -> str:
        tok = secrets.token_urlsafe(12)
        self.settings.setValue("remote_token", tok)
        if self.server is not None:  # laufenden Server mit neuem Schlüssel neu starten
            self.start(self.server.port)
        return tok

    @property
    def port(self) -> int:
        return int(self.settings.value("remote_port", DEFAULT_PORT))

    def start(self, port: int | None = None) -> None:
        self.stop()
        port = self.port if port is None else port
        server = RemoteServer(port=port, token=self.token)
        server.start()  # wirft OSError, wenn der Port belegt ist
        self.server = server
        if port:
            self.settings.setValue("remote_port", port)
        self.cmd_timer.start()
        self.snap_timer.start()
        self._publish(force=True)
        self.status_changed.emit()

    def stop(self) -> None:
        self.cmd_timer.stop()
        self.snap_timer.stop()
        if self.server is not None:
            self.server.stop()
            self.server = None
        self.win.realtime.remote_active = False
        self.status_changed.emit()

    @property
    def running(self) -> bool:
        return self.server is not None

    def clients(self) -> int:
        return self.server.active_clients() if self.server else 0

    # --- Befehle (GUI-Thread) ----------------------------------------------------------
    def _drain(self) -> None:
        if self.server is not None:
            self.server.drain(self.execute)

    def execute(self, action: str, args: dict) -> dict:
        w = self.win
        rt = w.realtime
        name = str(args.get("name", ""))[:60].strip()
        if action == "gen_toggle":
            if w.state.engine is None:
                return {"ok": False, "message": "Audio ist am Laptop nicht gestartet"}
            w.a_gen.toggle()
            return {"ok": True, "message": "Generator " + ("ein" if w.a_gen.isChecked() else "aus")}
        if action == "mute":
            w.mute()
            return {"ok": True, "message": "Stumm"}
        if action == "gen_level":
            delta = float(args.get("delta", 0))
            w.sp_gen_level.setValue(w.sp_gen_level.value() + max(-12.0, min(12.0, delta)))
            return {"ok": True, "message": f"Pegel {w.sp_gen_level.value():.1f} dBFS"}
        if action == "capture_tf":
            if rt.last_tf is None:
                return {"ok": False, "message": "Noch keine Übertragungsfunktion"}
            rt.capture_tf(name or None)
            return {"ok": True, "message": f"Gespeichert: {rt.traces.traces[-1]['name']}"}
        if action == "capture_spec":
            if rt.last_spec is None:
                return {"ok": False, "message": "Noch kein Spektrum"}
            rt.capture_spec(name or None)
            return {"ok": True, "message": f"Gespeichert: {rt.traces.traces[-1]['name']}"}
        if action == "find_delay":
            rt.find_delay()
            return {"ok": True, "message": rt.status.text()}
        if action == "reset_avg":
            rt.reset_averages()
            return {"ok": True, "message": "Mittelung zurückgesetzt"}
        if action == "spl_note":
            text = str(args.get("text", ""))[:120].strip()
            if not text:
                return {"ok": False, "message": "Leere Notiz"}
            w.spl.add_note_text(text)
            return {"ok": True, "message": "Notiz gesetzt"}
        if action == "ir_measure":
            iv = w.impulse
            if w.state.engine is None:
                return {"ok": False, "message": "Audio ist am Laptop nicht gestartet"}
            if iv.worker is not None and iv.worker.isRunning():
                return {"ok": False, "message": "Messung läuft bereits"}
            iv.measure()
            return {"ok": True, "message": "Messung gestartet – bitte Ruhe"}
        return {"ok": False, "message": f"Unbekannter Befehl: {action}"}

    # --- Schnappschuss für das Handy -----------------------------------------------------
    def _publish(self, force: bool = False) -> None:
        srv = self.server
        if srv is None:
            return
        # nur rechnen, wenn ein Handy in den letzten Sekunden abgefragt hat
        active = force or time.monotonic() - srv.last_request < 5.0
        self.win.realtime.remote_active = active
        if active:
            srv.set_snapshot(self.build_snapshot())

    def build_snapshot(self) -> dict:
        w = self.win
        rt, spl, iv = w.realtime, w.spl, w.impulse
        eng = w.state.engine
        snap = {
            "now": time.time(), "running": eng is not None, "status": rt.status.text(),
            "a4": w.state.a4, "naming": w.state.note_naming,
            "gen": {"on": w.a_gen.isChecked(), "name": w.cb_gen.currentText(),
                    "level": w.sp_gen_level.value(), "limit": w.state.level_limit_db},
            "delay_ms": rt.sp_delay.value(),
            "levels": jlist(20 * np.log10(eng.peak[:8] + 1e-12), 1) if eng is not None else [],
            "tf": None, "traces": [], "spec": None, "peak": rt.peak_text,
        }
        if rt.last_tf is not None:
            f, mag, ph, coh = rt.last_tf
            fd, d = log_decimate(f, PLOT_POINTS, mag=("mean", mag), ph=("phase", ph), coh=("mean", coh))
            m, p = d["mag"], d["ph"]
            if rt.chk_blank.isChecked():
                bad = d["coh"] < rt.sp_coh.value()
                m, p = np.where(bad, np.nan, m), np.where(bad, np.nan, p)
            snap["tf"] = {"f": jlist(fd, 1), "mag": jlist(m), "ph": jlist(p, 0), "coh": jlist(d["coh"])}
        for t in rt.traces.of_kind("tf"):
            if t["visible"] and len(snap["traces"]) < 6:
                fd, d = log_decimate(np.asarray(t["freqs"]), PLOT_POINTS, mag=("mean", t["mag"]),
                                     ph=("phase", t["phase"]))
                snap["traces"].append({"name": t["name"], "color": t["color"], "f": jlist(fd, 1),
                                       "mag": jlist(d["mag"]), "ph": jlist(d["ph"], 0)})
        if rt.last_spec is not None:
            x, lv, stepped = rt.last_spec
            if not stepped:
                x, d = log_decimate(x, 400, lv=("max", lv))
                lv = d["lv"]
            snap["spec"] = {"f": jlist(x, 1), "lv": jlist(lv, 1), "stepped": bool(stepped),
                            "unit": rt.p_spec.getAxis("left").labelText or "dB"}
        calibrated = spl.cal_warning.text() == ""
        main = spl.cb_main.currentText()
        snap["spl"] = {
            "main": main, "value": _num(spl.values.get(main)), "unit": "dB" if calibrated else "dBFS",
            "calibrated": calibrated, "warn": spl.sp_warn.value(), "alarm": spl.sp_alarm.value(),
            "tiles": [[n, _num(spl.values.get(n))] for n in spl.selected],
            "notes": [f"{time.strftime('%H:%M', time.localtime(ts))}  {text}" for ts, text in spl.notes[-5:]],
        }
        busy = iv.worker is not None and iv.worker.isRunning()
        ir = {"busy": busy, "status": iv.status.text(), "sti": "", "table": None}
        if iv.results:
            ir["sti"] = strip_html(iv.lbl_sti.text()).split("ohne")[0].strip()
            rows = []
            for key, label in room.METRICS:
                if key in ("edt", "t20", "t30", "c80", "d50"):
                    fmt = "{:.2f}" if key in ("edt", "t20", "t30") else "{:.1f}"
                    rows.append([label, [fmt.format(getattr(r, key)) if np.isfinite(getattr(r, key)) else None
                                         for r in iv.results]])
            ir["table"] = {"bands": [("Gesamt" if r.center is None else r.label) for r in iv.results],
                           "rows": rows}
        snap["ir"] = ir
        return snap


def _num(v) -> float | None:
    return round(float(v), 1) if v is not None and np.isfinite(v) else None


def qr_pixmap(text: str, size: int = 260) -> QtGui.QPixmap:
    import qrcode  # noqa: PLC0415

    qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(text)
    qr.make(fit=True)
    m = qr.get_matrix()
    n = len(m)
    cell = max(1, size // n)
    pix = QtGui.QPixmap(n * cell, n * cell)
    pix.fill(QtGui.QColor("white"))
    p = QtGui.QPainter(pix)
    for y, row in enumerate(m):
        for x, dark in enumerate(row):
            if dark:
                p.fillRect(x * cell, y * cell, cell, cell, QtGui.QColor("black"))
    p.end()
    return pix


class RemoteDialog(QtWidgets.QDialog):
    def __init__(self, controller: RemoteController, parent=None):
        super().__init__(parent)
        self.ctl = controller
        self.setWindowTitle("Fernbedienung (Handy / Tablet)")
        self.setMinimumWidth(520)
        lay = QtWidgets.QVBoxLayout(self)
        info = QtWidgets.QLabel(
            "Handy oder Tablet im <b>selben WLAN</b> wie dieser Laptop verbinden, Fernbedienung "
            "einschalten und den QR-Code mit der Kamera scannen. Keine App nötig, nur der Browser.<br>"
            "<span style='color:#999'>Beim ersten Einschalten fragt Windows ggf. nach der "
            "Firewall-Freigabe: <b>nur „Private Netzwerke“</b> erlauben. Nicht in fremden, "
            "öffentlichen WLANs verwenden.</span>")
        info.setWordWrap(True)
        info.setTextFormat(QtCore.Qt.RichText)
        lay.addWidget(info)
        row = QtWidgets.QHBoxLayout()
        self.btn = QtWidgets.QPushButton()
        self.btn.setCheckable(True)
        self.btn.setMinimumHeight(36)
        self.btn.toggled.connect(self._toggle)
        self.sp_port = QtWidgets.QSpinBox(minimum=1024, maximum=65535, value=controller.port)
        row.addWidget(self.btn, 1)
        row.addWidget(QtWidgets.QLabel("Port"))
        row.addWidget(self.sp_port)
        lay.addLayout(row)
        self.qr = QtWidgets.QLabel()
        self.qr.setAlignment(QtCore.Qt.AlignCenter)
        self.qr.setFixedHeight(300)
        lay.addWidget(self.qr)
        self.cb_url = QtWidgets.QComboBox()
        self.cb_url.currentIndexChanged.connect(self._show_qr)
        lay.addWidget(QtWidgets.QLabel("Adresse (bei mehreren Netzwerken die des WLANs wählen):"))
        lay.addWidget(self.cb_url)
        self.lbl_url = QtWidgets.QLineEdit(readOnly=True)
        lay.addWidget(self.lbl_url)
        row = QtWidgets.QHBoxLayout()
        b_copy = QtWidgets.QPushButton("Adresse kopieren")
        b_copy.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(self.lbl_url.text()))
        b_new = QtWidgets.QPushButton("Neuen Zugangsschlüssel erzeugen")
        b_new.setToolTip("Alte QR-Codes/Lesezeichen funktionieren danach nicht mehr")
        b_new.clicked.connect(self._new_token)
        row.addWidget(b_copy)
        row.addWidget(b_new)
        lay.addLayout(row)
        self.lbl_clients = QtWidgets.QLabel()
        lay.addWidget(self.lbl_clients)
        self.timer = QtCore.QTimer(self, interval=1000, timeout=self._refresh)
        self.timer.start()
        self.btn.blockSignals(True)
        self.btn.setChecked(controller.running)
        self.btn.blockSignals(False)
        self._refresh()

    def _toggle(self, on: bool) -> None:
        if on:
            try:
                self.ctl.start(self.sp_port.value())
            except OSError as exc:
                self.btn.blockSignals(True)
                self.btn.setChecked(False)
                self.btn.blockSignals(False)
                QtWidgets.QMessageBox.warning(self, "Fernbedienung",
                                              f"Port {self.sp_port.value()} ist nicht verfügbar:\n{exc}\n\n"
                                              "Einen anderen Port wählen.")
        else:
            self.ctl.stop()
        self._refresh()

    def _new_token(self) -> None:
        self.ctl.new_token()
        self._refresh()

    def _refresh(self) -> None:
        on = self.ctl.running
        self.btn.setText("■ Fernbedienung AUS schalten" if on else "▶ Fernbedienung EIN schalten")
        self.sp_port.setEnabled(not on)
        urls = self.ctl.server.urls() if on else []
        if [self.cb_url.itemText(i) for i in range(self.cb_url.count())] != urls:
            self.cb_url.blockSignals(True)
            self.cb_url.clear()
            self.cb_url.addItems(urls)
            self.cb_url.blockSignals(False)
            self._show_qr()
        n = self.ctl.clients()
        self.lbl_clients.setText(f"Verbundene Geräte: {n}" if on else "Fernbedienung ist aus.")

    def _show_qr(self) -> None:
        url = self.cb_url.currentText()
        self.lbl_url.setText(url)
        if url:
            self.qr.setPixmap(qr_pixmap(url))
        else:
            self.qr.clear()
            self.qr.setText("QR-Code erscheint nach dem Einschalten")
