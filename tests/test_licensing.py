"""Lizenzen: Signatur, Aussteller-Rechte, Ablauf, Sperrliste, Werkzeug, Lizenzserver, Oberfläche."""

import base64
import datetime as dt
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from akustik import license_config, licensing
from tools import licenses as tool

ROOT_KEY = Ed25519PrivateKey.generate()
SERVER_KEY = Ed25519PrivateKey.generate()


def pub(key):
    return base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw,
                                                          serialization.PublicFormat.Raw)).decode()


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    monkeypatch.setattr(license_config, "ROOT_PUBLIC_KEY", pub(ROOT_KEY))
    monkeypatch.setattr(license_config, "SERVER_PUBLIC_KEY", pub(SERVER_KEY))
    monkeypatch.setattr(license_config, "ENFORCEMENT", "remind")


def payload(**kw):
    p = {"id": "L-TEST1234ABCD", "name": "Alex", "email": "a@example.de", "plan": "community",
         "issued": "2026-10-16", "expires": None, "updates_until": None, "features": []}
    p.update(kw)
    return p


def test_roundtrip_and_tampering():
    token = licensing.sign(payload(), SERVER_KEY, "server")
    lic = licensing.parse(token)
    assert lic.plan == "community" and lic.issuer == "server" and lic.email == "a@example.de"
    assert licensing.parse(token[:40] + "\n  " + token[40:]).id == lic.id      # Umbrüche beim Kopieren egal
    head, body, sig = token.split(".")
    forged = json.loads(base64.urlsafe_b64decode(body + "=="))
    forged["plan"] = "pro"
    body2 = base64.urlsafe_b64encode(json.dumps(forged).encode()).decode().rstrip("=")
    with pytest.raises(licensing.LicenseError, match="Signatur"):
        licensing.parse(f"{head}.{body2}.{sig}")
    with pytest.raises(licensing.LicenseError, match="kein AkustikMess"):
        licensing.parse("hallo")
    with pytest.raises(licensing.LicenseError, match="beschädigt"):
        licensing.parse("AKM1.%%%.###")


def test_server_key_cannot_issue_paid_plans():
    with pytest.raises(licensing.LicenseError, match="nicht vom Lizenzserver"):
        licensing.parse(licensing.sign(payload(plan="pro"), SERVER_KEY, "server"))
    # root darf alles
    assert licensing.parse(licensing.sign(payload(plan="pro"), ROOT_KEY, "root")).plan == "pro"
    # Server-Schlüssel gibt sich als root aus → Signatur passt nicht
    with pytest.raises(licensing.LicenseError, match="Signatur"):
        licensing.parse(licensing.sign(payload(plan="pro"), SERVER_KEY, "root"))


def test_evaluate_expiry_updates_and_features():
    today = dt.date(2026, 10, 16)
    assert licensing.evaluate(None).state == "none"
    assert licensing.evaluate("AKM1.x.y").state == "invalid"
    trial = licensing.sign(payload(plan="trial", expires="2026-11-15"), ROOT_KEY, "root")
    st = licensing.evaluate(trial, today=today)
    assert st.valid and "pro" in st.features and "15.11.2026" in st.message
    assert licensing.evaluate(trial, today=dt.date(2026, 11, 16)).state == "expired"
    bought = licensing.sign(payload(plan="pro", updates_until="2027-10-16"), ROOT_KEY, "root")
    assert licensing.evaluate(bought, release_date="2027-10-01", today=today).valid
    st = licensing.evaluate(bought, release_date="2027-12-01", today=today)
    assert st.state == "updates_expired" and "16.10.2027" in st.message
    assert licensing.evaluate(bought, revoked={"L-TEST1234ABCD"}).state == "revoked"
    assert not licensing.evaluate(licensing.sign(payload(), SERVER_KEY, "server")).features


def test_revocation_list_signed():
    raw = licensing.sign_revocations(["L-AAAA1111BBBB", "kaputt"], SERVER_KEY, "server")
    assert licensing.parse_revocations(raw) == {"L-AAAA1111BBBB"}
    outer = json.loads(raw)
    outer["signed"] = outer["signed"].replace("AAAA", "CCCC")
    with pytest.raises(licensing.LicenseError):
        licensing.parse_revocations(json.dumps(outer).encode())


