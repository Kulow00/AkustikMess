"""Lizenzen: signierte Lizenzschlüssel, die offline geprüft werden.

Format eines Schlüssels::

    AKM1.<base64url(JSON-Nutzdaten)>.<base64url(Ed25519-Signatur)>

Nutzdaten::

    {"v": 1, "id": "L-…", "iss": "root"|"server", "name": "…", "email": "…",
     "plan": "community"|"pro"|…, "features": [...], "issued": "2026-10-16",
     "expires": null|"2027-10-16", "updates_until": null|"2027-10-16"}

* ``expires``       – danach ist die Lizenz ungültig (Abo, Testlizenz)
* ``updates_until`` – Kauflizenz: gilt für alle Versionen, die bis zu diesem Tag erschienen sind

Datenschutz: Die Prüfung läuft vollständig lokal. Die Sperrliste wird nur zusammen mit der
Update-Suche geladen, also nur nach Zustimmung des Nutzers; dabei wird nichts gesendet.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import re
from dataclasses import dataclass, field

from . import license_config as cfg

PREFIX = "AKM1"
PLAN_LABELS = {"community": "Community (kostenlos)", "pro": "Pro", "trial": "Testversion"}
# Funktionen, die ein Plan zusätzlich zu den im Schlüssel genannten freischaltet
PLAN_FEATURES = {"community": (), "trial": ("pro",), "pro": ("pro",)}

_ID_RE = re.compile(r"^L-[A-Z0-9]{4,32}$")


class LicenseError(Exception):
    pass


@dataclass(frozen=True)
class License:
    id: str
    issuer: str
    name: str
    email: str
    plan: str
    issued: str
    expires: str | None = None
    updates_until: str | None = None
    features: tuple[str, ...] = ()

    @property
    def plan_label(self) -> str:
        return PLAN_LABELS.get(self.plan, self.plan)

    @property
    def all_features(self) -> frozenset[str]:
        return frozenset(self.features) | frozenset(PLAN_FEATURES.get(self.plan, ()))


@dataclass
class Status:
    state: str            # none | valid | expired | revoked | updates_expired | invalid
    license: License | None = None
    message: str = ""
    features: frozenset = field(default_factory=frozenset)

    @property
    def valid(self) -> bool:
        return self.state == "valid"


# --- Kodierung ----------------------------------------------------------------------------

def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _public_key(issuer: str):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey  # noqa: PLC0415
    b64 = {"root": cfg.ROOT_PUBLIC_KEY, "server": cfg.SERVER_PUBLIC_KEY}.get(issuer, "")
    if not b64:
        raise LicenseError(f"Aussteller „{issuer}“ ist in diesem Build nicht eingerichtet")
    return Ed25519PublicKey.from_public_bytes(base64.b64decode(b64))


def _date(s: str | None, what: str) -> dt.date | None:
    if s in (None, ""):
        return None
    try:
        return dt.date.fromisoformat(s)
    except (TypeError, ValueError) as exc:
        raise LicenseError(f"Ungültiges Datum für {what}") from exc


def sign(payload: dict, private_key, issuer: str) -> str:
    """Lizenzschlüssel erzeugen (Werkzeug/Server; das Programm selbst signiert nie)."""
    data = dict(payload, v=1, iss=issuer)
    validate_payload(data)
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"{PREFIX}.{_b64e(raw)}.{_b64e(private_key.sign(raw))}"


def validate_payload(p: dict) -> None:
    if p.get("v") != 1:
        raise LicenseError("Unbekanntes Lizenzformat")
    if not _ID_RE.match(str(p.get("id", ""))):
        raise LicenseError("Ungültige Lizenz-ID")
    if p.get("iss") not in ("root", "server"):
        raise LicenseError("Unbekannter Aussteller")
    if not isinstance(p.get("plan"), str) or not p["plan"]:
        raise LicenseError("Plan fehlt")
    for key in ("issued", "expires", "updates_until"):
        _date(p.get(key), key)
    if _date(p.get("issued"), "issued") is None:
        raise LicenseError("Ausstellungsdatum fehlt")
    if not isinstance(p.get("features", []), list):
        raise LicenseError("Ungültige Funktionsliste")


def parse(token: str) -> License:
    """Schlüssel prüfen (Format, Signatur, Berechtigung des Ausstellers). Ablauf prüft ``evaluate``."""
    from cryptography.exceptions import InvalidSignature  # noqa: PLC0415
    token = "".join((token or "").split())  # Zeilenumbrüche/Leerzeichen beim Kopieren ignorieren
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != PREFIX:
        raise LicenseError("Das ist kein AkustikMess-Lizenzschlüssel")
    try:
        raw, sig = _b64d(parts[1]), _b64d(parts[2])
        p = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise LicenseError("Lizenzschlüssel ist beschädigt (unvollständig kopiert?)") from exc
    if not isinstance(p, dict):
        raise LicenseError("Lizenzschlüssel ist beschädigt")
    issuer = p.get("iss")
    try:
        _public_key(str(issuer)).verify(sig, raw)
    except InvalidSignature as exc:
        raise LicenseError("Signatur ungültig – Schlüssel verändert oder nicht von AkustikMess") from exc
    validate_payload(p)
    if issuer == "server" and p["plan"] not in cfg.SERVER_PLANS:
        raise LicenseError(f"Plan „{p['plan']}“ darf nicht vom Lizenzserver ausgestellt werden")
    return License(id=p["id"], issuer=issuer, name=str(p.get("name", "")), email=str(p.get("email", "")),
                   plan=p["plan"], issued=p["issued"], expires=p.get("expires"),
                   updates_until=p.get("updates_until"), features=tuple(p.get("features", [])))


def evaluate(token: str | None, revoked: set[str] | frozenset = frozenset(), today: dt.date | None = None,
             release_date: str | None = None) -> Status:
    """Gesamtstatus für die Oberfläche."""
    if not token:
        return Status("none", message="Nicht registriert")
    try:
        lic = parse(token)
    except LicenseError as exc:
        return Status("invalid", message=str(exc))
    today = today or dt.date.today()
    if lic.id in revoked:
        return Status("revoked", lic, "Diese Lizenz wurde gesperrt")
    exp = _date(lic.expires, "expires")
    if exp is not None and today > exp:
        return Status("expired", lic, f"Abgelaufen am {exp:%d.%m.%Y}")
    upd = _date(lic.updates_until, "updates_until")
    rel = _date(release_date, "release_date") if release_date else None
    if upd is not None and rel is not None and rel > upd:
        return Status("updates_expired", lic,
                      f"Gilt für Versionen bis {upd:%d.%m.%Y}; diese Version ist vom {rel:%d.%m.%Y}")
    until = f", gültig bis {exp:%d.%m.%Y}" if exp else ""
    return Status("valid", lic, f"{lic.plan_label}{until}", lic.all_features)


# --- Sperrliste ---------------------------------------------------------------------------

def parse_revocations(raw: bytes) -> set[str]:
    """Signierte Sperrliste {"signed": "<json>", "signature": "…", "iss": "server"|"root"}."""
    from cryptography.exceptions import InvalidSignature  # noqa: PLC0415
    try:
        outer = json.loads(raw)
        signed, sig, issuer = outer["signed"], outer["signature"], outer["iss"]
        _public_key(issuer).verify(base64.b64decode(sig), signed.encode("utf-8"))
        ids = json.loads(signed)["revoked"]
    except (ValueError, KeyError, TypeError, InvalidSignature) as exc:
        raise LicenseError("Sperrliste ungültig") from exc
    return {i for i in ids if isinstance(i, str) and _ID_RE.match(i)}


def sign_revocations(ids, private_key, issuer: str) -> bytes:
    signed = json.dumps({"revoked": sorted(set(ids)),
                         "updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")})
    sig = base64.b64encode(private_key.sign(signed.encode("utf-8"))).decode()
    return json.dumps({"signed": signed, "signature": sig, "iss": issuer}).encode("utf-8")


def fetch_revocations(url: str | None = None, timeout: float = 10) -> set[str]:
    from . import update  # noqa: PLC0415
    url = url or cfg.REVOCATIONS_URL
    update.check_url_allowed(url)
    with update._open(url, timeout) as r:  # noqa: SLF001 – gleiche https-Regeln wie Updates
        return parse_revocations(r.read(256 * 1024))


def enabled() -> bool:
    return cfg.ENFORCEMENT != "off" and bool(cfg.ROOT_PUBLIC_KEY or cfg.SERVER_PUBLIC_KEY)
