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

ZIP_NAME = "AkustikMess-1.0.0-Windows.zip"


@pytest.fixture
def server(tmp_path, monkeypatch):
    from server import license_server as ls
    www = tmp_path / "www"
    (www / "files").mkdir(parents=True)
    payload = b"PK" + b"x" * 300_000
    (www / "files" / ZIP_NAME).write_bytes(payload)
    signed = json.dumps({"channels": {"stable": "1.0.0"}, "releases": [
        {"version": "1.0.0", "channel": "stable", "assets": {"windows": {"file": ZIP_NAME, "size": len(payload),
                                                                      "sha256": "abc"}}}]})
    (www / "releases.json").write_text(json.dumps({"signed": signed, "signature": ""}), encoding="utf-8")
    cfg = ls.Config({"AKM_DATA": str(tmp_path / "data"), "AKM_WWW": str(www), "AKM_SITE": "https://akmess.example",
                     "AKM_ADMIN_EMAIL": "lizenz@example.de", "SMTP_HOST": "smtp.example", "SMTP_FROM": "l@example.de"})
    store = ls.Store(cfg)
    store._key = SERVER_KEY
    mails = []
    mailer = {"admin": lambda c, row, tok: mails.append(("admin", c.admin, dict(row), tok)),
              "received": lambda c, row: mails.append(("received", row["email"])),
              "license": lambda c, row, lic, tok, again=False: mails.append(("license", row["email"], lic, tok, again))}
    srv = ThreadingHTTPServer(("127.0.0.1", 0), ls.make_handler(store, cfg, ls.RateLimiter(600, 50), mailer))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield {"url": f"http://127.0.0.1:{srv.server_address[1]}", "store": store, "cfg": cfg, "mails": mails,
           "payload": payload, "ls": ls}
    srv.shutdown()
    srv.server_close()