def test_tool_issue_and_config(tmp_path):
    p = tool.make_payload("Firma X", " Chef@Firma.DE ", "pro", updates_years=1, today=dt.date(2026, 10, 16))
    assert p["email"] == "chef@firma.de" and p["updates_until"] == "2027-10-16" and p["id"].startswith("L-")
    token = tool.issue(p, ROOT_KEY, ledger=tmp_path / "ledger.jsonl")
    assert licensing.parse(token).plan == "pro"
    assert json.loads((tmp_path / "ledger.jsonl").read_text(encoding="utf-8"))["token"] == token
    with pytest.raises(tool.ToolError):
        tool.make_payload("a", "b@c.de", "trial", days=30, expires="2027-01-01")
    cfg = tmp_path / "license_config.py"
    cfg.write_text('ROOT_PUBLIC_KEY = ""\nSERVER_PUBLIC_KEY = ""\n', encoding="utf-8")
    tool.write_key_config("SERVER_PUBLIC_KEY", pub(SERVER_KEY), cfg)
    assert pub(SERVER_KEY) in cfg.read_text(encoding="utf-8")


# --- Lizenzserver --------------------------------------------------------------------------

@pytest.fixture
def server(tmp_path, monkeypatch):
    from server import license_server as ls
    cfg = ls.Config({"AKM_DATA": str(tmp_path / "data"), "AKM_SITE": "https://akmess.example"})
    store = ls.Store(cfg)
    store._key = SERVER_KEY
    mails = []
    mailer = {"verify": lambda c, to, name, code: mails.append(("verify", to, code)),
              "license": lambda c, to, name, token: mails.append(("license", to, token))}
    srv = ThreadingHTTPServer(("127.0.0.1", 0), ls.make_handler(store, cfg, ls.RateLimiter(600, 50), mailer))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield {"url": f"http://127.0.0.1:{srv.server_address[1]}", "store": store, "cfg": cfg, "mails": mails, "ls": ls}
    srv.shutdown()
    srv.server_close()


def post(url, data, ctype="application/json"):
    req = urllib.request.Request(url + "/api/register", data=json.dumps(data).encode(), method="POST",
                                 headers={"Content-Type": ctype})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_register_without_mail_issues_directly(server):
    code, res = post(server["url"], {"name": "Alex K", "email": "Alex@Example.de", "consent": True})
    assert code == 200 and res["status"] == "issued"
    lic = licensing.parse(res["license"])
    assert lic.email == "alex@example.de" and lic.plan == "community" and lic.issuer == "server"
    assert post(server["url"], {"name": "A", "email": "x@y.de", "consent": True})[0] == 400       # Name zu kurz
    assert post(server["url"], {"name": "Alex", "email": "kein-mail", "consent": True})[0] == 400
    assert post(server["url"], {"name": "Alex", "email": "x@y.de", "consent": False})[0] == 400
    assert post(server["url"], {"name": "Alex", "email": "x@y.de", "consent": True}, "text/plain")[0] == 415
    assert post(server["url"], {"name": "Bot", "email": "b@y.de", "consent": True, "website": "spam"}) \
        == (200, {"status": "verify_sent"})
    assert server["store"].db.execute("SELECT COUNT(*) FROM licenses WHERE email='b@y.de'").fetchone()[0] == 0
    for _ in range(2):
        post(server["url"], {"name": "Alex K", "email": "alex@example.de", "consent": True})
    assert post(server["url"], {"name": "Alex K", "email": "alex@example.de", "consent": True})[0] == 429


