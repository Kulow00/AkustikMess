"""Fernbedienung: Server (Schlüssel, Befehle, JSON) und Zusammenspiel mit der Oberfläche."""

import json
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from akustik.remote.server import RemoteServer
from conftest import make_window, wait


def http(url, data=None, token=None, timeout=10):
    req = urllib.request.Request(url, data=None if data is None else json.dumps(data).encode(),
                                 method="POST" if data is not None else "GET")
    if token:
        req.add_header("X-Token", token)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


# --- Server allein ---------------------------------------------------------------------

def test_server_token_snapshot_and_commands():
    srv = RemoteServer(port=0, host="127.0.0.1", token="geheim123")
    srv.start()
    try:
        base = f"http://127.0.0.1:{srv.port}"
        assert http(base + "/")[0] == 403                       # ohne Schlüssel
        assert http(base + "/?t=falsch")[0] == 403
        code, body = http(base + "/?t=geheim123")
        assert code == 200 and b"AkustikMess" in body
        srv.set_snapshot({"x": 1, "arr": [1.5, None]})
        code, body = http(base + "/api/state", token="geheim123")
        assert json.loads(body) == {"x": 1, "arr": [1.5, None]}
        with pytest.raises(ValueError):
            srv.set_snapshot({"bad": float("nan")})             # NaN wäre kein gültiges JSON
        # Befehl: der „GUI-Thread“ (hier: Hauptthread) arbeitet die Warteschlange ab
        seen = []
        stop = threading.Event()

        def gui_loop():
            while not stop.is_set():
                srv.drain(lambda a, args: seen.append((a, args)) or {"ok": True, "message": "erledigt"})
                stop.wait(0.01)

        t = threading.Thread(target=gui_loop)
        t.start()
        code, body = http(base + "/api/cmd", {"action": "capture_tf", "args": {"name": "FOH"}}, "geheim123")
        stop.set()
        t.join()
        assert code == 200 and json.loads(body)["message"] == "erledigt"
        assert seen == [("capture_tf", {"name": "FOH"})]
        assert http(base + "/api/cmd", {"action": "x"}, "falsch")[0] == 403
        assert srv.active_clients() == 1
    finally:
        srv.stop()
    assert not srv.running


# --- mit Oberfläche --------------------------------------------------------------------

@pytest.fixture(scope="module")
def remote_win(tmp_path_factory):
    app, w = make_window(tmp_path_factory.mktemp("remote"))
    w.remote.start(port=0)
    wait(app, 1.0)
    w.realtime.find_delay()
    yield app, w
    w.close()


def call(app, w, method, path, data=None, token=None):
    """HTTP-Anfrage im Hintergrund, während die Oberfläche weiterläuft."""
    token = w.remote.server.token if token is None else token
    url = f"http://127.0.0.1:{w.remote.server.port}{path}"
    with ThreadPoolExecutor(1) as ex:
        fut = ex.submit(http, url, data, token)
        while not fut.done():
            wait(app, 0.02)
        code, body = fut.result()
    return code, (json.loads(body) if body[:1] in (b"{", b"[") else body)


def test_state_contains_live_data(remote_win):
    app, w = remote_win
    w.tabs.setCurrentWidget(w.spl)  # Echtzeit-Ansicht verdeckt – Handy bekommt trotzdem Daten
    call(app, w, "GET", "/api/state")
    wait(app, 2.0)
    code, s = call(app, w, "GET", "/api/state")
    assert code == 200 and s["running"] is True
    assert len(s["tf"]["f"]) > 100 and len(s["tf"]["f"]) <= 320
    assert s["spec"]["unit"] in ("dB SPL", "dBFS")
    assert s["gen"]["on"] is True and s["delay_ms"] == pytest.approx(8.0, abs=0.1)
    assert "Spitze" in s["peak"]
    assert s["spl"]["main"] and len(s["spl"]["tiles"]) > 3
    assert all(v is None or np.isfinite(v) for v in s["tf"]["mag"])
    w.tabs.setCurrentWidget(w.realtime)


def test_commands_from_phone(remote_win):
    app, w = remote_win
    n = len(w.realtime.traces.traces)
    code, r = call(app, w, "POST", "/api/cmd", {"action": "capture_tf", "args": {"name": "Reihe 10 links"}})
    assert r["ok"] and "Reihe 10 links" in r["message"]
    assert len(w.realtime.traces.traces) == n + 1
    code, s = call(app, w, "GET", "/api/state")
    wait(app, 0.4)
    code, s = call(app, w, "GET", "/api/state")
    assert any(t["name"].startswith("Reihe 10 links") for t in s["traces"])
    code, r = call(app, w, "POST", "/api/cmd", {"action": "gen_level", "args": {"delta": -3}})
    assert r["ok"] and w.sp_gen_level.value() == pytest.approx(-21.0)
    code, r = call(app, w, "POST", "/api/cmd", {"action": "gen_toggle"})
    assert r["ok"] and not w.a_gen.isChecked()
    call(app, w, "POST", "/api/cmd", {"action": "gen_toggle"})
    assert w.a_gen.isChecked()
    code, r = call(app, w, "POST", "/api/cmd", {"action": "spl_note", "args": {"text": "Band startet"}})
    assert r["ok"] and w.spl.notes[-1][1] == "Band startet"
    code, r = call(app, w, "POST", "/api/cmd", {"action": "gibtsnicht"})
    assert not r["ok"]
    code, r = call(app, w, "POST", "/api/cmd", {"action": "mute"}, token="falsch")
    assert code == 403 and w.a_gen.isChecked()


def test_impulse_measurement_from_phone(remote_win):
    app, w = remote_win
    w.impulse.cb_len.setCurrentIndex(w.impulse.cb_len.findData(1))
    w.impulse.sp_tail.setValue(1.8)
    code, r = call(app, w, "POST", "/api/cmd", {"action": "ir_measure"})
    assert r["ok"]
    for _ in range(150):
        wait(app, 0.1)
        code, s = call(app, w, "GET", "/api/state")
        if s["ir"]["table"] and not s["ir"]["busy"]:
            break
    assert "STI" in s["ir"]["sti"]
    assert s["ir"]["table"]["bands"][-1] == "Gesamt"
    assert any(row[0].startswith("T30") for row in s["ir"]["table"]["rows"])


def test_stop_releases_port(remote_win):
    app, w = remote_win
    port = w.remote.server.port
    w.remote.stop()
    assert not w.remote.running
    srv = RemoteServer(port=port, host="127.0.0.1")
    srv.start()       # Port ist wieder frei
    srv.stop()