def call(url, path, data=None, ctype="application/json", headers=None, method=None):
    body = None
    if data is not None:
        body = data.encode() if isinstance(data, str) else json.dumps(data).encode()
    req = urllib.request.Request(url + path, data=body, method=method or ("POST" if body is not None else "GET"),
                                 headers={**({"Content-Type": ctype} if body is not None else {}), **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


def request_license(s, email="Alex@Example.de"):
    code, body, _ = call(s["url"], "/api/request", {"name": "Alex K", "email": email, "message": "FOH-Technik",
                                                    "consent": True})
    assert code == 200 and json.loads(body) == {"status": "requested"}


def approve(s):
    admin = [m for m in s["mails"] if m[0] == "admin"][-1]
    review = admin[3]
    code, page, _ = call(s["url"], f"/api/review?t={review}")
    assert code == 200 and b"Alex K" in page and b"FOH-Technik" in page and b"approve" in page
    assert s["store"].get(admin[2]["id"])["status"] == "requested"            # Öffnen allein gibt nicht frei
    code, page, _ = call(s["url"], "/api/review", f"t={review}&action=approve", "application/x-www-form-urlencoded")
    assert code == 200 and b"Lizenz erteilt" in page
    return [m for m in s["mails"] if m[0] == "license"][-1]


def test_request_needs_approval_and_mails(server):
    s = server
    request_license(s)
    kinds = [m[0] for m in s["mails"]]
    assert kinds == ["admin", "received"] and s["mails"][0][1] == "lizenz@example.de"
    assert s["mails"][0][2]["email"] == "alex@example.de"
    # zweite Anfrage derselben Adresse während offener Anfrage: keine neue Admin-Mail
    request_license(s)
    assert [m[0] for m in s["mails"]].count("admin") == 1
    lic_mail = approve(s)
    lic = licensing.parse(lic_mail[2])
    assert lic.email == "alex@example.de" and lic.issuer == "server" and lic_mail[1] == "alex@example.de"
    # Prüf-Link nur einmal nutzbar
    review = s["mails"][0][3]
    assert call(s["url"], "/api/review", f"t={review}&action=approve", "application/x-www-form-urlencoded")[0] == 410
    # Validierung und Honigtopf
    assert call(s["url"], "/api/request", {"name": "A", "email": "x@y.de", "consent": True})[0] == 400
    assert call(s["url"], "/api/request", {"name": "Alex", "email": "x@y.de", "consent": False})[0] == 400
    assert call(s["url"], "/api/request", {"name": "Bot", "email": "b@y.de", "consent": True, "website": "x"})[0] == 200
    assert s["store"].db.execute("SELECT COUNT(*) FROM licenses WHERE email='b@y.de'").fetchone()[0] == 0


def test_one_time_download_link(server):
    s = server
    request_license(s)
    tok = approve(s)[3]
    code, page, _ = call(s["url"], f"/api/download?t={tok}")
    assert code == 200 and ZIP_NAME.encode() in page and b"Windows" in page
    assert call(s["url"], f"/api/file/{ZIP_NAME}")[0] == 403                        # ohne Link/Lizenz
    code, data, headers = call(s["url"], f"/api/file/{ZIP_NAME}?t={tok}")
    assert code == 200 and data == s["payload"] and "attachment" in headers["Content-Disposition"]
    assert call(s["url"], f"/api/file/{ZIP_NAME}?t={tok}")[0] == 403                # nur einmal
    assert call(s["url"], f"/api/download?t={tok}")[0] == 410
    # Größe für die Online-Prüfung ohne Lizenz, aber keine Pfade außerhalb von files/
    code, _, headers = call(s["url"], f"/api/file/{ZIP_NAME}", method="HEAD")
    assert code == 200 and int(headers["Content-Length"]) == len(s["payload"])
    assert call(s["url"], "/api/file/..%2Freleases.json", method="HEAD")[0] == 404


def test_redownload_with_license_and_update_header(server):
    s = server
    request_license(s)
    key = approve(s)[2]
    lic_id = licensing.parse(key).id
    code, body, _ = call(s["url"], "/api/redownload", {"license": key[:30] + "\n" + key[30:]})
    url = json.loads(body)["url"]
    assert code == 200 and url.startswith("/api/download?t=")
    assert call(s["url"], url)[0] == 200
    code, body, _ = call(s["url"], "/api/redownload", {"email": "ALEX@example.de", "id": lic_id.lower()})
    assert code == 200 and "url" in json.loads(body)
    assert call(s["url"], "/api/redownload", {"email": "fremd@example.de", "id": lic_id})[0] == 403
    assert call(s["url"], "/api/redownload", {"license": "AKM1.kaputt.x"})[0] == 400
    # Programm-Update mit Lizenz im Header
    code, data, _ = call(s["url"], f"/api/file/{ZIP_NAME}", headers={"X-AKM-License": key})
    assert code == 200 and data == s["payload"]
    assert call(s["url"], f"/api/file/{ZIP_NAME}", headers={"X-AKM-License": "AKM1.x.y"})[0] == 401
    # Root-Lizenz (offline ausgestellt) funktioniert auch
    pro = licensing.sign(payload(id="L-PRO123456789", plan="pro"), ROOT_KEY, "root")
    assert call(s["url"], f"/api/file/{ZIP_NAME}", headers={"X-AKM-License": pro})[0] == 200
    # gesperrt → kein Download mehr
    s["store"].revoke(lic_id, "Missbrauch")
    assert call(s["url"], f"/api/file/{ZIP_NAME}", headers={"X-AKM-License": key})[0] == 403
    assert call(s["url"], "/api/redownload", {"license": key})[0] == 403
    status, raw, _ = call(s["url"], "/api/revocations")
    assert lic_id in licensing.parse_revocations(raw)
    # bereits lizenziert und erneut angefragt → Schlüssel + neuer Link per Mail (nach Entsperren)
    s["store"].revoke(lic_id, undo=True)
    request_license(s)
    assert s["mails"][-1][0] == "license" and s["mails"][-1][4] is True


def test_reject_and_gdpr_delete(server):
    s = server
    request_license(s, "b@example.de")
    review = s["mails"][-2][3]
    code, page, _ = call(s["url"], "/api/review", f"t={review}&action=reject", "application/x-www-form-urlencoded")
    assert code == 200 and b"abgelehnt" in page
    row = s["store"].db.execute("SELECT * FROM licenses WHERE email='b@example.de'").fetchone()
    assert row["status"] == "rejected"
    assert s["store"].delete_person("b@example.de") == 1


def test_server_rejects_oversized_and_unknown(server):
    req = urllib.request.Request(server["url"] + "/api/request", data=b"x" * 9000, method="POST",
                                 headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 413
    assert call(server["url"], "/api/admin")[0] == 404
    assert call(server["url"], "/api/register", {"name": "x"})[0] == 404           # alter Ablauf entfernt
    assert call(server["url"], "/api/health")[:2] == (200, b'{"ok": true}')
    assert call(server["url"], "/api/review?t=falsch")[0] == 410


# --- Oberfläche ---------------------------------------------------------------------------

def test_gui_license_dialog_and_enforcement(tmp_path, monkeypatch):
    from conftest import make_window
    from akustik.gui.license_dialog import LicenseDialog
    app, w = make_window(tmp_path, start=False)
    try:
        assert w.licenses.enabled and w.btn_license.text() == "Lizenz anfragen"
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