def test_register_with_mail_verification_and_revocation(server):
    server["cfg"].smtp.update(host="smtp.example", **{"from": "lizenz@example"})
    code, res = post(server["url"], {"name": "Alex K", "email": "a@example.de", "consent": True})
    assert (code, res) == (200, {"status": "verify_sent"}) and server["mails"][0][0] == "verify"
    code_link = server["mails"][0][2]
    status, page = get(server["url"] + "/api/verify?t=" + code_link)
    assert status == 200 and b"AKM1." in page
    token = server["mails"][1][2]
    assert server["mails"][1][0] == "license" and licensing.parse(token).name == "Alex K"
    assert get(server["url"] + "/api/verify?t=" + code_link)[0] == 400                # nur einmal gültig
    # erneute Registrierung: Schlüssel noch einmal zusenden, gleiche Antwort (verrät nichts)
    assert post(server["url"], {"name": "Alex K", "email": "a@example.de", "consent": True})[1] == {"status": "verify_sent"}
    assert server["mails"][-1] == ("license", "a@example.de", token)
    # sperren → Sperrliste signiert und für das Programm lesbar
    lic_id = licensing.parse(token).id
    assert server["store"].revoke(lic_id, "Missbrauch")
    assert server["store"].revoke("L-OFFLINE12345")                                  # offline ausgestellt
    status, raw = get(server["url"] + "/api/revocations")
    assert status == 200 and licensing.parse_revocations(raw) == {lic_id, "L-OFFLINE12345"}
    # DSGVO-Löschung
    assert server["store"].delete_person("a@example.de") == 1
    row = server["store"].db.execute("SELECT * FROM licenses WHERE id=?", (lic_id,)).fetchone()
    assert row["email"] == "" and row["name"] == "" and row["token"] is None and row["status"] == "revoked"


def test_server_rejects_oversized_and_unknown(server):
    req = urllib.request.Request(server["url"] + "/api/register", data=b"x" * 5000, method="POST",
                                 headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 413
    assert get(server["url"] + "/api/admin")[0] == 404
    assert get(server["url"] + "/api/health") == (200, b'{"ok": true}')


# --- Oberfläche ---------------------------------------------------------------------------

def test_gui_license_dialog_and_enforcement(tmp_path, monkeypatch):
    from conftest import make_window
    from akustik.gui.license_dialog import LicenseDialog
    app, w = make_window(tmp_path, start=False)
    try:
        assert w.licenses.enabled and w.btn_license.text() == "Kostenlos registrieren"
        dlg = LicenseDialog(w.licenses, w)
        dlg.edit.setPlainText("Unsinn")
        dlg.apply()
        assert "kein AkustikMess" in dlg.lbl_error.text()
        dlg.edit.setPlainText(licensing.sign(payload(), SERVER_KEY, "server"))
        dlg.apply()
        assert dlg.lbl_error.text() == "" and "Alex" in dlg.lbl_status.text()
        assert w.btn_license.text().startswith("✔") and not w.licenses.has("pro")
        w.licenses._revocations({"L-TEST1234ABCD"})                                  # gesperrt
        assert w.licenses.status().state == "revoked" and "⚠" in w.btn_license.text()
        # Pflicht-Modus: ohne gültige Lizenz kein Audio
        monkeypatch.setattr(license_config, "ENFORCEMENT", "required")
        opened = []
        monkeypatch.setattr(w, "open_license", lambda: opened.append(True))
        w._license_changed(w.licenses.status())
        assert not w.a_run.isEnabled()
        w.toggle_audio(True)
        assert opened and not w.a_run.isChecked()
        w.licenses.settings.remove("license_revoked")
        w.licenses.install(licensing.sign(payload(plan="pro"), ROOT_KEY, "root"))
        assert w.a_run.isEnabled() and w.licenses.has("pro")
    finally:
        w.close()


def test_licensing_hidden_without_keys(tmp_path, monkeypatch):
    from conftest import make_window
    monkeypatch.setattr(license_config, "ROOT_PUBLIC_KEY", "")
    monkeypatch.setattr(license_config, "SERVER_PUBLIC_KEY", "")
    app, w = make_window(tmp_path, start=False)
    try:
        assert not w.licenses.enabled and not w.btn_license.isVisible() and not w.a_license.isVisible()
        assert w.licenses.has("pro")          # ohne Lizenzsystem ist nichts gesperrt
    finally:
        w.close()
