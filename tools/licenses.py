"""Lizenzen ausstellen (offline, auf dem Rechner des Projektinhabers).

Einmalig::

    python tools/licenses.py keygen-root                  # Root-Schlüssel (darf alle Pläne) – gut sichern!
    python tools/licenses.py set-server-key --public <B64> # öffentlicher Schlüssel des Lizenzservers

Lizenzen::

    python tools/licenses.py issue --name "Firma X" --email a@b.de --plan pro --updates-years 1
    python tools/licenses.py issue --name "Test" --email t@b.de --plan trial --days 30
    python tools/licenses.py list
    python tools/licenses.py show <SCHLÜSSEL oder Datei>

Sperren geht über den Lizenzserver (``license_server.py revoke <ID>``), weil die Programme die
Sperrliste von dort laden.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from akustik import licensing  # noqa: E402

LICENSE_CONFIG = ROOT / "akustik" / "license_config.py"
KEY_DIR = Path.home() / ".akustikmess"
ROOT_KEY = KEY_DIR / "license_root_key.pem"
LEDGER = KEY_DIR / "licenses_issued.jsonl"
ID_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # ohne 0/O/1/I


class ToolError(Exception):
    pass


def new_id() -> str:
    return "L-" + "".join(secrets.choice(ID_ALPHABET) for _ in range(12))


def write_key_config(name: str, value: str, path: Path | None = None) -> None:
    path = path or LICENSE_CONFIG
    text = path.read_text(encoding="utf-8")
    new, n = re.subn(rf'^{name} = ".*"$', f'{name} = "{value}"', text, flags=re.M)
    if n != 1:
        raise ToolError(f"{name} nicht in {path} gefunden")
    path.write_text(new, encoding="utf-8")


def generate_key(path: Path, force: bool = False):
    from cryptography.hazmat.primitives import serialization  # noqa: PLC0415
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: PLC0415
    if path.exists() and not force:
        raise ToolError(f"Schlüssel existiert bereits: {path} (ein neuer würde alle damit ausgestellten "
                        "Lizenzen ungültig machen; nur mit --force)")
    key = Ed25519PrivateKey.generate()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


def public_b64(key) -> str:
    from cryptography.hazmat.primitives import serialization  # noqa: PLC0415
    return base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw,
                                                          serialization.PublicFormat.Raw)).decode()


def load_key(path: Path):
    from cryptography.hazmat.primitives import serialization  # noqa: PLC0415
    if not path.exists():
        raise ToolError(f"Root-Schlüssel fehlt ({path}). Mit `keygen-root` erzeugen oder Sicherung zurückkopieren.")
    return serialization.load_pem_private_key(path.read_bytes(), password=None)


def make_payload(name: str, email: str, plan: str, *, days: int | None = None, expires: str | None = None,
                 updates_years: int | None = None, features=(), today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    if days and expires:
        raise ToolError("Entweder --days oder --expires angeben")
    exp = (today + dt.timedelta(days=days)).isoformat() if days else expires
    upd = today.replace(year=today.year + updates_years).isoformat() if updates_years else None
    return {"id": new_id(), "name": name.strip(), "email": email.strip().lower(), "plan": plan,
            "issued": today.isoformat(), "expires": exp, "updates_until": upd, "features": list(features)}


def issue(payload: dict, key, ledger: Path | None = None) -> str:
    token = licensing.sign(payload, key, "root")
    ledger = ledger or LEDGER
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with open(ledger, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(dict(payload, token=token), ensure_ascii=False) + "\n")
    return token


def read_token(arg: str) -> str:
    p = Path(arg)
    return p.read_text(encoding="utf-8").strip() if len(arg) < 300 and p.exists() else arg


# --- Befehle ------------------------------------------------------------------------------

def cmd_keygen_root(args) -> None:
    key = generate_key(ROOT_KEY, args.force)
    write_key_config("ROOT_PUBLIC_KEY", public_b64(key))
    print(f"Root-Schlüssel: {ROOT_KEY}\nÖffentlicher Teil in akustik/license_config.py eingetragen.\n"
          "WICHTIG: zusammen mit den anderen Schlüsseln in ~/.akustikmess sichern, nie auf Server/GitHub.")


def cmd_set_server_key(args) -> None:
    raw = base64.b64decode(args.public, validate=True)
    if len(raw) != 32:
        raise ToolError("Das ist kein öffentlicher Ed25519-Schlüssel (32 Byte, Base64)")
    write_key_config("SERVER_PUBLIC_KEY", args.public)
    print("Öffentlicher Schlüssel des Lizenzservers eingetragen. Gilt ab dem nächsten Release.")


def cmd_issue(args) -> None:
    payload = make_payload(args.name, args.email, args.plan, days=args.days, expires=args.expires,
                           updates_years=args.updates_years, features=args.feature or ())
    token = issue(payload, load_key(ROOT_KEY))
    if args.out:
        Path(args.out).write_text(token + "\n", encoding="utf-8")
    print(f"Lizenz {payload['id']} für {payload['name']} <{payload['email']}> – {payload['plan']}"
          f"{', bis ' + payload['expires'] if payload['expires'] else ''}"
          f"{', Updates bis ' + payload['updates_until'] if payload['updates_until'] else ''}\n\n{token}\n")
    if args.out:
        print(f"Als Datei gespeichert: {args.out} (in AkustikMess: Hilfe → Lizenz… → Aus Datei laden…)")


def cmd_list(args) -> None:
    if not LEDGER.exists():
        print("Noch keine Lizenzen ausgestellt.")
        return
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        p = json.loads(line)
        if args.search and args.search.lower() not in (p["name"] + p["email"] + p["id"]).lower():
            continue
        print(f"{p['id']}  {p['issued']}  {p['plan']:<10} {p['name']} <{p['email']}>"
              f"{'  bis ' + p['expires'] if p.get('expires') else ''}")


def cmd_show(args) -> None:
    lic = licensing.parse(read_token(args.token))
    st = licensing.evaluate(read_token(args.token))
    print(json.dumps(lic.__dict__, ensure_ascii=False, indent=1, default=list))
    print(f"Status: {st.state} – {st.message}")


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="AkustikMess-Lizenzen ausstellen", epilog=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("keygen-root", help="Root-Schlüssel erzeugen (einmalig)")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_keygen_root)
    p = sub.add_parser("set-server-key", help="öffentlichen Schlüssel des Lizenzservers eintragen")
    p.add_argument("--public", required=True)
    p.set_defaults(fn=cmd_set_server_key)
    p = sub.add_parser("issue", help="Lizenz ausstellen")
    p.add_argument("--name", required=True)
    p.add_argument("--email", required=True)
    p.add_argument("--plan", required=True, choices=sorted(licensing.PLAN_LABELS))
    p.add_argument("--days", type=int, help="gültig für N Tage (z. B. Testversion)")
    p.add_argument("--expires", help="gültig bis JJJJ-MM-TT")
    p.add_argument("--updates-years", type=int, help="Kauflizenz: Versionen der nächsten N Jahre")
    p.add_argument("--feature", action="append", help="zusätzliche Funktion freischalten (mehrfach)")
    p.add_argument("--out", help="Schlüssel zusätzlich als .akmlic-Datei speichern")
    p.set_defaults(fn=cmd_issue)
    p = sub.add_parser("list", help="ausgestellte Lizenzen anzeigen")
    p.add_argument("--search")
    p.set_defaults(fn=cmd_list)
    p = sub.add_parser("show", help="Schlüssel prüfen und anzeigen")
    p.add_argument("token")
    p.set_defaults(fn=cmd_show)
    args = ap.parse_args(argv)
    try:
        args.fn(args)
    except (ToolError, licensing.LicenseError, ValueError) as exc:
        print(f"FEHLER: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
